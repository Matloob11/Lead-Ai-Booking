"""The Lead AI's health in one screen (the advance plan's workstream A5), for ``ops/wa.sh leadai-health`` after a deploy
and whenever something looks slow: the switch, the sweep's age (is worker-leadai alive?), the leadai queue's depth in
Redis, the last hour's turns (replied, skipped, failed, late, how slow), turns stuck running, the chats waiting for a
person and the drafts waiting for one, the messages nobody answered, the inventory's age, the keys configured, the
last digest, and today so far (assistant/digest.py). Exit code 1 when something is red, so a deploy script can stop.

Read only: nothing here writes, sends or calls out but one LLEN to Redis.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from apps.leadai.assistant import digest, hours, inventory, openai_client
from apps.leadai.models import LeadAiAlert, LeadAiChatState, LeadAiDigest, LeadAiSettings, LeadAiTurn, LeadAiUnit

SWEEP_WARN = dt.timedelta(minutes=3)
SWEEP_FAIL = dt.timedelta(minutes=10)
QUEUE_WARN, QUEUE_FAIL = 20, 100
STUCK_AFTER = dt.timedelta(minutes=5)
INVENTORY_WARN = dt.timedelta(minutes=90)
FAIL_RATE_WARN, FAIL_RATE_FAIL = 0.1, 0.3
WAITING_WARN = 10
QUEUE_NAME = "leadai"


def queue_depth() -> int | None:
    """How many tasks wait in the leadai queue (Celery's Redis transport keeps a list per queue), None when Redis is
    out of reach or the broker is not Redis."""
    url = str(getattr(settings, "CELERY_BROKER_URL", "") or getattr(settings, "REDIS_URL", "") or "")
    if not url.startswith("redis"):
        return None
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        return int(client.llen(QUEUE_NAME))
    except Exception:  # noqa: BLE001 - health must never crash on the thing it measures
        return None


def _age(moment, now) -> str:
    if moment is None:
        return "never"
    seconds = int((now - moment).total_seconds())
    if seconds < 90:
        return f"{seconds} s ago"
    if seconds < 5400:
        return f"{seconds // 60} min ago"
    return f"{seconds / 3600:.1f} h ago"


class Command(BaseCommand):
    help = "Lead AI health: the sweep, the queue, the last hour's turns, who waits, the inventory, the keys, the digest."

    def handle(self, *args, **options):
        now = timezone.now()
        levels: list[str] = []

        def line(label: str, value, level: str = "ok") -> None:
            levels.append(level)
            mark = {"ok": " ", "warn": "!", "fail": "X"}[level]
            self.stdout.write(f"{mark} {label}: {value}")

        row = LeadAiSettings.load()
        switch = "on" if row.assistant_enabled else "OFF"
        if row.paused_until and row.paused_until > now:
            switch += f", paused until {row.paused_until.astimezone(hours.DUBAI):%H:%M} Dubai"
        line("switch", switch, "warn" if not row.assistant_enabled else "ok")

        sweep_age = (now - row.last_sweep_at) if row.last_sweep_at else None
        level = "fail" if sweep_age is None or sweep_age > SWEEP_FAIL else "warn" if sweep_age > SWEEP_WARN else "ok"
        line("sweep (worker-leadai)", _age(row.last_sweep_at, now), level)

        depth = queue_depth()
        level = "warn" if depth is None or depth > QUEUE_WARN else "ok"
        if depth is not None and depth > QUEUE_FAIL:
            level = "fail"
        line("leadai queue", "unreachable" if depth is None else f"{depth} waiting", level)

        hour = LeadAiTurn.objects.filter(created_at__gte=now - dt.timedelta(hours=1))
        counts = {item["status"]: item["n"] for item in hour.order_by().values("status").annotate(n=Count("id"))}
        replied, failed = counts.get("replied", 0), counts.get("failed", 0)
        latencies = sorted(int(value or 0) for value in hour.filter(status="replied").values_list("latency_ms", flat=True))
        rate = failed / (replied + failed) if (replied + failed) else 0.0
        level = "fail" if rate >= FAIL_RATE_FAIL and failed >= 3 else "warn" if rate >= FAIL_RATE_WARN and failed >= 2 else "ok"
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))] if latencies else 0
        late = sum(1 for value in latencies if value > digest.LATE_MS)
        line("last hour", f"{replied} replied, {counts.get('skipped', 0)} skipped, {failed} failed ({rate:.0%}); {late} late; p50 {p50 / 1000:.1f} s, p95 {p95 / 1000:.1f} s", level)

        stuck = LeadAiTurn.objects.filter(status="running", created_at__lt=now - STUCK_AFTER).count()
        line("turns stuck running", stuck, "warn" if stuck else "ok")

        waiting = LeadAiChatState.objects.filter(
            handed_over_at__isnull=False, handed_over_at__gte=now - dt.timedelta(days=3), stopped_at__isnull=True, not_interested_at__isnull=True, paused_by__isnull=True
        )
        oldest = waiting.order_by("handed_over_at").values_list("handed_over_at", flat=True).first()
        line("handed over (3 days)", f"{waiting.count()} chats, oldest {_age(oldest, now)}", "warn" if waiting.count() > WAITING_WARN else "ok")
        drafts = LeadAiChatState.objects.filter(draft__isnull=False).count()
        line("drafts waiting", drafts)
        stale = LeadAiAlert.objects.filter(kind="stale", created_at__gte=now - dt.timedelta(hours=1)).values("conversation_id").distinct().count()
        line("unanswered (stale, last hour)", stale, "warn" if stale else "ok")

        units = LeadAiUnit.objects.filter(active=True)
        by_source = {item["source"]: item["n"] for item in units.order_by().values("source").annotate(n=Count("id"))}
        synced = units.order_by("-synced_at").values_list("synced_at", flat=True).first()
        level = "warn" if synced is None or now - synced > INVENTORY_WARN else "ok"
        line("inventory", f"{units.count()} live (pf {by_source.get('pf', 0)}, bitrix {by_source.get('bitrix', 0)}), synced {_age(synced, now)}", level)
        unnamed = units.filter(Q(community="") | Q(community="?")).count()
        line("units without a community", unnamed, "warn" if unnamed > 20 else "ok")

        line("openai key", "configured" if openai_client.configured() else "MISSING", "ok" if openai_client.configured() else "fail")
        line("property finder keys", "configured" if inventory.pf_configured() else "missing", "ok" if inventory.pf_configured() else "warn")
        notify = bool((getattr(settings, "LEADAI_BITRIX_NOTIFY_URL", "") or "").strip() and (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip())
        line("bitrix notifications", "configured" if notify else "missing", "ok" if notify else "warn")

        last = LeadAiDigest.objects.order_by("-day").first()
        yesterday = digest.today(now) - dt.timedelta(days=1)
        if last is None:
            line("digest", "none yet", "warn")
        else:
            level = "ok" if last.day >= yesterday or hours.now_dubai(now).hour < digest.DIGEST_HOUR else "warn"
            line("digest", f"{last.day:%Y-%m-%d}, sent to {len(last.sent_to or [])} user(s), {len(last.errors or [])} refused", level)

        stats = digest.compute(digest.today(now), now)
        self.stdout.write(f"  today so far: {digest.lines(stats)[0]}")
        self.stdout.write(f"  today so far: {digest.lines(stats)[3]}")

        worst = "FAIL" if "fail" in levels else "WARN" if "warn" in levels else "OK"
        self.stdout.write(f"HEALTH: {worst}")
        if worst == "FAIL":
            raise SystemExit(1)
