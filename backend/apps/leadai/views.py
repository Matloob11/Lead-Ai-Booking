"""Lead AI screen API: its own chat list, the assistant's state per chat, the
appointment, the assistant's settings, and the way back to the main inbox.

Messages, sending, media and read receipts reuse the inbox endpoints
(/api/inbox/conversations/<id>/...): those check visibility by thread, not by
list, so a Lead AI chat opens and answers there like any other. A row carries
the chat's labels (the inbox's own field) and its playbook, and the list
filters by label (?label=Broker: the chats the assistant handed over as a
broker's).

Permissions: anyone who can open a chat may pause, resume or cancel its
meeting, and take its call (I'll call). Settings: every agent may read them
(the test numbers, which are
private phone numbers, only as a count); anyone with admin rights may
switch the assistant OFF (an emergency stop); switching it ON and every
other change needs a panel admin (is_wa_admin) or a superuser. The shops
playbook's facts, brand and viewing agent are settings too (shops.validate
checks them); a shops chat's row says when it is due a follow-up, and when its
automatic follow-up waits because Template B is not approved on its number
(followups.panel_note: a note on the row, never an alert).

The agent desk (batch 2e, desk.py): a shops chat's row carries its track
(lead_ai_ai.track, unit, track_label), the list filters by it (?track=), and
lists the chats that need a person (?needs=1) or have a visit or call today
(?today=1), each row with why (lead_ai_desk). The first page carries the
counts of those two (desk_counts; GET desk/ alone). An agent with Lead AI
access opens every Lead AI chat (lane.desk_q, Q37).
"""

import datetime as dt
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.inbox.models import Conversation
from apps.inbox.serializers import serialize_conversation
from apps.inbox.visibility import visible_conversation_q
from apps.leadbot.models import LeadAutomation

from . import desk, ic_templates
from .assistant import hours, memory, openai_client, residential, shops
from .lane import GENERAL, IC_SHOPS, move_to_inbox, only_lead_ai, playbooks
from .models import LeadAiAppointment, LeadAiCampaign, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn

OPEN_STATUSES = LeadAiAppointment.OPEN
# Google Maps links only: a share link, or Google's own host with a /maps path.
MAPS_ANY_PATH = ("maps.app.goo.gl", "maps.google.com")
MAPS_PATH_ONLY = ("goo.gl", "google.com", "www.google.com", "google.ae", "www.google.ae")
MAPS_URL_MAX = 500
# A turn this recent and still running: the assistant is writing in that chat.
THINKING_FOR = dt.timedelta(minutes=3)
# Bitrix users the settings may name for the alerts (alert_bitrix_user_ids).
ALERT_USERS_MAX = 10
LABEL_MAX = 64


def _visible(user):
    return (
        Conversation.objects.filter(visible_conversation_q(user))
        .select_related(
            "contact",
            "number",
            "assigned_agent",
            "linked_conversation__number",
            "lead_ai_chat__campaign",
            "lead_ai_chat__added_by",
            "lead_ai_state__paused_by",
        )
        .prefetch_related(
            "labels",
            Prefetch(
                "lead_automations",
                queryset=LeadAutomation.objects.order_by("-id"),
                to_attr="leadbot_rows",
            ),
            Prefetch(
                "lead_ai_appointments",
                queryset=LeadAiAppointment.objects.filter(status__in=OPEN_STATUSES).select_related("taken_by").order_by("-id"),
                to_attr="lead_ai_open_appointments",
            ),
        )
        .distinct()
    )


def _iso(value):
    return value.isoformat() if value else None


def _day_month(value) -> str:
    """'12 Nov' in Dubai time, '' for none."""
    if not value:
        return ""
    local = value.astimezone(hours.DUBAI)
    return f"{local.day} {local:%b}"


def serialize_appointment(appointment) -> dict | None:
    if appointment is None:
        return None
    return {
        "id": appointment.pk,
        "status": appointment.status,
        "place": appointment.place,
        "place_label": appointment.get_place_display(),
        "starts_at": _iso(appointment.starts_at),
        "when": hours.describe(appointment.starts_at) if appointment.starts_at else "",
        "note": appointment.note,
        "customer_state": appointment.customer_state,
        "customer_state_label": appointment.get_customer_state_display() if appointment.customer_state else "",
        "eta_at": _iso(appointment.eta_at),
        "reminder_due_at": _iso(appointment.reminder_due_at),
        "reminder_sent_at": _iso(appointment.reminder_sent_at),
        "reminder_error": appointment.reminder_error,
        "crm_synced_at": _iso(appointment.crm_synced_at),
        "crm_error": appointment.crm_error,
        "crm_stage_moved": appointment.crm_stage_moved_at is not None,
        # A call (the agent desk): "Sales call" or "Call", who took it with I'll call, and whether it can be taken.
        "call_label": desk.call_label(appointment),
        "taken_by": desk.agent_name(appointment.taken_by) if appointment.taken_by_id else "",
        "taken_by_id": appointment.taken_by_id,
        "taken_at": _iso(appointment.taken_at),
        "takeable": desk.takeable(appointment),
    }


