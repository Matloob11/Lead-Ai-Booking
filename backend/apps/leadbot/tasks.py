"""Debounced Sara reply after an inbound customer message. Agent replies do not pause this."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.inbox.models import Message
from apps.inbox.services import SendBlocked, send_text

from . import bitrix_sync
from .models import LeadAutomation
from .outreach import AI_SOURCE
from .qualify import decide
from .reply import MAX_REPLIES_PER_DAY, ReplyError, configured, draft

logger = logging.getLogger(__name__)

SKIP_KINDS = frozenset({"reaction", "system"})
ACTIVE = (LeadAutomation.State.AWAITING_REPLY, LeadAutomation.State.ACTIVE)


def _memory(row: LeadAutomation) -> str:
    snap = row.snapshot if isinstance(row.snapshot, dict) else {}
    confirmed = row.confirmed_fields if isinstance(row.confirmed_fields, dict) else {}
    lines = [
        f"Bitrix lead id: {row.bitrix_lead_id}",
        f"Title: {snap.get('title') or ''}",
        f"Current stage: {snap.get('status_id') or ''}",
        f"Source: {snap.get('source_id') or ''}",
        f"Budget field: {snap.get('opportunity') or ''}",
        "Confirmed customer facts: " + (", ".join(f"{k}={v}" for k, v in confirmed.items()) or "(none yet)"),
        "Do not invent listing facts that are not written above.",
    ]
    return "\n".join(lines)


@shared_task(ignore_result=True)
def reply_to_inbound(message_id: int) -> None:
    inbound = (
        Message.objects.select_related("conversation", "conversation__contact")
        .filter(pk=message_id)
        .first()
    )
    if inbound is None or inbound.direction != Message.Direction.INBOUND:
        return
    if inbound.kind in SKIP_KINDS:
        return

    conversation = inbound.conversation
    latest = (
        conversation.messages.filter(direction=Message.Direction.INBOUND)
        .exclude(kind__in=SKIP_KINDS)
        .order_by("-id")
        .first()
    )
    if latest is None or latest.pk != inbound.pk:
        logger.info("leadbot skip burst superseded message=%s", message_id)
        return

    row = (
        LeadAutomation.objects.filter(conversation_id=conversation.pk, state__in=ACTIVE)
        .order_by("-id")
        .first()
    )
    if row is None:
        return

    # A Lead AI campaign put this chat in the Lead AI screen for the agent;
    # Sara stays silent there (apps/leadai).
    from apps.leadai.lane import is_lead_ai

    if is_lead_ai(conversation):
        logger.info("leadbot skip conversation %s: Lead AI chat", conversation.pk)
        return

    conversation.refresh_from_db(fields=["session_expires_at"])
    if not conversation.is_session_open:
        logger.info("leadbot skip conversation %s: 24h window closed", conversation.pk)
        return

    since = timezone.now() - timedelta(hours=24)
    already = conversation.messages.filter(
        direction=Message.Direction.OUTBOUND,
        created_at__gte=since,
        payload__source=AI_SOURCE,
    ).count()
    if already >= MAX_REPLIES_PER_DAY:
        logger.info("leadbot daily cap conversation=%s", conversation.pk)
        return

    if not configured():
        logger.warning("leadbot has no OpenAI key; conversation=%s", conversation.pk)
        return

    history = list(conversation.messages.exclude(kind__in=SKIP_KINDS).order_by("id"))
    try:
        data = draft(messages=history, memory=_memory(row), inbound_text=inbound.body or "")
    except ReplyError as exc:
        logger.warning("leadbot draft failed conversation=%s: %s", conversation.pk, exc)
        return

    confirmed = dict(row.confirmed_fields or {})
    extra = data.get("confirmed_fields")
    if isinstance(extra, dict):
        for key, val in extra.items():
            if val not in (None, ""):
                confirmed[str(key)] = val
    for key in (
        "for_self_or_client",
        "move_in_date",
        "cheques",
        "occupancy",
        "lead_type",
        "viewing_time",
        "buyer_type",
        "unit_preference",
        "community_flexibility",
    ):
        if data.get(key) not in (None, ""):
            confirmed[key] = data[key]
    confirmed["last_customer_text"] = (inbound.body or "")[:500]

    decision = decide(data, confirmed=confirmed)
    bitrix_sync.apply_ai_fields(row.bitrix_lead_id, {**data, **confirmed})

    current_status = ""
    try:
        lead = bitrix_sync.get_lead(row.bitrix_lead_id)
        current_status = str(lead.get("STATUS_ID") or "")
        row.snapshot = {
            **(row.snapshot or {}),
            "title": lead.get("TITLE") or (row.snapshot or {}).get("title", ""),
            "status_id": current_status,
        }
    except Exception as exc:
        logger.warning("leadbot refresh lead %s: %s", row.bitrix_lead_id, exc)

    if decision["status_id"]:
        bitrix_sync.apply_stage(
            row.bitrix_lead_id,
            status_id=decision["status_id"],
            current_status=current_status,
        )
        bitrix_sync.timeline(
            row.bitrix_lead_id,
            "=== A7 AI CLASSIFICATION === " + (decision["reason"] or decision["status_id"]),
        )

    row.confirmed_fields = {k: v for k, v in confirmed.items() if k != "last_customer_text"}
    row.qualification_reason = (decision["reason"] or "")[:255]
    if decision["stop"]:
        row.state = (
            LeadAutomation.State.JUNK
            if decision["status_id"] == bitrix_sync.STATUS_JUNK
            else LeadAutomation.State.QUALIFIED
        )
        row.qualified_at = timezone.now()
    else:
        row.state = LeadAutomation.State.ACTIVE
    row.last_error = ""
    row.save()

    if not data.get("shouldReply"):
        logger.info("leadbot silent turn conversation=%s", conversation.pk)
        return

    agent = row.agent
    if agent is None:
        logger.info("leadbot no agent on lead %s", row.bitrix_lead_id)
        return
    try:
        message = send_text(
            conversation,
            agent,
            data["reply"],
            reply_to=inbound if inbound.wamid else None,
            payload={"source": AI_SOURCE, "bitrix_lead_id": row.bitrix_lead_id},
        )
    except SendBlocked as exc:
        logger.info("leadbot send blocked conversation=%s: %s", conversation.pk, exc)
        return
    except Exception:
        logger.exception("leadbot send failed conversation=%s", conversation.pk)
        return

    bitrix_sync.timeline(
        row.bitrix_lead_id,
        "=== A7 AI CLASSIFICATION PROOF === " + (message.body or "")[:500],
    )
