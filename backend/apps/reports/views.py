"""Read-only numbers about what the inbox actually did.

No models of its own: everything here is derived from messages, conversations
and assignment logs that are already stored. A report that needed its own table
would be a second version of the truth, and would start disagreeing with the
threads the moment one of them was written and the other was not.

Scoped like every other screen — an admin sees every number, an agent sees the
ones they cover — so this cannot become a way to read the volume of a team you
are not on.
"""

import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.inbox.models import Conversation, Message

# Meta's failure codes in the words an admin needs. Several of these are not
# faults at all — knowing which is which is the whole point of the screen,
# because "not delivered" reads like a bug and usually is not one.
ERROR_MEANING = {
    "131047": (
        "Window closed",
        "The customer had not written for 24 hours, so a free-form message was "
        "refused. A template reopens the conversation.",
        False,
    ),
    "131049": (
        "Meta's daily cap",
        "Meta limits how many marketing templates one customer receives per day "
        "across all businesses. Nothing was wrong with the message.",
        False,
    ),
    "131053": (
        "Media rejected",
        "The file could not be uploaded — usually the wrong format or over the "
        "size WhatsApp accepts for that type.",
        True,
    ),
    "131026": (
        "Undeliverable",
        "The number is not on WhatsApp, or cannot receive this kind of message.",
        False,
    ),
    "132000": (
        "Template mismatch",
        "The values sent did not match the number of placeholders the template "
        "was approved with.",
        True,
    ),
    "131056": (
        "Too many to one number",
        "Too many messages to this same customer in a short time.",
        False,
    ),
    "130429": (
        "Rate limited",
        "The account sent faster than Meta allows. The message can be retried.",
        False,
    ),
    "": (
        "No code",
        "The gateway refused the send before Meta saw it, or returned no message "
        "id. The detail on the message says more.",
        True,
    ),
}

MAX_DAYS = 180


def _window(request):
    """The period being asked about, defaulting to the last week."""
    try:
        days = int(request.GET.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, MAX_DAYS))
    until = timezone.now()
    return days, until - timedelta(days=days), until


def _scope(request):
    """The numbers this caller may be told about."""
    numbers = request.user.visible_numbers
    wanted = request.GET.get("number")
    if wanted:
        numbers = numbers.filter(pk=wanted)
    return numbers


def _messages(request):
    days, since, until = _window(request)
    queryset = Message.objects.filter(
        conversation__number__in=_scope(request), created_at__gte=since, created_at__lte=until
    )
    agent = request.GET.get("agent")
    if agent:
        queryset = queryset.filter(sent_by_id=agent)
    return queryset, days, since, until


# First-reply median bands for agent performance (real-estate WhatsApp pace).
# Fewer than MIN_SAMPLES replies → "insufficient" rather than a misleading label.
PERF_MIN_SAMPLES = 3
PERF_BANDS = (
    ("excellent", "Excellent", 5 * 60),       # under 5 minutes
    ("good", "Good", 15 * 60),                # under 15 minutes
    ("fair", "Fair", 60 * 60),                # under 1 hour
    ("bad", "Bad", 4 * 60 * 60),              # under 4 hours
    ("critical", "Critical", None),           # 4 hours or more
)


def _response_gaps_by_agent(queryset):
    """First-reply gaps keyed by the agent who closed the wait (`sent_by_id`).

    Walked in one pass: the interesting number is the *first* reply after each
    inbound run, so a customer sending four messages and getting one answer
    counts once. Gaps with no ``sent_by`` land under ``None``.
    """
    rows = queryset.order_by("conversation_id", "created_at").values_list(
        "conversation_id", "direction", "created_at", "sent_by_id"
    )

    by_agent = defaultdict(list)
    current = None
    waiting_since = None

    for conversation_id, direction, created_at, sent_by_id in rows:
        if conversation_id != current:
            current, waiting_since = conversation_id, None
        if direction == Message.Direction.INBOUND:
            if waiting_since is None:
                waiting_since = created_at
        elif waiting_since is not None:
            gap = (created_at - waiting_since).total_seconds()
            by_agent[sent_by_id].append(gap)
            waiting_since = None
    return by_agent


def _response_gaps(queryset):
    """All first-reply gaps in the queryset (every agent, plus unattributed)."""
    gaps = []
    for agent_gaps in _response_gaps_by_agent(queryset).values():
        gaps.extend(agent_gaps)
    return gaps


def _spread(gaps):
    if not gaps:
        return {
            "count": 0,
            "avg_seconds": None,
            "median_seconds": None,
            "p90_seconds": None,
            "slowest_seconds": None,
        }
    ordered = sorted(gaps)
    return {
        "count": len(ordered),
        "avg_seconds": round(statistics.fmean(ordered)),
        "median_seconds": round(statistics.median(ordered)),
        "p90_seconds": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]),
        "slowest_seconds": round(ordered[-1]),
    }