def _open_appointment(conversation):
    rows = getattr(conversation, "lead_ai_open_appointments", None)
    if rows is not None:
        return rows[0] if rows else None
    return LeadAiAppointment.objects.filter(conversation=conversation, status__in=OPEN_STATUSES).order_by("-id").first()


def _state(conversation):
    try:
        return conversation.lead_ai_state
    except LeadAiChatState.DoesNotExist:
        return None


def _thinking(conversation_ids) -> set[int]:
    """The chats among these where a turn is running now (one query for a whole page)."""
    ids = list(conversation_ids)
    if not ids:
        return set()
    return set(
        LeadAiTurn.objects.filter(
            conversation_id__in=ids,
            status=LeadAiTurn.Status.RUNNING,
            created_at__gte=timezone.now() - THINKING_FOR,
        ).values_list("conversation_id", flat=True)
    )


def _silent_note(settings_row) -> str:
    """Why the assistant answers no chat right now although it is on ('' when it does).

    The same gates run_turn checks first: the key, the OpenAI breaker, the
    daily ceiling on model calls.
    """
    if not openai_client.configured():
        return "No Lead AI key"
    now = timezone.now()
    if settings_row.paused_until and settings_row.paused_until > now:
        return f"Paused after OpenAI errors until {hours.time_label(settings_row.paused_until)}"
    calls = LeadAiTurn.objects.filter(created_at__gte=now - dt.timedelta(hours=24)).aggregate(n=Sum("calls"))["n"] or 0
    if calls >= settings_row.daily_call_limit:
        return "Daily limit reached"
    return ""


def _handover_label(state) -> str:
    if state is None or not state.handed_over_at:
        return ""
    from .assistant import engine

    return engine.HANDOVER_TEXT.get(state.handover_reason, "needs a person")


def serialize_ai(conversation, settings_row=None, *, thinking=None, note=None) -> dict:
    """The assistant in this chat: on, paused, stopped, handed over, and what it knows.

    ``thinking`` and ``note`` may be worked out once for a whole list
    (``_thinking``, ``_silent_note``) instead of once per chat.
    """
    settings_row = settings_row or LeadAiSettings.load()
    state = _state(conversation)
    allowed = settings_row.answers(conversation.contact.wa_id)
    answers = allowed and openai_client.configured()
    mode = "on" if answers else "off"
    if state is not None:
        if state.stopped_at:
            mode = "stopped"
        elif state.paused_at:
            mode = "paused"
        elif state.handed_over_at and answers:
            mode = "handed_over"
    if conversation.linked_conversation_id and mode == "on":
        mode = "transferred"
    if thinking is None:
        thinking = conversation.pk in _thinking([conversation.pk])
    # Nobody stopped it in this chat, yet it is silent everywhere ("off" here
    # only when the key is missing).
    if allowed and mode in ("on", "handed_over", "off"):
        note = _silent_note(settings_row) if note is None else note
    else:
        note = ""
    paused_by = state.paused_by if state is not None else None
    followup = state.followup_due_at if state is not None else None
    return {
        # A shops chat whose customer said yes to "Should I check back with you in a month?".
        "followup_due_at": _iso(followup),
        "followup_label": _day_month(followup),
        "mode": mode,
        "test_number": bool(not settings_row.assistant_enabled and answers),
        "thinking": bool(thinking),
        "note": note,
        "stop_reason": state.get_stop_reason_display() if state is not None and state.stopped_at else "",
        "stopped_at": _iso(state.stopped_at) if state else None,
        "paused_at": _iso(state.paused_at) if state else None,
        "paused_by": (paused_by.display_name or paused_by.get_username()) if paused_by else "",
        "handed_over_at": _iso(state.handed_over_at) if state else None,
        "handover_reason": state.handover_reason if state else "",
        "handover_label": _handover_label(state),
        # The co-pilot's draft reply for the agent (assistant/copilot.py), or null.
        "draft": (state.draft or None) if state else None,
        # The customer's earlier chats on our other numbers (assistant/memory.py), one line each, for the agent: the chat
        # detail fills it (chat_detail); the list stays one query per page.
        "memory": [],
        "language": state.language if state else "",
        "facts": {k: v for k, v in ((state.facts if state else {}) or {}).items() if v not in (None, "")},
    }


