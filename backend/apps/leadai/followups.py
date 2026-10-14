"""The shops playbook's automatic follow-ups (board T63, T25, T29; owner's choice Q7, 2026-10-14).

Matloob sends every campaign himself; what follows it is automatic, in chats whose playbook is
ic_shops (lane.playbook_for), and only while the chat is the assistant's: on the Lead AI screen,
not transferred, the assistant answering this customer, not stopped, paused, handed to a person
or "not interested", and the phone not on the opt-out registry (optout.py). Nothing goes while
the gateway's credit is out (gateway.credit, board C16): it waits.

- Template B, once (T63): intl_city_shops_followup from the chat's own number, when the shops
  campaign's template went out (sent, delivered or read) 72 hours to 14 days ago and nothing
  happened in the chat since: no word, tap or reaction from the customer, no message of ours or
  a colleague's. It is the second message after that send and the last one
  (``template_b_sent_at``); only a campaign sent to the lead again later has its own.
- The check-back (T25): the same Template B once, on the day a customer who said "Not now" asked
  us to check back (``followup_due_at``, cleared then; ``followup_sent_at``), and only while
  nothing happened in the chat since our "I'll check back with you": no word from the customer
  but a "thanks" or an emoji, and nothing from a colleague or from us (``engaged_since``). A
  chat taken up again is no longer waiting: its date is cleared (here, and by the turn that
  answers the customer, engine._apply), and the nudges may follow it.
- Both go only from 11:00 to 18:00 Dubai, Monday to Saturday, never on a closed date, and only
  where the template is APPROVED on the chat's own WABA; otherwise they wait, and the sweep
  looks again every minute. While the template is not approved the chat's row on the Lead AI
  screen says so (``panel_note``): a note, never an alert. A campaign sent with Template B
  itself gets no second copy of it.
- The nudges (T29, assistant/nudges.py): free-form, inside the 24-hour window with ten minutes
  to spare, when the assistant's own message is the last in the chat, reached WhatsApp, and
  asked something or invited them, nothing is booked, they were not invited twice already, and
  the customer has been silent two hours: the first nudge; the morning after at 10:30, still
  silent, the last one. Never more than two in a chat, and none after "Not now" or "I already
  rented".
- Before any of them goes, the chat's Bitrix lead is read once (``bitrix_blocks``): a Bot Status
  a person set (Handed to agent, Broker, Lost, Opted out) or WhatsApp Opt-out Yes holds it, and
  is applied as if Bitrix had told us (bitrix_status.apply), because that call from Bitrix is
  made once and never retried (board C12). A lead that cannot be read now: the send waits.

The sweep (tasks.send_due_reminders, every minute) only finds who is due and queues one task per
chat (tasks.send_follow_up), at most PER_SWEEP at a time. What keeps a chat from being due for
days (stopped, paused, handed over, not interested, on the registry, the template not approved
on its number, the campaign's template failed, a check-back nothing waits for) is filtered in
the query itself, and the rest is read a page at a time until PER_SWEEP are found, so chats
turned down never hide a due one further on. The task decides again, claims the chat's state
with one conditional update (two tasks never both send), sends outside any transaction, and
gives the claim back only when nothing reached the gateway or the gateway was out of credit: a
send that may have gone out is never repeated. A send refused for credit leaves its row FAILED;
that row is marked (payload ``attempt_failed``) and read past from then on, so the chat is due
again once the wallet is topped up. Template B is stored as ours (payload source
transcript.FOLLOW_UP) and read like the campaign it follows up (transcript.who): [Yes, book a
viewing] is a first answer, [Not now] the check-back's question. A nudge is the assistant's own
message (source leadai_ai, ``nudge`` 1 or 2).
"""

from __future__ import annotations

import datetime as dt
import logging

from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import CharField, DateTimeField, Exists, F, OuterRef, Q, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from apps.inbox.models import Message

from . import lane, shop_templates
from .assistant import hours, nudges, rules, shops, transcript
from .models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiOptOut, LeadAiSettings

logger = logging.getLogger(__name__)

