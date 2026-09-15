from celery import Celery
from celery.schedules import crontab

from ..config import get_settings

settings = get_settings()

celery_app = Celery("agent_reports", broker=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.timezone = settings.agent_report_tz
celery_app.conf.enable_utc = False
celery_app.conf.beat_schedule = {
    "daily-agent-reports": {
        "task": "app.workers.tasks.task_run_daily_reports",
        "schedule": crontab(
            hour=settings.agent_report_cron_hour,
            minute=settings.agent_report_cron_minute,
        ),
    },
    # New Owner Data rows: link Number UF phone → Contact for call button.
    "owner-phone-contact-sync": {
        "task": "app.workers.tasks.task_sync_owner_phone_contacts",
        "schedule": crontab(minute="*/10"),
    },
}