def _lead_ai_part(chat: LeadAiChat, playbook: str = GENERAL) -> dict:
    added_by = chat.added_by
    return {
        "campaign_id": chat.campaign_id,
        "campaign_name": chat.campaign.name if chat.campaign_id and chat.campaign else "",
        "crm_entity": chat.crm_entity,
        "crm_id": chat.crm_id,
        "added_by": (added_by.display_name or added_by.get_username()) if added_by else "",
        "added_at": chat.created_at.isoformat() if chat.created_at else "",
        "confirmed": chat.confirmed,
        # The script the assistant follows here (lane.playbook_for).
        "playbook": playbook,
        "playbook_label": LeadAiCampaign.Playbook(playbook).label,
    }


def serialize_lead_ai_conversation(
    conversation, settings_row=None, *, thinking=None, note=None, playbook=None, approved=None, kinds=None
) -> dict:
    """The inbox's own shape (with its lead_ai flag and labels), plus where the chat
    came from and its playbook, the assistant's state and the open appointment.

    ``playbook`` may be worked out once for a whole list (lane.playbooks), and so may
    ``approved``, the WABAs Template B can go from (followups.approved_wabas): a shops
    chat's ``followup_note`` says when its automatic follow-up waits for Meta. So may
    ``kinds``, the campaign templates' kinds (desk.template_kinds), which a shops chat
    with no stored track reads its track from (lead_ai_ai.track, unit, track_label).
    """
    row = serialize_conversation(conversation)
    chat = getattr(conversation, "lead_ai_chat", None)
    if playbook is None:
        playbook = playbooks([conversation.pk]).get(conversation.pk, GENERAL)
    row["lead_ai_info"] = _lead_ai_part(chat, playbook) if chat is not None else None
    row["lead_ai_ai"] = serialize_ai(conversation, settings_row, thinking=thinking, note=note)
    state = _state(conversation)
    if kinds is None and desk.needs_template_kind(playbook, state):
        kinds = desk.template_kinds([conversation.pk])
    row["lead_ai_ai"].update(desk.track_part(playbook, state, (kinds or {}).get(conversation.pk, ic_templates.SHOP)))
    followup_note = ""
    if playbook == IC_SHOPS:
        from . import followups

        followup_note = followups.panel_note(
            conversation, _state(conversation), followups.approved_wabas() if approved is None else approved
        )
    row["lead_ai_ai"]["followup_note"] = followup_note
    row["lead_ai_appointment"] = serialize_appointment(_open_appointment(conversation))
    return row