TEMPLATE_B = shop_templates.FOLLOWUP_NAME
SOURCE = transcript.FOLLOW_UP
AFTER_CAMPAIGN = dt.timedelta(hours=72)
# Older than this, a campaign nobody answered gets no "quick follow-up" any more.
NOT_AFTER = dt.timedelta(days=14)
SEND_FROM = dt.time(11, 0)
SEND_UNTIL = dt.time(18, 0)
PER_SWEEP = 30
# The sweep reads its candidates this many at a time ...
SCAN = 200
# ... and at most this many of one kind in a minute (a safety valve: the query leaves hardly
# any that are not due).
READ_AT_MOST = 2000
# A conversation's last_message_at is stamped a moment after its message is stored.
SLACK = dt.timedelta(minutes=5)
SENT_STATUSES = (Message.Status.SENT, Message.Status.DELIVERED, Message.Status.READ)
# Invited twice and refused: no third invitation, in any words (engine.settle), so no nudge.
INVITED_TWICE = 2
# Our "I'll check back with you" goes in the turn that plans the check-back, a moment after
# that turn's own clock: within this long it is that confirmation, not a message since.
CONFIRM_SLACK = dt.timedelta(minutes=5)
# A row a send refused for "Insufficient credits" left behind (payload key): read past.
ATTEMPT_FAILED = "attempt_failed"
NO_CREDIT = "no_credit"

REENGAGE = "template_b"
CHECK_BACK = "check_back"
NUDGE_1 = "nudge_1"
NUDGE_2 = "nudge_2"
KINDS = (REENGAGE, CHECK_BACK, NUDGE_1, NUDGE_2)


# The rules ------------------------------------------------------------------------------------


def send_hours(now, closed_dates=()) -> bool:
    """Template B's hours: 11:00 to 18:00 Dubai, Monday to Saturday, not a closed date."""
    local = hours.now_dubai(now)
    return hours.is_open_day(local.date(), closed_dates) and SEND_FROM <= local.time() < SEND_UNTIL


def _sendable(template) -> bool:
    """Template B as it was submitted: one value ({{1}}, the first name) and no media header."""
    return template.variable_count == 1 and not template.requires_header_media


def _approved_rows():
    from apps.catalog.models import WaTemplate

    return WaTemplate.objects.filter(name=TEMPLATE_B, status=WaTemplate.Status.APPROVED)


def approved_template(number):
    """Template B, APPROVED on this number's WABA as it was submitted (English first), else None."""
    waba = str(getattr(number, "waba_business_id", "") or "")
    if not waba:
        return None
    rows = sorted(_approved_rows().filter(waba_business_id=waba), key=lambda row: (row.language != shop_templates.LANGUAGE, -row.pk))
    return next((row for row in rows if _sendable(row)), None)


def approved_wabas() -> set[str]:
    """The WABAs Template B can go from (one query for a whole page of the list)."""
    return {row.waba_business_id for row in _approved_rows() if _sendable(row)}


def credit_out() -> bool:
    """The gateway's wallet is out (board C16): nothing goes until it is topped up."""
    from apps.gateway.credit import credit_is_out

    return credit_is_out()


def blocked(conversation, chat, state, settings_row) -> str:
    """Why nothing automatic may go to this chat now, else ''."""
    from . import optout

    if chat is None or not chat.active:
        return "not on the Lead AI screen"
    if conversation.linked_conversation_id:
        return "transferred to another agent"
    if not settings_row.answers(conversation.contact.wa_id):
        return "the assistant is switched off"
    if state is not None:
        if state.stopped_at is not None:
            return "stopped"
        if state.paused_at is not None:
            return "paused"
        if state.handed_over_at is not None:
            return "handed to a person"
        if state.not_interested_at is not None:
            return "not interested"
    if optout.is_blocked(conversation.contact.wa_id):
        return "on the opt-out registry"
    return ""


def _real(messages):
    """The messages that are one: no system note, no copy from a linked chat, and no row of a
    follow-up the gateway refused for credit (it is tried again: ``_set_aside``)."""
    return messages.exclude(kind=Message.Kind.SYSTEM).exclude(mirrored_from__isnull=False).exclude(payload__has_key=ATTEMPT_FAILED)


def last_message(conversation):
    """The chat's newest message that is one (``_real``)."""
    return _real(Message.objects.filter(conversation=conversation)).order_by("-pk").first()


