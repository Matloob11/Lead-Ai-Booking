"""The daily digest (the advance plan's workstream A2): one Lead AI day in numbers.

``compute(day)`` reads the Dubai calendar day from the tables the assistant already keeps — turns (replies, skipped,
failed, how slow), the handovers the turns recorded (``actions.handover``) and whether a person then wrote in the chat
and how long that took, the co-pilot's draft outcomes, the appointments, the opt-outs, the stale alerts, the model's
tokens and their cost — and ``text(stats)`` writes it as one short English message. ``sweep(now)`` runs inside the
minute sweep (tasks.send_due_reminders): from DIGEST_HOUR Dubai it stores yesterday's digest (LeadAiDigest, one row a
day) and sends it once as a Bitrix notification to the panel admins and the Lead AI alert list; days the sweep missed
(a deploy at eight, a worker down) are stored on the following sweeps without a bell, up to BACKFILL_DAYS back. The
panel's Reports dialog and ops/wa.sh leadai-health read the same figures (views.digests, leadai_health).

Counts only, never a customer's words or number: the digest goes to Bitrix as a notification.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, OuterRef, Q, Sum
from django.utils import timezone

from apps.inbox.models import Message

from ..models import (
    LeadAiAlert,
    LeadAiAppointment,
    LeadAiChat,
    LeadAiChatState,
    LeadAiDigest,
    LeadAiDraftOutcome,
    LeadAiOptOut,
    LeadAiSettings,
    LeadAiTurn,
    LeadAiUnit,
)
from . import alerts, hours

logger = logging.getLogger(__name__)

DIGEST_HOUR = 8  # Dubai: the morning after the day it describes
LATE_MS = 60_000  # a reply slower than a minute is late (the customer sees "typing" for nothing that long)
BACKFILL_DAYS = 7
HANDOVERS_READ_AT_MOST = 500
TITLE = "Lead AI daily digest"
# USD per million tokens (prompt, completion) by the model name's start (OpenAI's list prices, 2026); the settings'
# LEADAI_MODEL_PRICES ({"gpt-4.1-mini": [0.4, 1.6]}) overrides or extends it. An unknown model takes DEFAULT_PRICE.
PRICES = (
    ("gpt-4.1-nano", (0.10, 0.40)),
    ("gpt-4.1-mini", (0.40, 1.60)),
    ("gpt-4.1", (2.00, 8.00)),
    ("gpt-4o-mini", (0.15, 0.60)),
    ("gpt-4o", (2.50, 10.00)),
    ("gpt-5-mini", (0.25, 2.00)),
    ("gpt-5", (1.25, 10.00)),
)
DEFAULT_PRICE = (0.40, 1.60)
PERSON_WORDS = {"customer_asked_human": "asked for a person", "call_requested": "asked for a call", "complaint_or_upset": "complaint",
                "legal_visa_licence_contract": "legal or visa", "broker_or_for_client": "broker", "unclear": "unclear",
                "abroad_cannot_visit": "abroad", "meet_at_building": "meet at the building", "questions_for_agent": "questions"}


# ---- the day ---------------------------------------------------------------------------------------------------------


def bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """The Dubai calendar day as two aware moments [start, end)."""
    start = dt.datetime.combine(day, dt.time(0), tzinfo=hours.DUBAI)
    return start, start + dt.timedelta(days=1)


def today(now=None) -> dt.date:
    return hours.now_dubai(now or timezone.now()).date()


def price_of(model: str) -> tuple[float, float]:
    """(prompt, completion) USD per million tokens for a model name ("gpt-4.1-mini-2025-04-14")."""
    name = str(model or "").lower()
    given = getattr(settings, "LEADAI_MODEL_PRICES", None) or {}
    table = [*((str(key).lower(), tuple(value)) for key, value in given.items() if isinstance(value, (list, tuple)) and len(value) == 2), *PRICES]
    for prefix, price in sorted(table, key=lambda item: -len(item[0])):
        if name.startswith(prefix):
            return (float(price[0]), float(price[1]))
    return DEFAULT_PRICE


def _percentile(values: list[int], share: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return int(ordered[index])


def _person_reply(conversation_id: int, since: dt.datetime):
    """The first message someone from our team wrote in the chat at or after ``since`` (engine.human_after's reading:
    anything outbound but ours — a payload source "leadai..." —, a transfer's mirror, a system line and the chat's
    campaign templates), or None."""
    from apps.campaigns.models import CampaignRecipient

    campaign_templates = (
        CampaignRecipient.objects.filter(conversation_id=OuterRef("conversation_id"))
        .exclude(campaign__template_id__isnull=True)
        .values("campaign__template_id")
    )
    return (
        Message.objects.filter(conversation_id=conversation_id, direction=Message.Direction.OUTBOUND, mirrored_from__isnull=True, created_at__gte=since)
        .exclude(kind="system")
        .exclude(Q(payload__has_key="source") & Q(payload__source__startswith="leadai"))
        .exclude(kind=Message.Kind.TEMPLATE, template_id__in=campaign_templates)
        .order_by("created_at", "pk")
        .select_related("sent_by")
        .first()
    )


def _handovers(turns, now) -> dict:
    """The handovers the day's turns recorded, one per chat: how many, how many a person then took and how fast, who,
    why; and how many chats wait for a person right now (desk.needs_rows' reading, counts only)."""
    rows = (
        turns.filter(actions__has_key="handover")
        .order_by("created_at", "pk")
        .values_list("conversation_id", "created_at", "actions")[:HANDOVERS_READ_AT_MOST]
    )
    first: dict[int, tuple[dt.datetime, str]] = {}
    for conversation_id, created, actions in rows:
        reason = str((actions or {}).get("handover") or "") if isinstance(actions, dict) else ""
        first.setdefault(conversation_id, (created, reason))
    taken, minutes, by, reasons = 0, [], {}, {}
    for conversation_id, (created, reason) in first.items():
        reasons[PERSON_WORDS.get(reason, reason or "unclear")] = reasons.get(PERSON_WORDS.get(reason, reason or "unclear"), 0) + 1
        reply = _person_reply(conversation_id, created)
        if reply is None:
            continue
        taken += 1
        minutes.append(max(0, int((reply.created_at - created).total_seconds() // 60)))
        who = (reply.sent_by.display_name or reply.sent_by.get_username()) if reply.sent_by is not None else "phone app"
        by[who] = by.get(who, 0) + 1
    waiting = (
        LeadAiChatState.objects.filter(handed_over_at__isnull=False, stopped_at__isnull=True, not_interested_at__isnull=True, paused_by__isnull=True)
        .filter(handed_over_at__gte=now - dt.timedelta(days=3))
        .count()
    )
    return {
        "new": len(first),
        "taken": taken,
        "median_minutes": _percentile(minutes, 0.5) if minutes else None,
        "by": dict(sorted(by.items(), key=lambda item: (-item[1], item[0]))),
        "reasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        "waiting_now": waiting,
    }


def compute(day: dt.date, now=None) -> dict:
    """The day's figures, JSON-ready (LeadAiDigest.stats)."""
    now = now or timezone.now()
    start, end = bounds(day)
    turns = LeadAiTurn.objects.filter(created_at__gte=start, created_at__lt=end)
    by_status = {row["status"]: row["n"] for row in turns.order_by().values("status").annotate(n=Count("id"))}
    replied = turns.filter(status=LeadAiTurn.Status.REPLIED)
    latencies = [int(value or 0) for value in replied.values_list("latency_ms", flat=True)]
    usage = {"prompt": 0, "completion": 0, "calls": 0, "usd": 0.0}
    for row in turns.order_by().values("model").annotate(prompt=Sum("prompt_tokens"), completion=Sum("completion_tokens"), calls=Sum("calls")):
        prompt_price, completion_price = price_of(row["model"])
        prompt, completion = int(row["prompt"] or 0), int(row["completion"] or 0)
        usage["prompt"] += prompt
        usage["completion"] += completion
        usage["calls"] += int(row["calls"] or 0)
        usage["usd"] += prompt * prompt_price / 1_000_000 + completion * completion_price / 1_000_000
    replies = by_status.get(LeadAiTurn.Status.REPLIED, 0)
    drafts = {row["kind"]: row["n"] for row in LeadAiDraftOutcome.objects.filter(created_at__gte=start, created_at__lt=end).order_by().values("kind").annotate(n=Count("id"))}
    appointments = LeadAiAppointment.objects.filter(created_at__gte=start, created_at__lt=end)
    opt_outs = LeadAiOptOut.objects.filter(created_at__gte=start, created_at__lt=end)
    inventory = LeadAiUnit.objects.filter(active=True).aggregate(n=Count("id"), synced=Max("synced_at"))
    settings_row = LeadAiSettings.load()
    return {
        "day": day.isoformat(),
        "turns": {
            "replied": replies,
            "skipped": by_status.get(LeadAiTurn.Status.SKIPPED, 0),
            "failed": by_status.get(LeadAiTurn.Status.FAILED, 0),
            "late": sum(1 for value in latencies if value > LATE_MS),
            "p50_ms": _percentile(latencies, 0.5),
            "p95_ms": _percentile(latencies, 0.95),
        },
        "chats": {
            "answered": replied.values("conversation_id").distinct().count(),
            "active": LeadAiChat.objects.filter(active=True).count(),
        },
        "handovers": _handovers(turns, now),
        "drafts": {kind: drafts.get(kind, 0) for kind in LeadAiDraftOutcome.Kind.values},
        "bookings": {
            "created": appointments.count(),
            **{status: n for status, n in ((row["status"], row["n"]) for row in appointments.order_by().values("status").annotate(n=Count("id")))},
            "visits": appointments.exclude(place=LeadAiAppointment.Place.CALL).count(),
            "calls": appointments.filter(place=LeadAiAppointment.Place.CALL).count(),
        },
        "opt_outs": {
            "total": opt_outs.count(),
            "by_source": {row["source"]: row["n"] for row in opt_outs.order_by().values("source").annotate(n=Count("id"))},
        },
        "stale": LeadAiAlert.objects.filter(kind="stale", created_at__gte=start, created_at__lt=end).values("conversation_id").distinct().count(),
        "cost": {
            "calls": usage["calls"],
            "prompt_tokens": usage["prompt"],
            "completion_tokens": usage["completion"],
            "usd": round(usage["usd"], 2),
            "usd_per_reply": round(usage["usd"] / replies, 4) if replies else 0.0,
        },
        "inventory": {"active": inventory["n"] or 0, "synced_at": inventory["synced"].isoformat() if inventory["synced"] else None},
        "sweep_at": settings_row.last_sweep_at.isoformat() if settings_row.last_sweep_at else None,
        "assistant_enabled": bool(settings_row.assistant_enabled),
        "computed_at": now.isoformat(),
    }


# ---- the words -------------------------------------------------------------------------------------------------------


def _n(value) -> str:
    return f"{int(value or 0):,}"


def _tokens(value) -> str:
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value // 1_000}k"
    return str(value)


def _listed(counts: dict, limit: int = 4) -> str:
    return ", ".join(f"{name} {n}" for name, n in list(counts.items())[:limit])


def lines(stats: dict) -> list[str]:
    """The digest as short English lines (the Bitrix message's body and the panel's text)."""
    turns, chats, hand, drafts, book, opt, cost, inv = (stats.get(key) or {} for key in ("turns", "chats", "handovers", "drafts", "bookings", "opt_outs", "cost", "inventory"))
    out = [
        f"Replies: {_n(turns.get('replied'))} in {_n(chats.get('answered'))} chats ({_n(turns.get('skipped'))} skipped, {_n(turns.get('failed'))} failed); "
        f"{_n(turns.get('late'))} late (over a minute); median {int(turns.get('p50_ms') or 0) / 1000:.1f} s."
    ]
    taken = f"{_n(hand.get('taken'))} taken by a person"
    if hand.get("median_minutes") is not None:
        taken += f" (median {_n(hand.get('median_minutes'))} min"
        taken += f"; {_listed(hand.get('by') or {})})" if hand.get("by") else ")"
    out.append(f"Handovers: {_n(hand.get('new'))} new; {taken}; {_n(hand.get('waiting_now'))} waiting now." + (f" Why: {_listed(hand.get('reasons') or {})}." if hand.get("reasons") else ""))
    out.append(
        f"Drafts: {_n(drafts.get('sent'))} sent as written, {_n(drafts.get('edited'))} edited, {_n(drafts.get('auto'))} went out by themselves, "
        f"{_n(drafts.get('dismissed'))} dismissed."
    )
    out.append(
        f"Bookings: {_n(book.get('created'))} ({_n(book.get('visits'))} office visits, {_n(book.get('calls'))} calls); "
        f"{_n(book.get('confirmed'))} confirmed, {_n(book.get('tentative'))} tentative, {_n(book.get('cancelled'))} cancelled."
    )
    sources = {LeadAiOptOut.Source(key).label if key in LeadAiOptOut.Source.values else key: n for key, n in (opt.get("by_source") or {}).items()}
    out.append(f"Opt-outs: {_n(opt.get('total'))}." + (f" {_listed(sources, 3)}." if sources else ""))
    if stats.get("stale"):
        out.append(f"Messages nobody answered in time: {_n(stats.get('stale'))} chats.")
    out.append(
        f"Model: {_n(cost.get('calls'))} calls, {_tokens(cost.get('prompt_tokens'))} prompt + {_tokens(cost.get('completion_tokens'))} completion tokens "
        f"≈ ${float(cost.get('usd') or 0):.2f} (${float(cost.get('usd_per_reply') or 0):.4f} a reply)."
    )
    synced = stats.get("inventory", {}).get("synced_at")
    out.append(f"Inventory: {_n(inv.get('active'))} units live" + (f", synced {synced[11:16]} UTC." if synced else ", never synced."))
    if not stats.get("assistant_enabled", True):
        out.append("The assistant is switched off.")
    return out


def heading(day: dt.date) -> str:
    return f"Lead AI — {day:%A} {day.day} {day:%b %Y}"


def text(stats: dict) -> str:
    day = dt.date.fromisoformat(stats["day"])
    return "\n".join([heading(day), *lines(stats)])


# ---- storing and sending ---------------------------------------------------------------------------------------------


def recipients() -> list[int]:
    """The panel admins' Bitrix ids, then the Lead AI alert list's, each once."""
    ids: list[int] = []
    for _agent, bitrix_id in alerts.admin_recipients():
        if bitrix_id.isdigit() and int(bitrix_id) not in ids:
            ids.append(int(bitrix_id))
    for item in LeadAiSettings.load().alert_user_ids():
        if str(item).isdigit() and int(item) not in ids:
            ids.append(int(item))
    return ids


def send(day: dt.date, *, now=None, deliver: bool = True) -> LeadAiDigest | None:
    """Store the day's digest (once: the day is unique) and, ``deliver``, send it to each recipient. None when the day
    already has its row."""
    now = now or timezone.now()
    stats = compute(day, now)
    body = text(stats)
    try:
        with transaction.atomic():
            row = LeadAiDigest.objects.create(day=day, stats=stats, text=body)
    except IntegrityError:
        return None
    if not deliver:
        return row
    sent, errors = [], []
    for user_id in recipients():
        try:
            answer = alerts.notify_bitrix(
                to_user_id=user_id, title=TITLE, message=body[:alerts.MESSAGE_MAX], push=f"{heading(day)}: {lines(stats)[0][:120]}",
                tag=f"LEADAI|DIGEST|{day:%Y%m%d}|{user_id}", url=alerts.PANEL_PATH,
            )
        except Exception as exc:  # noqa: BLE001 - one refused bell must not lose the others
            errors.append({"user": user_id, "error": str(exc)[:200]})
            continue
        if isinstance(answer, dict) and answer.get("ok"):
            sent.append(user_id)
        else:
            errors.append({"user": user_id, "error": str((answer or {}).get("error") or "refused")[:200]})
    row.sent_to, row.errors = sent, errors
    row.save(update_fields=["sent_to", "errors"])
    logger.info("Lead AI digest for %s sent to %s user(s), %s refused", day, len(sent), len(errors))
    return row


def due(now=None) -> dt.date | None:
    """The oldest day of the last BACKFILL_DAYS with no digest yet — yesterday only from DIGEST_HOUR Dubai on; None
    when every day has one."""
    now = now or timezone.now()
    local = hours.now_dubai(now)
    missing = None
    for offset in range(1, BACKFILL_DAYS + 1):
        day = local.date() - dt.timedelta(days=offset)
        if offset == 1 and local.hour < DIGEST_HOUR:
            continue
        if not LeadAiDigest.objects.filter(day=day).exists():
            missing = day
    return missing


def sweep(now=None) -> dt.date | None:
    """One missing day per sweep: yesterday's with the bell, an older one quietly. The day stored, or None."""
    now = now or timezone.now()
    day = due(now)
    if day is None:
        return None
    row = send(day, now=now, deliver=day == hours.now_dubai(now).date() - dt.timedelta(days=1))
    return day if row is not None else None
