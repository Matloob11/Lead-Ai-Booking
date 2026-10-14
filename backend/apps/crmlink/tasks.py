"""Putting the WhatsApp conversation where the CRM can see it.

Two jobs, both out of band. Nothing here may delay a message reaching an agent,
and nothing here may lose one either: if Bitrix is down, the message is already
stored and only its copy in the timeline is missing.

A passing Bitrix failure (client.BitrixTransient: the REST throttle's 429, a 5xx,
an answer that is not JSON, a timeout, no rate-limit slot) is tried again later
with a growing wait, instead of costing the message its line for good. A lookup
that failed that way is never taken for "no record": the mirror asks strictly
and tries again. The Mirror table makes each (message, record) post once, so a
new try posts only what is still missing, and a post whose answer was lost after
it was sent (it may be on the timeline already) is looked for there before it is
sent again.

Both tasks are background work (client.background). They share the worker with
the webhooks, so they never sleep there waiting for a rate-limit slot: they take
one only when it is free now, leave the rest of the budget to campaigns, Lead AI
and the panel, stop asking for a minute after Bitrix timed out, and no more than
two of them talk to Bitrix at once (redis_state.held_one_of). A task that cannot
go now comes back later; a turn lost to a busy moment does not use up a try.
"""

import logging
import random
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Case, CharField, Exists, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.utils import timezone

from apps.inbox.models import Conversation, Message

from . import client, redis_state, summary as ai
from .models import Mirror

logger = logging.getLogger(__name__)

# Where the pinned summary lives on a lead or contact. Created by
# `manage.py setup_crm_fields`, which is safe to run again.
FIELD_SUMMARY = "UF_CRM_WA_SUMMARY"
FIELD_CLIENT = "UF_CRM_WA_CLIENT_SCORE"
FIELD_AGENT = "UF_CRM_WA_AGENT_SCORE"

# Contacts get their own copies of the same fields, under the portal's own
# naming for that entity.
CONTACT_FIELDS = {
    FIELD_SUMMARY: "UF_CRM_WA_SUMMARY",
    FIELD_CLIENT: "UF_CRM_WA_CLIENT_SCORE",
    FIELD_AGENT: "UF_CRM_WA_AGENT_SCORE",
}

# Seconds before each new try after a passing failure: about 30 s, 1, 2, 5, 10, 20, 30 and 30
# minutes, each up to a fifth longer at random so that a backlog does not come back all at once:
# about an hour and a half in all, which outlasts a busy campaign that keeps the shared budget
# (background work takes only what is left). Every countdown stays far below the broker's
# one-hour visibility timeout, past which Redis would hand the waiting task out a second time.
MIRROR_RETRY_SECONDS = (30, 60, 120, 300, 600, 1200, 1800, 1800)
# The summary costs a model call per try and is rewritten every few messages anyway.
SUMMARY_RETRY_SECONDS = (60, 300, 900)
JITTER = 0.2
# A busy turn (another run of the same message posting now, or every background slot taken)
# comes back in 15 to 75 s, at random, without using up a try; this many times at most, then
# it counts as a failed try.
DEFER_SECONDS = (15, 75)
MAX_DEFERRALS = 20
BACKGROUND_SLOTS = "crmlink:background"

# What a Lead AI chat's crm_entity can name (apps.leadai.lane._crm_ref) that is a person's
# record of its own. Owner Data is not among them: the Owner Data search finds every card
# carrying the number, that one included.
OWN_RECORD_TYPES = ("lead", "contact", "deal")
OWNER_DATA = f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}"

# A campaign's own template: process_recipient stamps last_attempt_at, files the Owner Data card
# (a few Bitrix calls, each of which may wait for its slot) and only then stores the message.
CAMPAIGN_SEND_WINDOW = timedelta(minutes=30)


def _countdown(schedule, retries):
    base = schedule[min(retries, len(schedule) - 1)]
    return int(round(base * random.uniform(1.0, 1.0 + JITTER)))


# Which records a message belongs on
# ---------------------------------------------------------------------------


def _lead_ai_chat(conversation):
    """The chat's LeadAiChat (crm_entity, crm_id), whether still on the Lead AI screen or moved to
    the inbox since, or None. In a savepoint: a failure here must not break a caller's
    transaction."""
    from apps.leadai.models import LeadAiChat

    try:
        with transaction.atomic():
            return LeadAiChat.objects.filter(conversation_id=conversation.pk).values("crm_entity", "crm_id").first()
    except DatabaseError:
        logger.exception("Could not read the Lead AI record of conversation %s", conversation.pk)
        return None