def campaign_template(conversation):
    """The newest template a campaign of this chat sent (its CampaignRecipient rows say which)."""
    templates = transcript.campaign_template_ids(conversation)
    if not templates:
        return None
    return (
        Message.objects.filter(
            conversation=conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template_id__in=templates
        )
        .order_by("-pk")
        .first()
    )


def reengage_due(conversation, state, now) -> bool:
    """T63: the campaign's template went out 72 hours to 14 days ago, is still the last thing in
    the chat (no reaction to it either), and no Template B followed it: one per campaign send
    (a lead sent the campaign again a month later gets its own). A campaign sent with Template B
    itself (Matloob may pick it in the popup) gets no second copy of it."""
    campaign = campaign_template(conversation)
    if campaign is None or campaign.status not in SENT_STATUSES or campaign.reactions:
        return False
    if campaign.template is not None and campaign.template.name == TEMPLATE_B:
        return False
    if state is not None and state.template_b_sent_at is not None and state.template_b_sent_at >= campaign.created_at:
        return False
    if not now - NOT_AFTER <= campaign.created_at <= now - AFTER_CAMPAIGN:
        return False
    last = last_message(conversation)
    return last is not None and last.pk == campaign.pk


def engaged_since(conversation, since) -> bool:
    """Anything happened in the chat after ``since`` (when the check-back was planned): a word or a
    tap from the customer that is more than a "thanks" or an emoji, or any message of a
    colleague's or ours, except our own "I'll check back with you" sent in that same turn."""
    rows = _real(Message.objects.filter(conversation=conversation, created_at__gt=since)).exclude(kind="reaction").exclude(transcript.REVOKED)
    for row in rows.only("direction", "kind", "body", "payload", "created_at").order_by("pk"):
        if row.direction == Message.Direction.OUTBOUND:
            if transcript.source(row) == transcript.ASSISTANT and row.created_at <= since + CONFIRM_SLACK:
                continue  # the confirmation itself
            return True
        if row.kind == "sticker" or (row.kind == "text" and rules.is_acknowledgement(row.body or "")):
            continue
        return True
    return False


def check_back_due(conversation, state, now) -> bool:
    """T25: the day the customer asked us to check back has come, and nothing happened since they
    asked (``engaged_since``): a customer who came back by themselves, or a colleague who took
    the chat, is not "checked back" with a marketing template on top of it."""
    if state is None or state.followup_due_at is None or state.followup_due_at > now:
        return False
    return not engaged_since(conversation, state.followup_due_at - shops.FOLLOW_UP_AFTER)


def check_back_moot(conversation, state, now) -> bool:
    """The check-back's day came for a chat taken up again since: nothing waits for it any more, so
    its date is cleared (the chat's row stops showing it, and the nudges may follow it). True when
    it was."""
    if state is None or state.followup_due_at is None or state.followup_due_at > now:
        return False
    if not engaged_since(conversation, state.followup_due_at - shops.FOLLOW_UP_AFTER):
        return False
    cleared = LeadAiChatState.objects.filter(pk=state.pk, followup_due_at=state.followup_due_at).update(followup_due_at=None)
    if cleared:
        logger.info("Lead AI check-back of conversation %s dropped: the chat was taken up again since", conversation.pk)
        _changed(conversation.pk)
    return bool(cleared)


def _open_appointment(conversation) -> bool:
    return LeadAiAppointment.objects.filter(conversation=conversation, status__in=LeadAiAppointment.OPEN).exists()