def _performance_band(spread):
    """Label an agent from median first-reply time (stable vs one slow outlier)."""
    count = int(spread.get("count") or 0)
    median = spread.get("median_seconds")
    if count < PERF_MIN_SAMPLES or median is None:
        return {
            "key": "insufficient",
            "label": "Not enough data",
            "median_seconds": median,
        }
    for key, label, ceiling in PERF_BANDS:
        if ceiling is None or median < ceiling:
            return {"key": key, "label": label, "median_seconds": median}
    return {"key": "critical", "label": "Critical", "median_seconds": median}


def _performance_legend():
    rows = [
        {
            "key": "excellent",
            "label": "Excellent",
            "detail": "Median first reply under 5 minutes",
        },
        {"key": "good", "label": "Good", "detail": "Under 15 minutes"},
        {"key": "fair", "label": "Fair", "detail": "Under 1 hour"},
        {"key": "bad", "label": "Bad", "detail": "Under 4 hours"},
        {"key": "critical", "label": "Critical", "detail": "4 hours or more"},
        {
            "key": "insufficient",
            "label": "Not enough data",
            "detail": f"Fewer than {PERF_MIN_SAMPLES} timed replies in this period",
        },
    ]
    return rows


@api_view(["GET"])
def summary(request):
    """The headline figures, plus a day-by-day series to draw."""
    messages, days, since, until = _messages(request)

    inbound = messages.filter(direction=Message.Direction.INBOUND)
    outbound = messages.filter(direction=Message.Direction.OUTBOUND)
    failed = outbound.filter(status=Message.Status.FAILED).count()
    sent = outbound.count()

    conversations = Conversation.objects.filter(number__in=_scope(request))

    # Bucketed here rather than in SQL so the days land in the panel's timezone
    # and an empty day is still a zero rather than a missing point.
    per_day = defaultdict(lambda: {"in": 0, "out": 0})
    for direction, created_at in messages.values_list("direction", "created_at"):
        key = timezone.localtime(created_at).date().isoformat()
        per_day[key]["in" if direction == Message.Direction.INBOUND else "out"] += 1

    start = timezone.localtime(since).date()
    series = []
    for offset in range(days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        series.append({"date": day, **per_day.get(day, {"in": 0, "out": 0})})

    return Response(
        {
            "from": since.isoformat(),
            "to": until.isoformat(),
            "days": days,
            "inbound": inbound.count(),
            "outbound": sent,
            "failed": failed,
            "failure_rate": round(failed / sent * 100, 1) if sent else 0.0,
            "templates_sent": outbound.filter(kind=Message.Kind.TEMPLATE).count(),
            "customers": inbound.values("conversation__contact_id").distinct().count(),
            "chats_active": messages.values("conversation_id").distinct().count(),
            "chats_new": conversations.filter(created_at__gte=since).count(),
            "chats_total": conversations.count(),
            "windows_open_now": sum(1 for c in conversations if c.is_session_open),
            "unanswered": conversations.filter(
                unread_count__gt=0, last_message_at__gte=since
            ).count(),
            "first_response": _spread(_response_gaps(messages)),
            "daily": series,
        }
    )


@api_view(["GET"])
def agents(request):
    """Who did how much, how quickly, and how that ranks (full list + worst 10)."""
    messages, days, since, until = _messages(request)

    rows = list(
        messages.filter(sent_by__isnull=False)
        .values("sent_by_id", "sent_by__display_name", "sent_by__username", "sent_by__community")
        .annotate(
            sent=Count("pk"),
            delivered=Count("pk", filter=Q(delivered_at__isnull=False)),
            read=Count("pk", filter=Q(read_at__isnull=False)),
            failed=Count("pk", filter=Q(status=Message.Status.FAILED)),
            templates=Count("pk", filter=Q(kind=Message.Kind.TEMPLATE)),
            chats=Count("conversation_id", distinct=True),
        )
        .order_by("-sent")
    )

    # Attribute each first-reply gap to the agent who actually answered — not
    # every agent who ever touched the chat (that used to share the same times).
    gaps_by_agent = _response_gaps_by_agent(messages)

    agents_out = []
    for row in rows:
        agent_id = row["sent_by_id"]
        spread = _spread(gaps_by_agent.get(agent_id, []))
        band = _performance_band(spread)
        agents_out.append(
            {
                "agent_id": agent_id,
                "display_name": row["sent_by__display_name"] or row["sent_by__username"],
                "community": row["sent_by__community"] or "",
                "sent": row["sent"],
                "delivered": row["delivered"],
                "read": row["read"],
                "failed": row["failed"],
                "templates": row["templates"],
                "chats": row["chats"],
                "first_response": spread,
                "performance": band,
            }
        )

    ranked = [
        a
        for a in agents_out
        if a["performance"]["key"] not in ("insufficient",)
        and a["first_response"].get("median_seconds") is not None
    ]
    worst = sorted(
        ranked,
        key=lambda a: (
            a["first_response"]["median_seconds"],
            -(a["first_response"]["count"] or 0),
        ),
        reverse=True,
    )[:10]
    best = sorted(
        ranked,
        key=lambda a: (
            a["first_response"]["median_seconds"],
            -(a["first_response"]["count"] or 0),
        ),
    )[:10]

    return Response(
        {
            "from": since.isoformat(),
            "to": until.isoformat(),
            "days": days,
            "bands": _performance_legend(),
            "agents": agents_out,
            "worst": worst,
            "best": best,
        }
    )


@api_view(["GET"])
def numbers(request):
    """Per number: how busy it is, and whether it can still start a chat."""
    messages, days, since, until = _messages(request)
    scope = list(_scope(request))

    counts = {
        row["conversation__number_id"]: row
        for row in messages.values("conversation__number_id").annotate(
            inbound=Count("pk", filter=Q(direction=Message.Direction.INBOUND)),
            outbound=Count("pk", filter=Q(direction=Message.Direction.OUTBOUND)),
            failed=Count("pk", filter=Q(status=Message.Status.FAILED)),
            chats=Count("conversation_id", distinct=True),
        )
    }

    from apps.catalog.models import WaTemplate, WaTemplateHide

    approved = dict(
        WaTemplateHide.visible(
            WaTemplate.objects.filter(status=WaTemplate.Status.APPROVED)
        )
        .values_list("waba_business_id")
        .annotate(n=Count("pk"))
    )

    out = []
    for number in scope:
        row = counts.get(number.pk, {})
        open_now = Conversation.objects.filter(
            number=number, session_expires_at__gt=timezone.now()
        ).count()
        out.append(
            {
                "number_id": number.pk,
                "phone_number": number.phone_number,
                "title": number.title,
                "inbound": row.get("inbound", 0),
                "outbound": row.get("outbound", 0),
                "failed": row.get("failed", 0),
                "chats": row.get("chats", 0),
                "windows_open": open_now,
                # A number with nothing approved can only answer someone who
                # wrote first, which is worth seeing next to how busy it is.
                "approved_templates": approved.get(number.waba_business_id, 0),
                "agents": [
                    {
                        "display_name": a.agent.display_name or a.agent.get_username(),
                        "community": a.agent.community or "",
                    }
                    for a in number.assignments.filter(is_active=True).select_related("agent")
                ],
            }
        )
    return Response(sorted(out, key=lambda r: -(r["inbound"] + r["outbound"])))


@api_view(["GET"])
def failures(request):
    """Why sends failed, and which of those are nobody's fault."""
    messages, days, since, until = _messages(request)
    failed = messages.filter(status=Message.Status.FAILED).select_related(
        "conversation__contact", "template"
    )

    counts = Counter(m.error_code or "" for m in failed)
    latest = {}
    for message in failed.order_by("-created_at"):
        latest.setdefault(message.error_code or "", message)

    rows = []
    for code, count in counts.most_common():
        label, meaning, actionable = ERROR_MEANING.get(
            code, ("Unknown", "Meta returned a code this panel does not recognise yet.", True)
        )
        sample = latest[code]
        rows.append(
            {
                "code": code,
                "label": label,
                "meaning": meaning,
                # False when there is nothing to fix — the send was refused by a
                # rule, not by a mistake.
                "actionable": actionable,
                "count": count,
                "example": {
                    "message_id": sample.pk,
                    "conversation_id": sample.conversation_id,
                    "contact": str(sample.conversation.contact),
                    "template": sample.template.name if sample.template else "",
                    "detail": sample.error_detail[:200],
                    "created_at": sample.created_at.isoformat(),
                },
            }
        )
    return Response({"total": failed.count(), "reasons": rows})


@api_view(["GET"])
def templates(request):
    """Which templates get used, and how they land."""
    messages, days, since, until = _messages(request)

    rows = (
        messages.filter(kind=Message.Kind.TEMPLATE, template__isnull=False)
        .values("template_id", "template__name", "template__category", "template__language")
        .annotate(
            sent=Count("pk"),
            delivered=Count("pk", filter=Q(delivered_at__isnull=False)),
            read=Count("pk", filter=Q(read_at__isnull=False)),
            failed=Count("pk", filter=Q(status=Message.Status.FAILED)),
            capped=Count("pk", filter=Q(error_code="131049")),
        )
        .order_by("-sent")
    )

    return Response(
        [
            {
                "template_id": row["template_id"],
                "name": row["template__name"],
                "category": row["template__category"],
                "language": row["template__language"],
                "sent": row["sent"],
                "delivered": row["delivered"],
                "read": row["read"],
                "failed": row["failed"],
                # Marketing templates share Meta's per-customer daily cap, so a
                # high number here means the template is fine and the audience
                # has already heard from somebody today.
                "hit_daily_cap": row["capped"],
                "delivery_rate": round(row["delivered"] / row["sent"] * 100, 1)
                if row["sent"]
                else 0.0,
            }
            for row in rows
        ]
    )
