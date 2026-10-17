"""Heads-ups for the agents who own a Lead AI customer (owner's rules 54-56, 60).

Who: the chat's owner (who sent the campaign and can open the chat) AND the
CRM record's responsible person (owner's choice), each once. Bookings and
the other appointment events, handovers (a broker among them) and messages
nobody answered also reach every active agent whose Bitrix id the Lead AI
settings list (owner's choice 2026-10-13: Matloob). System alerts (OpenAI
down, no credit, daily ceiling) go to the panel admins.

How (owner's choice): the WhatsApp panel, as a live ``leadai.alert`` to an
agent who can open the chat, and Bitrix, as a notification with mobile push
through /bitrix/tools/a7_leadai_notify.php (the backend's webhook has no
"im" scope).

An alert is one database row per recipient first; ``dedupe_key`` (which
names the recipient) is unique, so the same event never alerts the same
person twice. Delivery happens in a Celery task after the commit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import LeadAiAlert, LeadAiChatState

logger = logging.getLogger(__name__)

SIGN_PREFIX = b"leadai-notify."
MESSAGE_MAX = 1000
# The WhatsApp panel inside Bitrix, for alerts with no CRM record to open.
PANEL_PATH = "/marketplace/app/76/"
# Bitrix users 0 and 1 hold unassigned leads; they are nobody's work, so
# they never get a Bitrix notification (an agent linked to one still gets the
# panel toast).
HOLD_USERS = {"", "0", "1"}
# The alerts the listed Bitrix users get as well (LeadAiSettings.alert_bitrix_user_ids).
# The rest (a fault, a cap, a failed send) stay with the chat's own people.
LISTED_KINDS = frozenset(
    {
        "booked", "hot_lead", "tentative", "rescheduled", "cancelled", "on_my_way", "running_late",
        "reschedule_requested", "handover", "stale",
        # A shops customer's licence copy that could not reach the lead (tasks.write_licence_file),
        # and a Bot Status a person set in Bitrix (bitrix_status.py).
        "licence", "bitrix_status",
        # A shops customer who wants no shop to rent: what they want, for a person to prepare (engine._wanted_alert).
        "wanted",
        # A shops customer's question the assistant left to a colleague, unanswered two hours on (no nudge went:
        # followups.OPEN_QUESTION), and a shops chat's tentative visit of theirs that lapsed (tasks._close_past_appointments).
        "open_question", "tentative_lapsed",
        # While a person has the chat: the customer chased us, or gave their call's time (engine._quiet_alert);
        # and a shops handover nobody answered in 30 minutes of office time (people.escalate_waiting).
        "chase", "call_time", "handover_waiting",
        # A shops customer said no: Bot Status Lost, the lead moved only if nobody works it (engine.record_opt_out, lost.py).
        "lost",
        # A shops customer's must-answer questions, while the assistant goes on with the chat (engine._questions_alert).
        "questions",
    }
)
# The alerts that go to the panel admins, not to a chat's people (a chat's responsible never needs them).
ADMIN_KINDS = frozenset({"ai_quota", "ai_down", "global_cap"})

CRM_PATHS = {
    "lead": "/crm/lead/details/{id}/",
    "deal": "/crm/deal/details/{id}/",
    "contact": "/crm/contact/details/{id}/",
    "owner_data": "/crm/type/1042/details/{id}/",
}


class AlertDeliveryError(Exception):
    """Bitrix could not be reached; the task retries."""


def crm_path(entity: str, crm_id) -> str:
    template = CRM_PATHS.get(entity or "")
    return template.format(id=int(crm_id)) if template and crm_id else ""


def _bitrix_target(bitrix_user_id) -> str:
    """The Bitrix user to notify, or '' for nobody: a hold user (0, 1) gets the panel toast only."""
    bitrix_id = str(bitrix_user_id or "").strip()
    return "" if bitrix_id in HOLD_USERS else bitrix_id


def recipients(conversation, *, listed: bool = False) -> list:
    """[(agent or None, bitrix_user_id)]: the chat owner, then the CRM responsible if
    different, then (``listed``) each agent the settings list who is neither."""
    out = []
    owner = conversation.assigned_agent
    if owner is not None:
        out.append((owner, _bitrix_target(owner.bitrix_user_id)))
    state = LeadAiChatState.objects.filter(conversation=conversation).select_related("responsible_agent").first()
    if state is not None:
        bitrix_id = (state.responsible_bitrix_user_id or "").strip()
        agent = state.responsible_agent
        if bitrix_id not in HOLD_USERS:
            known = {a.pk for a, _ in out if a is not None} | {b for _, b in out if b}
            if (agent is None or agent.pk not in known) and bitrix_id not in known:
                out.append((agent, bitrix_id))
    if listed:
        for agent in listed_agents():
            target = _bitrix_target(agent.bitrix_user_id)
            # One row per person: the owner or the responsible already has it.
            if any(a is not None and a.pk == agent.pk for a, _ in out) or (target and target in {b for _, b in out}):
                continue
            out.append((agent, target))
    return out


def listed_agents() -> list:
    """The active agents whose Bitrix ids the Lead AI settings list (an id with no agent is nobody)."""
    from django.contrib.auth import get_user_model

    from ..models import LeadAiSettings

    ids = LeadAiSettings.load().alert_user_ids()
    if not ids:
        return []
    return list(get_user_model().objects.filter(is_active=True, bitrix_user_id__in=ids).order_by("pk"))


def admin_recipients() -> list:
    from django.contrib.auth import get_user_model

    agents = get_user_model().objects.filter(is_active=True, is_wa_admin=True)
    return [(agent, _bitrix_target(agent.bitrix_user_id)) for agent in agents]


def raise_alert(
    *,
    kind: str,
    conversation,
    title: str,
    text: str,
    appointment=None,
    priority: str = LeadAiAlert.Priority.NORMAL,
    dedupe_key: str = "",
    crm_url: str = "",
    admins: bool = False,
    listed: bool | None = None,
) -> list:
    """Record one alert per recipient and deliver each after the commit.

    Returns the new rows; a recipient already alerted for this event is skipped.
    ``listed``: whether the Lead AI alert list hears it too; None reads the kind (LISTED_KINDS), True or False
    decides for this one (a shops chat's reply cap and opt-out reach the list: caps.alert, engine.record_opt_out).
    """
    from ..tasks import deliver_alert

    base = (dedupe_key or f"{kind}:{conversation.pk}:{timezone.now():%Y%m%d%H%M%S%f}")[:180]
    targets = admin_recipients() if admins else recipients(conversation, listed=kind in LISTED_KINDS if listed is None else listed)
    created = []
    for agent, bitrix_id in targets:
        who = f"a{agent.pk}" if agent is not None else f"b{bitrix_id}"
        try:
            with transaction.atomic():
                alert = LeadAiAlert.objects.create(
                    kind=kind,
                    priority=priority,
                    conversation=conversation,
                    appointment=appointment,
                    agent=agent,
                    bitrix_user_id=bitrix_id if bitrix_id.isdigit() else "",
                    title=title[:200],
                    text=text[:2000],
                    crm_url=crm_url[:200],
                    dedupe_key=f"{base}:{who}"[:220],
                )
        except IntegrityError:
            continue
        created.append(alert)
        transaction.on_commit(lambda pk=alert.pk: deliver_alert.delay(pk))
    return created


def reach_responsible(conversation, since) -> int:
    """The chat's alerts raised since ``since``, before its CRM responsible was known, reach that person now
    (tasks.resolve_responsible, right after the lookup): the same event under the same key, so whoever has it
    is skipped and only the responsible gets a row. Launch chat 112: a STOP as the first answer was alerted
    before the lookup ever ran, so the lead's owner never heard of it, sent two templates and called three
    times. How many rows were added."""
    rows = (
        LeadAiAlert.objects.filter(conversation=conversation, created_at__gte=since)
        .exclude(kind__in=ADMIN_KINDS)
        .select_related("appointment")
        .order_by("pk")
    )
    seen: set[str] = set()
    added = 0
    for row in rows:
        base = (row.dedupe_key or "").rsplit(":", 1)[0]
        if not base or base in seen:
            continue
        seen.add(base)
        added += len(
            raise_alert(
                kind=row.kind,
                conversation=conversation,
                title=row.title,
                text=row.text,
                appointment=row.appointment,
                priority=row.priority,
                dedupe_key=base,
                crm_url=row.crm_url,
                listed=False,
            )
        )
    return added


def panel_payload(alert: LeadAiAlert) -> dict:
    """Flat ids only: the main inbox drops any chat named by a conversation object."""
    from ..models import LeadAiChat

    return {
        "id": alert.pk,
        "kind": alert.kind,
        "priority": alert.priority,
        "title": alert.title,
        "text": alert.text,
        "conversation_id": alert.conversation_id,
        "appointment_id": alert.appointment_id,
        "lead_ai": LeadAiChat.objects.filter(conversation_id=alert.conversation_id, active=True).exists(),
        "created_at": alert.created_at.isoformat() if alert.created_at else "",
    }


def _can_open(agent, conversation_id) -> bool:
    from apps.inbox.models import Conversation
    from apps.inbox.visibility import visible_conversation_q

    try:
        return Conversation.objects.filter(pk=conversation_id).filter(visible_conversation_q(agent)).exists()
    except Exception:  # noqa: BLE001 - a lookup problem only costs the panel toast
        return False


def deliver(alert: LeadAiAlert) -> None:
    """Panel first (cheap, cannot fail the task), then Bitrix (may raise to retry)."""
    if alert.panel_sent_at is None and alert.agent_id and _can_open(alert.agent, alert.conversation_id):
        from apps.inbox.events import publish_to_agent

        publish_to_agent(alert.agent_id, "leadai.alert", panel_payload(alert))
        alert.panel_sent_at = timezone.now()
        alert.save(update_fields=["panel_sent_at"])

    if alert.bitrix_sent_at is not None:
        return
    if not alert.bitrix_user_id.isdigit():
        if not alert.bitrix_error:
            alert.bitrix_error = "No Bitrix user to notify."
            alert.save(update_fields=["bitrix_error"])
        return
    answer = _notify(alert, alert.bitrix_user_id)
    if not answer.get("ok") and "active user" in str(answer.get("error") or ""):
        # The CRM responsible has left: tell the chat's owner instead, unless
        # the owner has this alert as their own row already (no double buzz).
        owner = alert.conversation.assigned_agent
        fallback = _bitrix_target(getattr(owner, "bitrix_user_id", ""))
        base = alert.dedupe_key.rsplit(":", 1)[0]
        if owner is not None and LeadAiAlert.objects.filter(dedupe_key=f"{base}:a{owner.pk}"[:220]).exists():
            answer = {"ok": False, "error": "The CRM responsible is not an active Bitrix user; the chat owner has this alert."}
        elif fallback.isdigit() and fallback != alert.bitrix_user_id:
            answer = _notify(alert, fallback)
    if answer.get("ok"):
        alert.bitrix_sent_at = timezone.now()
        alert.bitrix_error = ""
        alert.save(update_fields=["bitrix_sent_at", "bitrix_error"])
    else:
        # A refusal (no such user, not configured) will not get better by retrying.
        alert.bitrix_error = str(answer.get("error") or "Refused")[:500]
        alert.save(update_fields=["bitrix_error"])


def _notify(alert: LeadAiAlert, bitrix_user_id: str) -> dict:
    try:
        return notify_bitrix(
            to_user_id=int(bitrix_user_id),
            title=alert.title,
            message=alert.text,
            push=alert.title,
            tag=f"LEADAI|{alert.kind}|{alert.conversation_id}|{alert.pk}|{bitrix_user_id}",
            url=alert.crm_url or PANEL_PATH,
        )
    except AlertDeliveryError as exc:
        alert.bitrix_error = str(exc)[:500]
        alert.save(update_fields=["bitrix_error"])
        raise


def sign(raw: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), SIGN_PREFIX + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def notify_bitrix(*, to_user_id: int, title: str, message: str, push: str = "", tag: str = "", url: str = "") -> dict:
    """POST one signed notification to the Bitrix tool. Raises AlertDeliveryError on transport trouble."""
    endpoint = (getattr(settings, "LEADAI_BITRIX_NOTIFY_URL", "") or "").strip()
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    if not endpoint or not secret:
        return {"ok": False, "error": "Bitrix notifications are not configured."}
    raw = json.dumps(
        {
            "to_user_id": to_user_id,
            "title": title[:200],
            "message": message[:MESSAGE_MAX],
            "push": (push or title)[:200],
            "tag": tag[:100],
            "url": url,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    ts = str(int(time.time()))
    try:
        response = httpx.post(
            endpoint,
            content=raw,
            headers={"Content-Type": "application/json", "X-Leadai-Ts": ts, "X-Leadai-Sign": sign(raw, ts, secret)},
            timeout=httpx.Timeout(15, connect=5),
        )
    except httpx.HTTPError as exc:
        raise AlertDeliveryError(f"Bitrix unreachable: {type(exc).__name__}") from None
    if response.status_code >= 500 or response.status_code == 429:
        raise AlertDeliveryError(f"Bitrix answered {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise AlertDeliveryError(f"Bitrix answered {response.status_code} without JSON") from None
    return body if isinstance(body, dict) else {"ok": False, "error": "Unexpected answer"}