def nudge_due(conversation, state, now, settings_row) -> str:
    """T29: NUDGE_1 or NUDGE_2 when that nudge may go now, else ''."""
    if state is None or state.nudges >= nudges.MOST:
        return ""
    if state.invites >= INVITED_TWICE:
        return ""  # invited twice and not taken up: both nudges invite, so neither goes
    if state.followup_asked_at is not None or state.followup_due_at is not None:
        return ""  # they said "Not now": the check-back answers that, never a nudge
    if (state.facts or {}).get("already_rented") is True or _open_appointment(conversation):
        return ""
    last = last_message(conversation)
    if (
        last is None
        or last.direction != Message.Direction.OUTBOUND
        or transcript.source(last) != transcript.ASSISTANT
        or last.status not in SENT_STATUSES
    ):
        return ""
    window, closed = conversation.session_expires_at, settings_row.closed_dates
    if state.nudges == 0:
        if not nudges.asks_or_invites(transcript.outbound_text(last), last.kind, str(transcript.payload(last).get("shop_step") or "")):
            return ""
        return NUDGE_1 if nudges.first_due(now, last.created_at, window, closed) else ""
    # The first one went: the last one only while it is still the last word in the chat.
    if transcript.payload(last).get("nudge") != 1 or not nudges.second_due(now, state.nudged_at, window, closed):
        return ""
    from .assistant import engine

    return NUDGE_2 if nudges.today_slots(now, closed, engine.taken_slots(conversation, now)) else ""


def panel_note(conversation, state, approved: set) -> str:
    """Why this shops chat's Template B cannot go, for its row on the Lead AI screen: '' when the
    template is approved on its number, or the chat is not waiting for one."""
    if str(conversation.number.waba_business_id or "") in approved:
        return ""
    if state is not None and (state.stopped_at or state.paused_at or state.handed_over_at or state.not_interested_at):
        return ""
    check_back = state is not None and state.followup_due_at is not None
    never_answered = (state is None or state.template_b_sent_at is None) and conversation.last_inbound_at is None
    if not (check_back or never_answered):
        return ""
    return f"{TEMPLATE_B} is not approved on this number yet, so the automatic follow-up waits until Meta approves it."


# The sweep ---------------------------------------------------------------------------------------


def _shops_chats() -> set[int]:
    """The conversations of the active, not transferred Lead AI chats that follow the shops playbook."""
    ids = list(
        LeadAiChat.objects.filter(active=True, conversation__linked_conversation__isnull=True).values_list("conversation_id", flat=True)
    )
    return {pk for pk, playbook in lane.playbooks(ids).items() if playbook == lane.IC_SHOPS}


def messageable(conversations, settings_row):
    """These conversations without the ones ``blocked`` turns down for days, in the query itself:
    stopped, paused, handed to a person or not interested, the phone on the registry, the
    assistant not answering this customer. ``blocked`` still decides each one."""
    rows = conversations.filter(
        Q(lead_ai_state__isnull=True)
        | Q(
            lead_ai_state__stopped_at__isnull=True,
            lead_ai_state__paused_at__isnull=True,
            lead_ai_state__handed_over_at__isnull=True,
            lead_ai_state__not_interested_at__isnull=True,
        )
    ).filter(~Exists(LeadAiOptOut.objects.filter(phone=OuterRef("contact__wa_id"))))
    if not settings_row.assistant_enabled:
        tested = {"".join(ch for ch in str(number) if ch.isdigit()) for number in settings_row.test_numbers or []}
        rows = rows.filter(contact__wa_id__in=[number for number in tested if number])
    return rows