@api_view(["GET"])
def chat_list(request):
    """The Lead AI screen's own list, same order and search as the main inbox.

    The agent desk (desk.py): ``?track=shop|rent|sale|other|unknown`` keeps one track's chats;
    ``?needs=1`` lists the chats that need a person, the longest wait first, and ``?today=1``
    the visits and calls that start today, by time, each row saying why (lead_ai_desk). The
    first page carries the counts of those two lists (desk_counts), over every chat the agent
    may open here, whatever the search or filters.
    """
    base = only_lead_ai(_visible(request.user))
    queryset = base

    number_id = request.GET.get("number", "").strip()
    if number_id:
        if not re.fullmatch(r"[0-9]{1,18}", number_id):
            return Response({"detail": "number must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(number_id=number_id)

    search = request.GET.get("q", "").strip()
    if search:
        digits = "".join(ch for ch in search if ch.isdigit())
        q_obj = (
            Q(contact__wa_id__icontains=search)
            | Q(contact__profile_name__icontains=search)
            | Q(contact__display_name__icontains=search)
        )
        if digits:
            q_obj |= Q(contact__wa_id__icontains=digits)
            if len(digits) >= 9:
                q_obj |= Q(contact__wa_id__endswith=digits[-9:])
        queryset = queryset.filter(q_obj)

    if request.GET.get("unread") == "1":
        queryset = queryset.filter(unread_count__gt=0)

    # ?label=Broker: only the chats carrying that label (the panel's "Brokers"), in any case.
    label = request.GET.get("label", "").strip()
    if label:
        if len(label) > LABEL_MAX:
            return Response({"detail": f"label is at most {LABEL_MAX} characters."}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(labels__name__iexact=label)

    # ?track=: the desk's Shops, Rent, Sale and Other filters (desk.chat_track).
    track = request.GET.get("track", "").strip().lower()
    if track:
        if track not in desk.TRACK_FILTERS:
            return Response(
                {"detail": "track is one of shop, rent, sale, other or unknown."}, status=status.HTTP_400_BAD_REQUEST
            )
        queryset = queryset.filter(pk__in=desk.track_ids(queryset, track))
    needs = request.GET.get("needs") == "1"
    today = request.GET.get("today") == "1"
    if needs and today:
        return Response({"detail": "Ask for needs or today, not both."}, status=status.HTTP_400_BAD_REQUEST)

    queryset = queryset.order_by("-is_pinned", "-last_message_at", "-created_at")
    try:
        limit = min(max(int(request.GET.get("limit", 50)), 1), 200)
        offset = max(int(request.GET.get("offset", 0)), 0)
    except ValueError:
        return Response({"detail": "limit and offset must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    desk_rows = None
    if needs or today:
        # The desk's own order: the longest wait first, or the start time; a page of it.
        rows = desk.needs_rows(queryset, now) if needs else desk.today_rows(queryset, now)
        total = len(rows)
        chosen = rows[offset : offset + limit]
        found = {c.pk: c for c in queryset.filter(pk__in=[row.conversation_id for row in chosen])}
        page = [found[row.conversation_id] for row in chosen if row.conversation_id in found]
        desk_rows = {row.conversation_id: row.as_dict() for row in chosen}
    else:
        total = queryset.count()
        page = list(queryset[offset : offset + limit])
    unread = queryset.filter(unread_count__gt=0).count() if offset == 0 else None
    settings_row = LeadAiSettings.load()
    thinking = _thinking(c.pk for c in page)
    note = _silent_note(settings_row) if page else ""
    scripts = playbooks(c.pk for c in page)
    approved = None
    if IC_SHOPS in scripts.values():
        from . import followups

        approved = followups.approved_wabas()
    kinds = desk.template_kinds(c.pk for c in page if desk.needs_template_kind(scripts.get(c.pk, GENERAL), _state(c)))
    results = []
    for c in page:
        row = serialize_lead_ai_conversation(
            c, settings_row, thinking=c.pk in thinking, note=note, playbook=scripts.get(c.pk, GENERAL), approved=approved,
            kinds=kinds,
        )
        if desk_rows is not None:
            row["lead_ai_desk"] = desk_rows.get(c.pk)
        results.append(row)
    body = {"count": total, "unread_chats": unread, "results": results}
    if offset == 0:
        body["desk_counts"] = desk.counts(base, now)
    return Response(body)


@api_view(["GET"])
def desk_counts(request):
    """The numbers on the desk's Needs a person and Today buttons, over every Lead AI chat the agent may open."""
    return Response(desk.counts(only_lead_ai(_visible(request.user))))


@api_view(["GET"])
def chat_detail(request, pk):
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    row = serialize_lead_ai_conversation(conversation)
    # What the assistant remembers of this customer from chats on our other numbers (assistant/memory.py).
    row["lead_ai_ai"]["memory"] = [
        memory.describe(entry) for entry in memory.recall(conversation.contact.wa_id, exclude_conversation=conversation.pk)
    ]
    return Response(row)


@api_view(["POST"])
def chat_move_to_inbox(request, pk):
    """Hand a chat back to the main inbox. Only an agent who can open it may move it."""
    conversation = get_object_or_404(_visible(request.user), pk=pk)
    if not move_to_inbox(conversation, request.user):
        return Response({"detail": "This chat is not in the Lead AI screen."}, status=status.HTTP_409_CONFLICT)
    return Response({"id": conversation.pk, "moved": True})


def _changed(conversation_id) -> None:
    from .assistant import live

    transaction.on_commit(lambda pk=conversation_id: live.appointment_changed(pk))


@api_view(["POST"])
def chat_pause_ai(request, pk):
    """The agent's "Pause AI" for one chat (owner's choice). Reminders still go out."""
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    state = LeadAiChatState.for_conversation(conversation)
    if state.paused_at is None:
        LeadAiChatState.objects.filter(pk=state.pk).update(paused_at=timezone.now(), paused_by=request.user)
    _changed(conversation.pk)
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    return Response(serialize_lead_ai_conversation(conversation))


@api_view(["POST"])
def chat_draft_ask(request, pk):
    """Ask AI (the co-pilot): the agent's question about this chat, or "write me a reply", answered as a draft by a
    task (copilot.ask); the screen hears ai.changed when it lands."""
    from .assistant import copilot
    from .tasks import copilot_ask

    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    question = " ".join(str(request.data.get("question") or "").split())[: copilot.ASK_MAX]
    if not question:
        return Response({"detail": "Ask something first."}, status=status.HTTP_400_BAD_REQUEST)
    transaction.on_commit(lambda pk=conversation.pk, q=question, who=request.user.pk: copilot_ask.delay(pk, q, who))
    return Response({"ok": True})


@api_view(["POST"])
def chat_draft_used(request, pk):
    """The agent sent the draft (as it was, or edited: ``text`` is what went out): its fate recorded, the draft cleared."""
    from .assistant import copilot
    from .models import LeadAiDraftOutcome

    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    state = LeadAiChatState.for_conversation(conversation)
    sent_text = " ".join(str(request.data.get("text") or "").split())
    draft_text = " ".join(str((state.draft or {}).get("text") or "").split())
    kind = LeadAiDraftOutcome.Kind.SENT if sent_text == draft_text else LeadAiDraftOutcome.Kind.EDITED
    copilot.close(conversation, state, kind, agent=request.user, sent_text=sent_text)
    _changed(conversation.pk)
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    return Response(serialize_lead_ai_conversation(conversation))


@api_view(["POST"])
def chat_draft_dismiss(request, pk):
    """The agent dropped the draft: recorded (the knowledge base learns from a no too), cleared."""
    from .assistant import copilot
    from .models import LeadAiDraftOutcome

    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    state = LeadAiChatState.for_conversation(conversation)
    copilot.close(conversation, state, LeadAiDraftOutcome.Kind.DISMISSED, agent=request.user)
    _changed(conversation.pk)
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    return Response(serialize_lead_ai_conversation(conversation))


@api_view(["POST"])
def chat_resume_ai(request, pk):
    """Let the assistant answer again: after a pause, an opt-out, an automatic-reply stop or a handover.
    A stop the assistant read as spam or a wrong number also takes the phone off the opt-out
    registry again (optout.release_for_resume): that was code's reading, not the customer's STOP."""
    from . import optout

    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    state = LeadAiChatState.for_conversation(conversation)
    if state.stopped_at is not None:
        optout.release_for_resume(conversation, state.stop_reason)
    LeadAiChatState.objects.filter(pk=state.pk).update(
        paused_at=None,
        paused_by=None,
        stopped_at=None,
        stop_reason="",
        handed_over_at=None,
        handover_reason="",
        holding_line_at=None,
        draft=None,  # the co-pilot's draft goes with the handover (assistant/copilot.py)
    )
    _changed(conversation.pk)
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    return Response(serialize_lead_ai_conversation(conversation))


@api_view(["POST"])
def appointment_cancel(request, pk):
    """An agent cancels the chat's open meeting: no reminder, a CRM comment, the to-do closed."""
    conversation = get_object_or_404(_visible(request.user), pk=pk)
    with transaction.atomic():
        appointment = (
            LeadAiAppointment.objects.select_for_update()
            .filter(conversation=conversation, status__in=OPEN_STATUSES)
            .order_by("-id")
            .first()
        )
        if appointment is None:
            return Response({"detail": "This chat has no open meeting."}, status=status.HTTP_409_CONFLICT)
        appointment.status = LeadAiAppointment.Status.CANCELLED
        appointment.reminder_due_at = None
        appointment.cancelled_by = request.user
        appointment.log("cancelled", by=request.user.display_name or request.user.get_username())
        appointment.save(update_fields=["status", "reminder_due_at", "cancelled_by", "history", "updated_at"])
        from .tasks import sync_appointment_crm

        revision = len(appointment.history or [])
        transaction.on_commit(lambda apk=appointment.pk, rev=revision: sync_appointment_crm.delay(apk, "cancelled", False, rev))
        _changed(conversation.pk)
    conversation = get_object_or_404(_visible(request.user), pk=pk)
    return Response(serialize_lead_ai_conversation(conversation))


@api_view(["POST"])
def appointment_take(request, pk):
    """I'll call (spec §3.3 step 5): the agent takes the chat's open call, first come first served
    (desk.take_call, under a row lock). Anyone who can open the chat may, as for cancelling its
    meeting: never only the settings admins. A call someone else took answers 409 with their name
    (taken_by); the customer is never told who."""
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    result = desk.take_call(conversation, request.user)
    if result.error == desk.NO_CALL:
        return Response({"detail": "This chat has no open call."}, status=status.HTTP_409_CONFLICT)
    if result.error == desk.TAKEN:
        return Response(
            {"detail": f"{result.taken_by} has already taken this call.", "taken_by": result.taken_by},
            status=status.HTTP_409_CONFLICT,
        )
    _changed(conversation.pk)
    conversation = get_object_or_404(only_lead_ai(_visible(request.user)), pk=pk)
    return Response(serialize_lead_ai_conversation(conversation))


# Settings ---------------------------------------------------------------------------------


def _can_edit(user) -> bool:
    return bool(getattr(user, "is_wa_admin", False) or getattr(user, "is_superuser", False))


def _can_disable(user) -> bool:
    return bool(getattr(user, "has_admin_rights", False) or _can_edit(user))


def _missing_templates() -> list[str]:
    """Active numbers, with an agent or not, whose WABA has no approved reminder template yet.

    Every active number, as the template is submitted (submit_leadai_reminder_template):
    the Lead AI campaigns go out from numbers nobody is assigned to.
    """
    from apps.catalog.models import WabaNumber, WaTemplate

    from .assistant.reminders import TEMPLATE_NAME

    approved = set(
        WaTemplate.objects.filter(name=TEMPLATE_NAME, status=WaTemplate.Status.APPROVED, category__iexact="UTILITY").values_list(
            "waba_business_id", flat=True
        )
    )
    missing = set()
    for phone, waba in WabaNumber.objects.filter(is_active=True).values_list("phone_number", "waba_business_id"):
        if waba and waba not in approved:
            missing.add(phone)
    return sorted(missing)


def _alert_recipients(row: LeadAiSettings) -> list[dict]:
    """The listed Bitrix users with the agent each one is, so a typo shows (no agent: no alert)."""
    from django.contrib.auth import get_user_model

    ids = row.alert_user_ids()
    if not ids:
        return []
    agents = {agent.bitrix_user_id: agent for agent in get_user_model().objects.filter(is_active=True, bitrix_user_id__in=ids)}
    return [
        {
            "bitrix_user_id": value,
            "name": (agents[value].display_name or agents[value].get_username()) if value in agents else "",
        }
        for value in ids
    ]


def _desk_agents() -> list[dict]:
    """The agents with Lead AI access (Agents & access), who follow every Lead AI chat and get its alerts (Q37)."""
    from .assistant import alerts

    return [
        {"name": desk.agent_name(agent), "bitrix_user_id": agent.bitrix_user_id or ""} for agent in alerts.desk_agents()
    ]


def serialize_settings(row: LeadAiSettings, user) -> dict:
    data = {
        "assistant_enabled": row.assistant_enabled,
        "key_configured": openai_client.configured(),
        "model": openai_client.chat_model(),
        "test_numbers_count": len(row.test_numbers or []),
        "closed_dates": list(row.closed_dates or []),
        "office_address": row.office_address,
        "office_maps_url": row.office_maps_url,
        "office_latitude": str(row.office_latitude) if row.office_latitude is not None else "",
        "office_longitude": str(row.office_longitude) if row.office_longitude is not None else "",
        "hours": hours.HOURS_TEXT,
        "daily_call_limit": row.daily_call_limit,
        # The co-pilot (assistant/copilot.py): an ordinary draft nobody sent or dropped goes out by itself after this many
        # minutes; 0 never.
        "copilot_auto_send_minutes": row.copilot_auto_send_minutes,
        "alert_bitrix_user_ids": row.alert_user_ids(),
        "alert_recipients": _alert_recipients(row),
        # The agent desk (Q37): who follows every Lead AI chat; granted per agent in Agents & access.
        "desk_agents": _desk_agents(),
        # The shops playbook: what it may quote, the brand it speaks for, who a booked client meets.
        "shops_facts": shops.facts_of(row.shops_facts),
        # Batch 2e: what the International City studios and one-bedrooms may quote (rent and sale bands, the charges).
        "residential_facts": residential.facts_of(row.residential_facts),
        "brand_name": shops.brand_of(row),
        "viewing_agent_name": shops.agent_of(row),
        "paused_until": _iso(row.paused_until),
        "last_sweep_at": _iso(row.last_sweep_at),
        "updated_at": _iso(row.updated_at),
        "updated_by": (row.updated_by.display_name or row.updated_by.get_username()) if row.updated_by else "",
        "can_edit": _can_edit(user),
        "can_disable": _can_disable(user),
    }
    if _can_disable(user):
        # Private phone numbers: only for those who may change the settings.
        data["test_numbers"] = list(row.test_numbers or [])
        since = timezone.now() - dt.timedelta(hours=24)
        turns = LeadAiTurn.objects.filter(created_at__gte=since)
        totals = turns.aggregate(prompt=Sum("prompt_tokens"), completion=Sum("completion_tokens"), calls=Sum("calls"))
        data["usage_24h"] = {
            "replies": turns.filter(status=LeadAiTurn.Status.REPLIED).count(),
            "failed": turns.filter(status=LeadAiTurn.Status.FAILED).count(),
            "calls": totals["calls"] or 0,
            "prompt_tokens": totals["prompt"] or 0,
            "completion_tokens": totals["completion"] or 0,
        }
        data["numbers_without_reminder_template"] = _missing_templates()
        data["history"] = list(row.history or [])[-20:]
    return data


def _coordinate(value, low, high):
    text = str(value if value is not None else "").strip()
    if not text:
        return None, ""
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, "must be a number"
    if not number.is_finite():
        # 'NaN' and 'Infinity' parse; comparing a NaN raises.
        return None, "must be a number"
    if not (low <= number <= high):
        return None, "is out of range"
    return number.quantize(Decimal("0.000001")), ""


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")


def _phone_digits(text: str) -> str:
    """The number's digits (Arabic-Indic ones too, as 0-9), a leading 00 (the international prefix) dropped."""
    digits = "".join(str(unicodedata.decimal(ch)) for ch in text if ch.isdecimal())
    return digits[2:] if digits.startswith("00") else digits


def normalize_number(value) -> tuple[str, str]:
    """One phone number as WhatsApp ids are stored (digits, country code first), or ('', why not).

    A number starting with a single 0 is a local one: it would be stored and
    never match a customer, so it is refused. Shared with leadai_switch.
    """
    text = str(value).strip()
    digits = _phone_digits(text)
    if digits.startswith("0"):
        return "", f"'{text}' has no country code: include the country code, e.g. 971501234567."
    if not 8 <= len(digits) <= 15:
        return "", f"'{text}' is not a phone number with country code."
    return digits, ""


def _numbers(value) -> tuple[list[str], str]:
    """Phone numbers from a list or from text separated by commas, semicolons or lines.

    Spaces inside one entry are part of the number ("+971 50 999 0000"); only
    when the whole entry is too long to be one number is it read as several
    numbers separated by spaces.
    """
    raw = value if isinstance(value, list) else re.split(r"[,;\n]+", str(value or ""))
    out = []
    for item in raw:
        text = str(item).strip()
        digits = _phone_digits(text)
        if not digits:
            continue
        parts = [text]
        if not digits.startswith("0") and not 8 <= len(digits) <= 15 and len(text.split()) > 1:
            parts = text.split()
        for part in parts:
            number, error = normalize_number(part)
            if error:
                return [], error
            if number not in out:
                out.append(number)
    return out[:50], ""


def _bitrix_ids(value) -> tuple[list[str], str]:
    """Bitrix user ids (digits only, at most ALERT_USERS_MAX) from a list or from
    text separated by commas, semicolons, spaces or lines, or ([], why not)."""
    raw = value if isinstance(value, list) else re.split(r"[\s,;]+", str(value or ""))
    out = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        if not re.fullmatch(r"[0-9]{1,16}", text):
            return [], f"'{text[:40]}' is not a Bitrix user id: use digits only, e.g. 2311."
        if text not in out:
            out.append(text)
    if len(out) > ALERT_USERS_MAX:
        return [], f"Give at most {ALERT_USERS_MAX} Bitrix user ids."
    return out, ""


def _maps_url_error(url: str) -> str:
    """'' when ``url`` may go to customers as the office's Google Maps link, else why not.

    The host is parsed, not prefix-matched: a '?', '#', backslash or space
    after a foreign host must not pass it off as Google's.
    """
    if len(url) > MAPS_URL_MAX:
        return f"The link is longer than {MAPS_URL_MAX} characters."
    wrong = "Paste a Google Maps link starting with https://maps.app.goo.gl/ or https://www.google.com/maps."
    if any(ch == "\\" or ch.isspace() or unicodedata.category(ch).startswith("C") for ch in url):
        return wrong
    try:
        parts = urlsplit(url)
    except ValueError:
        return wrong
    host = parts.netloc.lower()
    # '@' would be a user name, ':' a port; neither belongs in a Maps link.
    if parts.scheme != "https" or "@" in host or ":" in host:
        return wrong
    if host in MAPS_ANY_PATH:
        return ""
    if host in MAPS_PATH_ONLY and (parts.path == "/maps" or parts.path.startswith("/maps/")):
        return ""
    return wrong


def _dates(value) -> tuple[list[str], str]:
    raw = value if isinstance(value, list) else re.split(r"[\s,;]+", str(value or ""))
    out = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        day = hours.parse_date(text)
        if day is None:
            return [], f"'{text}' is not a date in YYYY-MM-DD form."
        if day.isoformat() not in out:
            out.append(day.isoformat())
    return sorted(out)[:100], ""


@api_view(["GET", "PUT"])
def assistant_settings(request):
    row = LeadAiSettings.load()
    if request.method == "GET":
        return Response(serialize_settings(row, request.user))

    data = request.data if isinstance(request.data, dict) else {}
    can_edit, can_disable = _can_edit(request.user), _can_disable(request.user)
    only_turning_off = set(data) == {"assistant_enabled"} and not _truthy(data.get("assistant_enabled"))
    if not can_edit and not (can_disable and only_turning_off):
        return Response(
            {"detail": "Only a panel admin can change the Lead AI settings; admins may only switch it off."},
            status=status.HTTP_403_FORBIDDEN,
        )

    errors = {}
    changes = {}

    def change(field, new):
        old = getattr(row, field)
        if old != new:
            changes[field] = [str(old), str(new)]
            setattr(row, field, new)

    if "assistant_enabled" in data:
        change("assistant_enabled", _truthy(data.get("assistant_enabled")))
    if "test_numbers" in data:
        numbers, error = _numbers(data.get("test_numbers"))
        if error:
            errors["test_numbers"] = error
        else:
            change("test_numbers", numbers)
    if "closed_dates" in data:
        days, error = _dates(data.get("closed_dates"))
        if error:
            errors["closed_dates"] = error
        else:
            change("closed_dates", days)
    if "office_address" in data:
        address = " ".join(str(data.get("office_address") or "").split())
        if not address:
            errors["office_address"] = "The office address cannot be empty."
        else:
            change("office_address", address[:255])
    if "office_maps_url" in data:
        url = str(data.get("office_maps_url") or "").strip()
        error = _maps_url_error(url) if url else ""
        if error:
            errors["office_maps_url"] = error
        else:
            change("office_maps_url", url)
    if "office_latitude" in data or "office_longitude" in data:
        lat, lat_error = _coordinate(data.get("office_latitude"), Decimal(-90), Decimal(90))
        lng, lng_error = _coordinate(data.get("office_longitude"), Decimal(-180), Decimal(180))
        if lat_error:
            errors["office_latitude"] = f"Latitude {lat_error}."
        if lng_error:
            errors["office_longitude"] = f"Longitude {lng_error}."
        if not (lat_error or lng_error) and (lat is None) != (lng is None):
            errors["office_latitude"] = "Give both latitude and longitude, or neither."
        if not errors.get("office_latitude") and not errors.get("office_longitude"):
            change("office_latitude", lat)
            change("office_longitude", lng)
    if "daily_call_limit" in data:
        try:
            limit = int(data.get("daily_call_limit"))
        except (TypeError, ValueError):
            limit = -1
        if not 0 <= limit <= 20000:
            errors["daily_call_limit"] = "Give a number from 0 to 20000."
        else:
            change("daily_call_limit", limit)
    if "copilot_auto_send_minutes" in data:
        try:
            minutes = int(data.get("copilot_auto_send_minutes"))
        except (TypeError, ValueError):
            minutes = -1
        if not 0 <= minutes <= 180:
            errors["copilot_auto_send_minutes"] = "Give a number of minutes from 0 (never) to 180."
        else:
            change("copilot_auto_send_minutes", minutes)
    if "alert_bitrix_user_ids" in data:
        ids, error = _bitrix_ids(data.get("alert_bitrix_user_ids"))
        if error:
            errors["alert_bitrix_user_ids"] = error
        else:
            change("alert_bitrix_user_ids", ids)
    if "shops_facts" in data:
        facts, problems = shops.validate(data.get("shops_facts"))
        if problems:
            errors.update(problems)
        else:
            change("shops_facts", facts)
    if "residential_facts" in data:
        facts, problems = residential.validate(data.get("residential_facts"))
        if problems:
            errors.update(problems)
        else:
            change("residential_facts", facts)
    if "brand_name" in data:
        brand, error = shops.clean_text(data.get("brand_name"), shops.BRAND_MAX)
        if error or not brand:
            errors["brand_name"] = error or "The brand name cannot be empty."
        else:
            change("brand_name", brand)
    if "viewing_agent_name" in data:
        agent, error = shops.clean_text(data.get("viewing_agent_name"), shops.AGENT_MAX)
        if error:
            errors["viewing_agent_name"] = error
        else:
            change("viewing_agent_name", agent)
    if errors:
        return Response({"detail": "Some values are not valid.", "errors": errors}, status=status.HTTP_400_BAD_REQUEST)
    if changes:
        row.updated_by = request.user
        row.history = (list(row.history or []) + [
            {
                "at": timezone.now().isoformat(),
                "by": request.user.display_name or request.user.get_username(),
                "changes": changes,
            }
        ])[-100:]
        if changes.get("assistant_enabled") and row.assistant_enabled:
            row.paused_until = None
            row.consecutive_failures = 0
        row.save()
    return Response(serialize_settings(row, request.user))