def _own_record(conversation, at=None):
    """The record a Lead AI campaign was sent from, when it is a lead, contact or deal (T57).

    Matloob (2026-10-14): every message of a Lead AI chat (customer, assistant, agent) belongs on
    THAT lead's timeline. The duplicate search by phone picks the first person-like lead Bitrix
    returns, which is often another lead of the same customer (906 International City shop leads
    hold about 531 phones).

    The campaign is the newest Lead AI campaign that had reached the chat by ``at`` (the message's
    time; now when None): its lead, else its deal. That is the lead the Lead AI writes its fields
    to (apps.leadai.assistant.crm_fields.lead_of), so a shops campaign sent from another lead to a
    chat already on the screen moves the conversation to that lead, from that send on. A chat with
    no such send by then (its history from before, or one sent from Owner Data or Contacts) uses
    the record it came onto the Lead AI screen with (LeadAiChat), still or since moved to the
    inbox. Any other chat has no own record. ``own_record_annotations`` is the same in SQL.
    """
    from apps.campaigns.models import CampaignRecipient

    chat = _lead_ai_chat(conversation)
    if chat is None:
        return None
    try:
        with transaction.atomic():
            sends = CampaignRecipient.objects.filter(conversation_id=conversation.pk, campaign__lead_ai__isnull=False)
            if at is not None:
                sends = sends.filter(last_attempt_at__lte=at)
            newest = sends.order_by("-pk").values("crm_lead_id", "crm_deal_id").first()
    except DatabaseError:
        logger.exception("Could not read the Lead AI campaigns of conversation %s", conversation.pk)
        newest = None
    if newest and newest.get("crm_lead_id"):
        return {"type": "lead", "id": int(newest["crm_lead_id"]), "kind": "lead"}
    if newest and newest.get("crm_deal_id"):
        return {"type": "deal", "id": int(newest["crm_deal_id"]), "kind": "deal"}
    entity = str(chat.get("crm_entity") or "").strip().lower()
    crm_id = chat.get("crm_id")
    if entity not in OWN_RECORD_TYPES or not crm_id:
        return None
    return {"type": entity, "id": int(crm_id), "kind": entity}


def own_record_annotations():
    """_own_record in SQL, at each message's own time, for a Message queryset: two steps of
    annotations, ``own_type`` and ``own_id`` (NULL when the message's chat has no own record).

    For the back-fill: queryset.annotate(**steps[0]).annotate(**steps[1]).
    """
    from apps.campaigns.models import CampaignRecipient

    sends = CampaignRecipient.objects.filter(
        conversation_id=OuterRef("conversation_id"),
        campaign__lead_ai__isnull=False,
        last_attempt_at__lte=OuterRef("created_at"),
    ).order_by("-pk")
    first = {
        "newest_lead": Subquery(sends.values("crm_lead_id")[:1], output_field=IntegerField()),
        "newest_deal": Subquery(sends.values("crm_deal_id")[:1], output_field=IntegerField()),
    }
    in_chat = Q(conversation__lead_ai_chat__isnull=False)
    chat_own = in_chat & Q(
        conversation__lead_ai_chat__crm_entity__in=OWN_RECORD_TYPES,
        conversation__lead_ai_chat__crm_id__isnull=False,
    )
    second = {
        "own_type": Case(
            When(in_chat & Q(newest_lead__isnull=False), then=Value("lead")),
            When(in_chat & Q(newest_deal__isnull=False), then=Value("deal")),
            When(chat_own, then=F("conversation__lead_ai_chat__crm_entity")),
            default=Value(None),
            output_field=CharField(),
        ),
        "own_id": Case(
            When(in_chat & Q(newest_lead__isnull=False), then=F("newest_lead")),
            When(in_chat & Q(newest_deal__isnull=False), then=F("newest_deal")),
            When(chat_own, then=F("conversation__lead_ai_chat__crm_id")),
            default=Value(None),
            output_field=IntegerField(),
        ),
    }
    return first, second