def due_now(now=None) -> list[tuple[int, str]]:
    """[(conversation id, kind)] of the shops chats that are due a follow-up now (the sweep's look;
    the task decides again)."""
    from apps.inbox.models import Conversation

    now = now or timezone.now()
    settings_row = LeadAiSettings.load()
    shops_ids = _shops_chats()
    if not shops_ids:
        return []
    found: list[tuple[int, str]] = []
    seen: set[int] = set()

    def consider(conversation, kind_of) -> None:
        if conversation.pk in seen or len(found) >= PER_SWEEP:
            return
        chat = getattr(conversation, "lead_ai_chat", None)
        state = LeadAiChatState.objects.filter(conversation=conversation).first()
        if blocked(conversation, chat, state, settings_row):
            return
        kind = kind_of(conversation, state)
        if kind:
            seen.add(conversation.pk)
            found.append((conversation.pk, kind))

    def walk(rows, kind_of, label: str) -> None:
        """Every candidate, in pk order and a page at a time, until PER_SWEEP are found: the ones
        turned down here never hide a due chat further on."""
        after = read = 0
        while len(found) < PER_SWEEP:
            if read >= READ_AT_MOST:
                logger.warning("Lead AI follow-up sweep read %s %s candidates and stopped; the rest wait a minute", read, label)
                return
            page = list(rows.filter(pk__gt=after).order_by("pk")[:SCAN])
            for conversation in page:
                consider(conversation, kind_of)
            if len(page) < SCAN:
                return
            read += len(page)
            after = page[-1].pk

    base = messageable(Conversation.objects.select_related("contact", "number", "lead_ai_chat").filter(pk__in=shops_ids), settings_row)
    if send_hours(now, settings_row.closed_dates):
        approved = approved_wabas()
        # Template B waits for Meta's approval on the chat's own number; its row on the screen says so.
        on_approved = base.filter(number__waba_business_id__in=sorted(approved))

        def template_kind(kind):
            def decide(conversation, state):
                if str(conversation.number.waba_business_id or "") not in approved:
                    return ""
                if kind == REENGAGE:
                    return kind if reengage_due(conversation, state, now) else ""
                if check_back_due(conversation, state, now):
                    return kind
                check_back_moot(conversation, state, now)  # taken up again since: nothing waits for it
                return ""

            return decide

        walk(on_approved.filter(lead_ai_state__followup_due_at__lte=now), template_kind(CHECK_BACK), "check-back")
        # Only chats whose newest message is a template that reached WhatsApp 72 hours to 14 days ago,
        # not Template B itself, with no Template B since (reengage_due decides the rest).
        quiet = (
            _with_last(on_approved.filter(last_message_at__gte=now - NOT_AFTER - SLACK))
            .filter(
                last_direction=Message.Direction.OUTBOUND,
                last_kind=Message.Kind.TEMPLATE,
                last_status__in=SENT_STATUSES,
                last_created__lte=now - AFTER_CAMPAIGN + SLACK,
                last_created__gte=now - NOT_AFTER - SLACK,
            )
            .exclude(last_template=TEMPLATE_B)
            .filter(
                Q(lead_ai_state__isnull=True)
                | Q(lead_ai_state__template_b_sent_at__isnull=True)
                | Q(lead_ai_state__template_b_sent_at__lt=F("last_created") - SLACK)
            )
        )
        walk(quiet, template_kind(REENGAGE), "Template B")
    # Only chats whose newest message is the assistant's own, delivered, two hours old, with nothing
    # booked, no "Not now" and no second refusal (nudge_due decides the rest).
    silent = (
        _with_last(
            base.filter(
                session_expires_at__gte=now + nudges.WINDOW_MARGIN,
                lead_ai_state__nudges__lt=nudges.MOST,
                lead_ai_state__invites__lt=INVITED_TWICE,
                lead_ai_state__followup_asked_at__isnull=True,
                lead_ai_state__followup_due_at__isnull=True,
            )
        )
        .filter(
            last_direction=Message.Direction.OUTBOUND,
            last_source=transcript.ASSISTANT,
            last_status__in=SENT_STATUSES,
            last_created__lte=now - nudges.SILENT_FOR + SLACK,
        )
        .filter(~Exists(LeadAiAppointment.objects.filter(conversation=OuterRef("pk"), status__in=LeadAiAppointment.OPEN)))
    )
    walk(silent, lambda conversation, state: nudge_due(conversation, state, now, settings_row), "nudge")
    return found


def _with_last(conversations):
    """The conversations with their newest message's direction, kind, payload source, status, time
    and template name (as last_message reads it: ``_real``), in one query."""
    newest = _real(Message.objects.filter(conversation=OuterRef("pk"))).order_by("-pk")
    return conversations.annotate(
        last_direction=Subquery(newest.values("direction")[:1]),
        last_kind=Subquery(newest.values("kind")[:1]),
        last_source=Subquery(
            newest.annotate(source_key=KeyTextTransform("source", "payload")).values("source_key")[:1], output_field=CharField()
        ),
        last_status=Subquery(newest.values("status")[:1]),
        last_created=Subquery(newest.values("created_at")[:1], output_field=DateTimeField()),
        last_template=Subquery(newest.values("template__name")[:1], output_field=CharField()),
    )


def sweep(now=None) -> int:
    """Queue the due follow-ups (one task per chat); how many were queued. Nothing while credit is out."""
    from .tasks import send_follow_up

    if credit_out():
        return 0
    due = due_now(now)
    for conversation_id, kind in due:
        send_follow_up.delay(conversation_id, kind)
    return len(due)


