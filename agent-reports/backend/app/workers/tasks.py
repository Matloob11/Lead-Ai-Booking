from __future__ import annotations

import logging

from ..bitrix.client import BitrixClient
from ..bitrix.owner_phone_link import sync_owner_phone_links
from ..config import get_settings
from ..db import SessionLocal, init_db
from ..reports.pipeline import run_daily_reports
from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.task_run_daily_reports")
def task_run_daily_reports() -> dict:
    init_db()
    db = SessionLocal()
    try:
        run = run_daily_reports(db, trigger="schedule", notify=True, upload=True)
        return {"run_id": run.id, "day": run.day.isoformat(), "agents": run.agent_count}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.task_sync_owner_phone_contacts")
def task_sync_owner_phone_contacts(limit: int | None = 200, only_unlinked: bool = True) -> dict:
    """Bind Owner Data phone UFs to Contacts so call buttons stay active.

    Beat runs every 10 minutes with only_unlinked=True and limit=200.
    Pass limit=0 for a full backfill (CLI / one-shot).
    """
    settings = get_settings()
    webhook = settings.webhook_base()
    if not webhook:
        return {"ok": False, "error": "webhook_not_configured"}
    client = BitrixClient(webhook)
    effective_limit = None if limit == 0 else limit
    result = sync_owner_phone_links(
        client,
        limit=effective_limit,
        dry_run=False,
        sleep_s=0.05,
        only_unlinked=only_unlinked,
    )
    logger.info("owner phone sync: %s", result.get("counts"))
    return {"ok": True, **result}