def _records_for(conversation, strict=False, at=None):
    """Every CRM record this customer's number belongs to: the person (a lead or a
    contact) and the Owner Data cards.

    A Lead AI chat whose campaign was sent from a lead, contact or deal names its
    person itself (board T57, _own_record), and no duplicate search is made for
    it; its Owner Data cards are found by phone as everywhere else. Any other chat
    asks Bitrix by phone, as it always has.

    Looked up per number and kept for about ten minutes (client.find_records,
    cached=True), so an active chat asks Bitrix once rather than for every
    message. A lead created after the first message — the normal order of things
    when a customer writes before anybody has entered them — is found once that
    entry expires (an answer of "no record" is kept two minutes only), or at once
    when it is created from here (client.create_lead and create_owner_data drop
    it).

    ``strict``: a passing Bitrix failure raises client.BitrixTransient rather
    than reading as "no record". ``at``: the message's time, for _own_record.
    """
    wa_id = conversation.contact.wa_id
    own = _own_record(conversation, at=at)
    if own is None:
        return client.find_records(wa_id, strict=strict, cached=True)
    return [own] + client.owner_data_records(wa_id, strict=strict, cached=True)


def _line_with_role(message, role):
    """Live timeline line, with Tenant or Owner when the chat came from Renewals."""
    line = _line(message)
    label = {"tenant": "Tenant", "owner": "Owner"}.get(str(role or "").strip().lower())
    if not label:
        return line
    return line.replace("WhatsApp · ", f"WhatsApp · {label} · ", 1)


def _renewal_deals(conversation):
    """Deals a Renewals campaign already messaged on this WhatsApp number.

    Looked up by the number we sent from and the customer's phone, so a later
    reply — from them or from an agent — lands on the same deal timeline.
    """
    from apps.campaigns.models import CampaignRecipient

    phone = "".join(ch for ch in str(getattr(conversation.contact, "wa_id", "") or "") if ch.isdigit())
    number_id = getattr(conversation, "number_id", None)
    if not phone or not number_id:
        return []
    found = {}
    rows = (
        CampaignRecipient.objects.filter(
            phone=phone,
            campaign__number_id=number_id,
            crm_deal_id__isnull=False,
        )
        .exclude(status=CampaignRecipient.Status.SKIPPED)
        .order_by("id")
    )
    for row in rows:
        found[int(row.crm_deal_id)] = row.crm_role or ""
    return [
        {"type": "deal", "id": deal_id, "kind": "deal", "role": role}
        for deal_id, role in found.items()
    ]


def _mirror_records(conversation, strict=False, at=None):
    """Lead, contact, Owner Data, plus any Renewals deal this chat was sent to."""
    records = list(_records_for(conversation, strict=strict, at=at))
    seen = {(record["type"], record["id"]): record for record in records}
    for record in _renewal_deals(conversation):
        key = (record["type"], record["id"])
        if key in seen:
            # A Lead AI chat sent from a Renewals deal names that deal itself: keep the
            # Tenant / Owner label its lines carry.
            if record.get("role") and not seen[key].get("role"):
                seen[key]["role"] = record["role"]
            continue
        seen[key] = record
        records.append(record)
    return records


def _record_for(conversation):
    """The first of them, for the one caller that only wants somewhere to write."""
    records = _records_for(conversation)
    return records[0] if records else None


def campaign_sends():
    """Q for an outbound template one of our campaigns sent: the campaign posts its own copy of it
    (campaigns.services, renewals.post_deal_timeline), so the mirror never posts it, whether it
    runs before the send's transaction commits (and finds no message) or after.

    Sent by a campaign: a recipient of a campaign on this line, with this template, to this
    chat or this phone, whose attempt began at most CAMPAIGN_SEND_WINDOW before the message was
    stored. The Lead AI's own templates (a reminder, Template B: payload source "leadai...")
    are never a campaign's, whatever template they use.
    """
    from apps.campaigns.models import CampaignRecipient

    sends = CampaignRecipient.objects.filter(
        campaign__number_id=OuterRef("conversation__number_id"),
        campaign__template_id=OuterRef("template_id"),
        last_attempt_at__gte=OuterRef("created_at") - CAMPAIGN_SEND_WINDOW,
        last_attempt_at__lte=OuterRef("created_at"),
    ).filter(Q(conversation_id=OuterRef("conversation_id")) | Q(phone=OuterRef("conversation__contact__wa_id")))
    # has_key first: on a payload without "source" the key reads as SQL NULL, and a bare negated
    # startswith would drop that row instead of keeping it.
    lead_ai_own = Q(payload__has_key="source") & Q(payload__source__startswith="leadai")
    return (
        Q(direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template__isnull=False)
        & ~lead_ai_own
        & Exists(sends)
    )