# Sending -------------------------------------------------------------------------------------------


def _nothing_sent(conversation, attempt: str) -> bool:
    """No message of this attempt was stored: the send stopped before the gateway."""
    return not Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__attempt=attempt).exists()


def _no_credit(exc) -> bool:
    from apps.gateway.credit import is_no_credit

    return is_no_credit(str(exc))


def _set_aside(conversation, attempt: str) -> None:
    """The rows of an attempt the gateway refused for credit: marked, so that the chat reads as it
    did before (``_real``) and the follow-up is due again once the wallet is topped up. The row
    stays in the thread, FAILED, as the agents saw it."""
    for row in Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__attempt=attempt):
        row.payload = {**(row.payload if isinstance(row.payload, dict) else {}), ATTEMPT_FAILED: NO_CREDIT}
        row.save(update_fields=["payload"])


def _enum_id(value) -> int | None:
    """A Bitrix enumeration field as crm.lead.get returns it ("2481", 2481, ["2481"], "", None)."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def bitrix_blocks(conversation, chat) -> str:
    """What the chat's Bitrix lead says against an automatic send, else ''.

    A person's Bot Status (Handed to agent, Broker, Lost, Opted out) or WhatsApp Opt-out Yes
    reaches us through one call from Bitrix (board C12) that is never retried: a lost call must
    not let a marketing template or a nudge go to someone a person stopped or took over. So the
    lead is read once here (a REST read, nothing written) and what it says is applied as if
    Bitrix had sent it (bitrix_status.apply, which changes nothing twice). A lead that cannot be
    read now holds the send until the next sweep. No Bitrix, or no lead: nothing to read."""
    from apps.crmlink import client

    from . import bitrix_status
    from .assistant import crm, crm_fields

    if not client.configured():
        return ""
    lead = crm_fields.lead_of(chat, conversation)
    if lead is None:
        return ""
    try:
        row = crm.read_record("lead", lead)["fields"] or {}
    except client.BitrixError as exc:
        logger.info("Lead AI could not read lead %s before a follow-up: %s", lead, exc)
        return "the Bitrix lead could not be read; tried again later"
    except Exception:  # noqa: BLE001 - nothing goes on a read we cannot trust
        logger.exception("Lead AI could not read lead %s before a follow-up", lead)
        return "the Bitrix lead could not be read; tried again later"
    bot = _enum_id(row.get(crm_fields.FIELD_BOT_STATUS)) if isinstance(row, dict) else None
    opt = _enum_id(row.get(crm_fields.FIELD_OPT_OUT)) if isinstance(row, dict) else None
    wanted = bitrix_status.effects(bot, opt)
    if not wanted:
        return ""
    bitrix_status.apply(lead, bot_status=bot, wa_opt_out=opt)
    return f"the Bitrix lead says {', '.join(wanted)}"


def _first_name(conversation, state) -> str:
    from .assistant import engine, filters

    return filters.first_name(engine._customer_name(conversation, (state.facts if state is not None else None) or {}))


def send(conversation_id: int, kind: str) -> str:
    """One chat's follow-up of this kind, if it is still due now: "sent", or why not."""
    from apps.inbox.models import Conversation

    now = timezone.now()
    conversation = Conversation.objects.select_related("contact", "number").filter(pk=conversation_id).first()
    if conversation is None or kind not in KINDS:
        return "no such chat"
    if lane.playbook_for(conversation) != lane.IC_SHOPS:
        return "not a shops chat"
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    state = LeadAiChatState.objects.filter(conversation=conversation).first()
    settings_row = LeadAiSettings.load()
    why = blocked(conversation, chat, state, settings_row)
    if why:
        return why
    if credit_out():
        return "the gateway is out of credit"
    if kind in (REENGAGE, CHECK_BACK):
        if not send_hours(now, settings_row.closed_dates):
            return "outside Template B's hours"
        if approved_template(conversation.number) is None:
            return "Template B is not approved on this number"
        if kind == REENGAGE and not reengage_due(conversation, state, now):
            return "not due"
        if kind == CHECK_BACK and not check_back_due(conversation, state, now):
            check_back_moot(conversation, state, now)
            return "not due"
    elif nudge_due(conversation, state, now, settings_row) != kind:
        return "not due"
    why = bitrix_blocks(conversation, chat)
    if why:
        return why
    if kind in (REENGAGE, CHECK_BACK):
        return _send_template_b(conversation, state, settings_row, kind, now)
    return _send_nudge(conversation, state, settings_row, kind, now)