def _campaign_send(message):
    if message.direction != Message.Direction.OUTBOUND or message.kind != Message.Kind.TEMPLATE:
        return False
    return Message.objects.filter(pk=message.pk).filter(campaign_sends()).exists()


def _was_lead_ai(conversation):
    """The chat is, or once was, a Lead AI chat (moved to the inbox since or not)."""
    return _lead_ai_chat(conversation) is not None


def _line(message):
    """One message, as the timeline should read it."""
    who = "Customer" if message.direction == Message.Direction.INBOUND else "Agent"
    if message.direction == Message.Direction.OUTBOUND and message.sent_by:
        who = f"Agent · {message.sent_by.display_name or message.sent_by.get_username()}"
    payload = message.payload if isinstance(message.payload, dict) else {}
    if message.direction == Message.Direction.OUTBOUND and str(payload.get("source") or "").startswith("leadai"):
        # Written by the Lead AI assistant, not by a person.
        who = "Lead AI assistant"

    body = (message.body or "").strip()
    if not body:
        body = f"[{message.get_kind_display().lower()}]"
    elif message.kind != Message.Kind.TEXT:
        body = f"[{message.get_kind_display().lower()}] {body}"

    stamp = timezone.localtime(message.created_at).strftime("%d %b %H:%M")
    return f"WhatsApp · {who} · {stamp}\n{body}"


def _where(records):
    return ", ".join(f"{record['type']} {record['id']}" for record in records)


# The mirror
# ---------------------------------------------------------------------------


def _found_by_phone(record, own):
    """Whether the record came from the lookup by phone (and so maybe from its cache)."""
    if own is not None and (record["type"], record["id"]) == (own["type"], own["id"]):
        return False
    return record["type"] in ("lead", "contact", OWNER_DATA)


def _known_comments(record):
    """The latest comment ids this record holds for other messages (find_comment's ``skip``)."""
    return set(
        Mirror.objects.filter(entity_type=record["type"], entity_id=record["id"], comment_id__isnull=False)
        .order_by("-id")
        .values_list("comment_id", flat=True)[:500]
    )


def _post(message, check=(), look_first=False):
    """Posts the message on each of its records that does not have it yet.

    Returns (records, failed, unsure), each of the last two a list of (record, BitrixTransient):

    - ``failed``: a post that provably never ran; the next try simply posts it;
    - ``unsure``: a post whose answer was lost after it was sent (maybe_applied), or whose
      check could not be made; the next try first looks for the line on that record's timeline
      (``check``: [type, id] pairs), and posts it only when it is not there. ``look_first``
      looks on every record (a back-fill: an earlier post may have landed unrecorded).

    A record found by phone that refuses the comment (deleted or merged since its lookup was
    cached) or gives no comment id has the number looked up again, once, and the message goes to
    whatever records it holds now. No Mirror row is ever written without a comment id.

    Raises client.BitrixTransient when the lookup itself did.
    """
    conversation = message.conversation
    records = _mirror_records(conversation, strict=True, at=message.created_at)
    if not records:
        return records, [], []

    # Per record, not per message. The same number can be on a lead and on an
    # Owner Data item, and one of them having the message already is no reason
    # to skip the other.
    done = set(
        Mirror.objects.filter(message_id=message.pk).values_list("entity_type", "entity_id")
    )
    check = {(str(kind), int(pk)) for kind, pk in (check or ())}

    failed, unsure, tried = [], [], set()
    looked_again = False
    queue = list(records)
    while queue:
        record = queue.pop(0)
        key = (record["type"], record["id"])
        if key in done or key in tried:
            continue
        tried.add(key)
        text = _line_with_role(message, record.get("role")) if record.get("type") == "deal" else _line(message)

        found = None
        if look_first or key in check:
            try:
                found = client.find_comment(record["type"], record["id"], text, skip=_known_comments(record))
            except client.BitrixTransient as exc:
                unsure.append((record, exc))
                continue
            except client.BitrixError as exc:
                # Cannot tell whether the earlier post landed. Not posted again: a read timeout
                # usually means it did, and two of the same line is the mistake this avoids.
                logger.warning(
                    "Could not check whether message %s reached %s; not posted again: %s",
                    message.pk,
                    _where([record]),
                    exc,
                )
                continue

        if found is None:
            try:
                found = client.comment_id(client.add_comment(record["type"], record["id"], text))
                refusal = None if found is not None else "Bitrix gave no comment id"
            except client.BitrixTransient as exc:
                (unsure if exc.maybe_applied else failed).append((record, exc))
                continue
            except client.BitrixError as exc:
                # The portal said no (a deleted record, a type it will not comment on): asking
                # again changes nothing.
                refusal = exc
            if refusal is not None:
                logger.warning("Could not mirror message %s to %s: %s", message.pk, _where([record]), refusal)
                if not looked_again and _found_by_phone(record, _own_record(conversation, at=message.created_at)):
                    # Maybe a cached record that is gone (merged, deleted): ask Bitrix afresh, once.
                    looked_again = True
                    client.forget_records(conversation.contact.wa_id)
                    try:
                        queue.extend(_mirror_records(conversation, strict=True, at=message.created_at))
                    except client.BitrixTransient as exc:
                        failed.append((record, exc))
                continue

        # Recorded after the fact. The other order would mark a message as sent
        # across and then fail to send it, which is the one mistake this table
        # cannot recover from.
        Mirror.objects.get_or_create(
            message_id=message.pk,
            entity_type=record["type"],
            entity_id=record["id"],
            defaults={"comment_id": found},
        )
    return records, failed, unsure


def _mirror_again(task, message_id, where, exc, later, busy=None):
    """Another try of this mirror later, or, after the last one, one warning.

    ``busy``: why this turn could not run at all (another run of the message, every background
    slot taken); it comes back soon without using up a try, MAX_DEFERRALS times at most. The
    warning names the message and the records, never what the message says.
    """
    deferred = int(later.get("deferred") or 0)
    if busy is not None and deferred < MAX_DEFERRALS:
        countdown = random.randint(*DEFER_SECONDS)
        logger.info("Mirroring message %s again in %s s: %s", message_id, countdown, busy)
        raise task.retry(countdown=countdown, kwargs={**later, "deferred": deferred + 1}, exc=exc)
    failures = max(0, task.request.retries - deferred)
    reason = exc if exc is not None else busy
    if failures >= len(MIRROR_RETRY_SECONDS):
        logger.warning(
            "Gave up mirroring message %s to %s after %s tries: %s", message_id, where, failures + 1, reason
        )
        return
    countdown = _countdown(MIRROR_RETRY_SECONDS, failures)
    logger.info(
        "Mirroring message %s to %s again in %s s (try %s of %s): %s",
        message_id,
        where,
        countdown,
        failures + 2,
        len(MIRROR_RETRY_SECONDS) + 1,
        reason,
    )
    raise task.retry(countdown=countdown, kwargs=later, exc=exc)


def _maybe_refresh_summary(message):
    """Every Nth message, rewrite what the manager reads.

    N counts the message's own place in its chat, not the chat's size when this runs: a try
    that runs late, after more messages came, decides exactly as the first one would have, and
    never takes the turn of the message that is the Nth.
    """
    every = settings.SUMMARY_EVERY_N_MESSAGES
    if every <= 0:
        return
    place = Message.objects.filter(conversation_id=message.conversation_id, pk__lte=message.pk).count()
    if place % every:
        return
    try:
        refresh_summary.delay(message.conversation_id)
    except Exception as exc:  # noqa: BLE001 - broker down, mostly; the lines are posted
        logger.warning("Could not queue the summary of conversation %s: %s", message.conversation_id, exc)