def _send_template_b(conversation, state, settings_row, kind: str, now) -> str:
    from apps.inbox import services as inbox_services

    from .assistant import reminders

    template = approved_template(conversation.number)
    if template is None:
        return "Template B is not approved on this number"
    state = state or LeadAiChatState.for_conversation(conversation)
    rows = LeadAiChatState.objects.filter(pk=state.pk)
    if kind == REENGAGE:
        sent_for = campaign_template(conversation).created_at  # reengage_due found it just now
        before = state.template_b_sent_at
        claimed = rows.filter(Q(template_b_sent_at__isnull=True) | Q(template_b_sent_at__lt=sent_for)).update(template_b_sent_at=now)

        def undo():
            rows.filter(template_b_sent_at=now).update(template_b_sent_at=before)

    else:
        due, before = state.followup_due_at, state.followup_sent_at
        claimed = rows.filter(followup_due_at=due).update(followup_due_at=None, followup_sent_at=now)

        def undo():
            rows.filter(followup_due_at__isnull=True, followup_sent_at=now).update(followup_due_at=due, followup_sent_at=before)

    if not claimed:
        return "another task has it"
    attempt = f"{kind}:{now.isoformat()}"
    values = {"1": reminders.template_value(_first_name(conversation, state) or "there")}
    try:
        inbox_services.send_template(conversation, None, template, values, payload={"source": SOURCE, "followup": kind, "attempt": attempt})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded; the agents see the failed message in the chat
        if _nothing_sent(conversation, attempt) or _no_credit(exc):
            _set_aside(conversation, attempt)
            undo()
            logger.info("Lead AI Template B for conversation %s did not go (%s); it waits", conversation.pk, exc)
            return f"not sent ({type(exc).__name__}); tried again later"
        logger.warning("Lead AI Template B for conversation %s failed: %s", conversation.pk, exc)
        return f"failed ({type(exc).__name__})"
    _changed(conversation.pk)
    return "sent"


def _send_nudge(conversation, state, settings_row, kind: str, now) -> str:
    from apps.inbox import services as inbox_services

    from .assistant import engine, shop_flow

    facts = state.facts or {}
    language = state.language or "en"
    name = _first_name(conversation, state)
    closed = settings_row.closed_dates
    if kind == NUDGE_1:
        text = nudges.first_text(
            language, name, shop_type=shop_flow.type_in_view({}, facts, settings_row.shops_facts),
            business=facts.get("business_activity") or "", now=now, closed_dates=closed,
        )
    else:
        text = nudges.second_text(language, name, nudges.today_slots(now, closed, engine.taken_slots(conversation, now)))
    number = 1 if kind == NUDGE_1 else 2
    before = state.nudged_at
    rows = LeadAiChatState.objects.filter(pk=state.pk)
    if not rows.filter(nudges=number - 1).update(nudges=number, nudged_at=now):
        return "another task has it"
    attempt = f"{kind}:{now.isoformat()}"
    try:
        inbox_services.send_text(conversation, None, text, payload={"source": transcript.ASSISTANT, "nudge": number, "attempt": attempt})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - the chat shows the failed message
        if _nothing_sent(conversation, attempt) or _no_credit(exc):
            _set_aside(conversation, attempt)
            rows.filter(nudges=number, nudged_at=now).update(nudges=number - 1, nudged_at=before)
            logger.info("Lead AI nudge %s for conversation %s did not go (%s)", number, conversation.pk, exc)
            return f"not sent ({type(exc).__name__})"
        logger.warning("Lead AI nudge %s for conversation %s failed: %s", number, conversation.pk, exc)
        return f"failed ({type(exc).__name__})"
    return "sent"


def _changed(conversation_id: int) -> None:
    from .assistant import live

    live.appointment_changed(conversation_id)