@shared_task(bind=True, ignore_result=True, max_retries=len(MIRROR_RETRY_SECONDS) + MAX_DEFERRALS)
def mirror_message(self, message_id, summary_check=True, check=None, look_first=False, deferred=0):
    """Copies one message into the timeline of every CRM record it belongs on.

    A passing failure of the lookup or of a post is tried again later
    (MIRROR_RETRY_SECONDS); a new try posts only on the records that do not have
    the message yet, and first looks on those whose last post may have landed
    (``check``). ``summary_check`` is cleared on the tries that follow a lookup
    that answered, so the every-Nth-message summary is considered once.
    ``look_first``: the back-fill's tasks look on every record before posting.
    ``deferred``: busy turns so far (they use up no try).

    A campaign's own template is never mirrored: the campaign posts its own copy.
    """
    if not client.configured():
        return

    message = Message.objects.select_related(
        "conversation__contact", "sent_by"
    ).filter(pk=message_id).first()
    if not message:
        return
    if _campaign_send(message):
        return

    later = {"summary_check": summary_check, "check": check, "look_first": look_first, "deferred": deferred}
    busy = lookup_error = outcome = None
    # One run of a message at a time. A live retry and a back-fill copy of the same
    # message can meet, and both would read "not posted yet" before either posted.
    with redis_state.held(f"crmlink:mirror:{message.pk}") as mine:
        if mine is False:
            busy = "another run of it is posting now"
        else:
            with redis_state.held_one_of(BACKGROUND_SLOTS, redis_state.background_parallel()) as slot:
                if slot is False:
                    busy = "every background slot is taken"
                else:
                    with client.background():
                        try:
                            outcome = _post(message, check=check, look_first=look_first)
                        except client.BitrixTransient as exc:
                            lookup_error = exc

    if busy is not None:
        # The other run finishes it, or comes back on its own retry; this one looks
        # again later and finds whatever that run left to do.
        _mirror_again(self, message.pk, "its records", None, later, busy=busy)
        return
    if lookup_error is not None:
        _mirror_again(self, message.pk, "its records", lookup_error, later)
        return
    records, failed, unsure = outcome
    if not records:
        # Nothing in the CRM carries this number. Deliberately silent: the
        # customer simply is not entered anywhere, which is not an error.
        return

    if summary_check:
        _maybe_refresh_summary(message)

    if failed or unsure:
        later.update(
            summary_check=False,
            look_first=False,
            check=[[record["type"], record["id"]] for record, _ in unsure] or None,
        )
        pending = failed + unsure
        _mirror_again(self, message.pk, _where([record for record, _ in pending]), pending[0][1], later)


# The summary
# ---------------------------------------------------------------------------

STEPS = ("fields", "comment")


def _summary_steps(only):
    """{(type, id): steps still to do} from a retry's ``only``, or None for every record and step.

    An entry is [type, id] (every step that applies to it) or [type, id, step...].
    """
    if only is None:
        return None
    wanted = {}
    for entry in only:
        steps = {str(step) for step in entry[2:] if str(step) in STEPS} or set(STEPS)
        wanted[(str(entry[0]), int(entry[1]))] = steps
    return wanted


def _write_summary(conversation, only):
    """The summary of this chat on each of its records (or those ``only`` names, and only the
    steps it names). Returns ([entries still to do], the first passing failure), the entries in
    ``only``'s shape. Raises client.BitrixTransient when the lookup did.
    """
    records = _mirror_records(conversation, strict=True)
    steps = _summary_steps(only)
    if steps is not None:
        records = [record for record in records if (record["type"], record["id"]) in steps]
    if not records:
        return [], None

    # The tail of the conversation. What somebody wants now matters more than
    # what they asked three weeks ago, and the whole thread would cost more per
    # call for an answer that is mostly about the end of it anyway.
    messages = list(
        Message.objects.filter(conversation_id=conversation.pk)
        .order_by("-created_at", "-id")[: settings.SUMMARY_CONTEXT_MESSAGES]
    )
    messages.reverse()

    try:
        result = ai.summarise(messages)
    except ai.SummaryError as exc:
        logger.warning("Summary for conversation %s failed: %s", conversation.pk, exc)
        return [], None

    stamp = timezone.localtime().strftime("%d %b %Y %H:%M")
    pinned = (
        f"{result['summary']}\n\n"
        f"Customer {result['client_score']}/100 — {result['client_reason']}\n"
        f"Our handling {result['agent_score']}/100 — {result['agent_reason']}\n"
        f"(updated {stamp}, after {len(messages)} messages)"
    )

    # A Lead AI chat (owner's choice, 2026-10-09): the summary is a comment
    # only. Every lead update re-runs Bitrix's Lead Automation, which plans a
    # new "Viewing/Meeting" to-do each time a lead sits in Meeting/Viewing
    # Scheduled, and the assistant's own messages make these chats busier. So
    # too once it is moved to the inbox: it still mirrors to its campaign lead,
    # which may be the one the assistant booked.
    comment_only = _was_lead_ai(conversation)

    pending, first = [], None
    for record in records:
        where = _where([record])
        # The pinned fields exist on leads and contacts, where `setup_crm_fields`
        # created them. A smart-process item has no such fields, so it gets the
        # summary as a comment and nothing is written into a field that is not
        # there.
        applies = {"comment"} | ({"fields"} if record["type"] in ("lead", "contact") and not comment_only else set())
        wanted = applies & (steps[(record["type"], record["id"])] if steps is not None else set(STEPS))
        left = []
        if "fields" in wanted:
            try:
                client.update_fields(
                    record["type"],
                    record["id"],
                    {
                        FIELD_SUMMARY: pinned,
                        FIELD_CLIENT: result["client_score"],
                        FIELD_AGENT: result["agent_score"],
                    },
                )
            except client.BitrixTransient as exc:
                if exc.maybe_applied:
                    # Written again, a lead would run its automation (BP 235) once more.
                    logger.info("The summary fields on %s may have been written (%s); not written again", where, exc)
                else:
                    left.append("fields")
                    first = first or exc
            except client.BitrixError as exc:
                logger.warning("Could not write the summary fields on %s: %s", where, exc)

        # And a timeline entry everywhere, so the summary's own history is
        # readable — how a customer's score moved is worth more than where it
        # currently sits.
        if "comment" in wanted:
            try:
                client.add_comment(record["type"], record["id"], f"WhatsApp summary · updated\n{pinned}")
            except client.BitrixTransient as exc:
                if exc.maybe_applied:
                    # The next try's summary reads differently, so it cannot be looked for.
                    logger.info("The summary comment on %s may have been posted (%s); not posted again", where, exc)
                else:
                    left.append("comment")
                    first = first or exc
            except client.BitrixError as exc:
                logger.warning("Could not post the summary comment on %s: %s", where, exc)

        if left:
            entry = [record["type"], record["id"]]
            pending.append(entry if set(left) == applies else entry + left)
    return pending, first


def _summary_again(task, conversation_id, exc, later, busy=None):
    deferred = int(later.get("deferred") or 0)
    if busy is not None and deferred < MAX_DEFERRALS:
        countdown = random.randint(*DEFER_SECONDS)
        logger.info("Summary of conversation %s again in %s s: %s", conversation_id, countdown, busy)
        raise task.retry(countdown=countdown, kwargs={**later, "deferred": deferred + 1}, exc=exc)
    only = later.get("only")
    where = "its records" if only is None else ", ".join(f"{entry[0]} {entry[1]}" for entry in only)
    failures = max(0, task.request.retries - deferred)
    reason = exc if exc is not None else busy
    if failures >= len(SUMMARY_RETRY_SECONDS):
        logger.warning(
            "Gave up on the summary of conversation %s for %s after %s tries: %s",
            conversation_id,
            where,
            failures + 1,
            reason,
        )
        return
    countdown = _countdown(SUMMARY_RETRY_SECONDS, failures)
    logger.info("Summary of conversation %s for %s again in %s s: %s", conversation_id, where, countdown, reason)
    raise task.retry(countdown=countdown, kwargs=later, exc=exc)


@shared_task(bind=True, ignore_result=True, max_retries=len(SUMMARY_RETRY_SECONDS) + MAX_DEFERRALS)
def refresh_summary(self, conversation_id, only=None, deferred=0):
    """Rewrites the pinned summary and the two scores.

    A passing Bitrix failure is tried again later (SUMMARY_RETRY_SECONDS). The
    try after a failed write does only what did not take (``only``: [type, id]
    for every step of a record, [type, id, "fields" | "comment"] for one), so
    nobody gets the same summary comment twice and no lead's fields (and its
    automation) are written twice. A write whose answer was lost after it was
    sent counts as done.
    """
    if not (client.configured() and ai.configured()):
        return

    conversation = Conversation.objects.select_related("contact").filter(pk=conversation_id).first()
    if not conversation:
        return

    later = {"only": only, "deferred": deferred}
    busy = lookup_error = None
    pending, first = [], None
    with redis_state.held_one_of(BACKGROUND_SLOTS, redis_state.background_parallel()) as slot:
        if slot is False:
            busy = "every background slot is taken"
        else:
            with client.background():
                try:
                    pending, first = _write_summary(conversation, only)
                except client.BitrixTransient as exc:
                    lookup_error = exc

    if busy is not None:
        _summary_again(self, conversation_id, None, later, busy=busy)
        return
    if lookup_error is not None:
        _summary_again(self, conversation_id, lookup_error, later)
        return
    if pending:
        _summary_again(self, conversation_id, first, {**later, "only": pending})
