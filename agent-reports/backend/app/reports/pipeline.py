"""Orchestrate collect → AI → PDF → DB for one agent or a full day run."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..bitrix.agents import Agent, list_sales_ts_agents
from ..bitrix.client import BitrixClient
from ..bitrix.metrics import collect_agent_day
from ..config import get_settings
from ..models import AgentReport, ReportRun
from .ai_summary import write_ai_summary
from .deliver import deliver_digest, upload_pdf
from .pdf import write_pdf

logger = logging.getLogger(__name__)


def _client() -> BitrixClient:
    return BitrixClient(get_settings().webhook_base())


def _storage_path(day: date, agent_id: int) -> Path:
    settings = get_settings()
    root = Path(settings.storage_dir)
    return root / day.isoformat() / f"{agent_id}.pdf"


def generate_one(
    db: Session,
    *,
    agent: Agent,
    day: date,
    run: ReportRun,
    upload: bool = False,
) -> AgentReport:
    settings = get_settings()
    client = _client()
    row = AgentReport(
        run_id=run.id,
        agent_id=agent.id,
        agent_name=agent.name,
        day=day,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    try:
        snap = collect_agent_day(
            client,
            agent_id=agent.id,
            agent_name=agent.name,
            day=day,
            tz_name=settings.agent_report_tz,
            owner_data_entity_type_id=settings.agent_report_owner_data_entity_type_id,
        )
        summary = write_ai_summary(snap)
        pdf_path = _storage_path(day, agent.id)
        write_pdf(snap, summary, pdf_path)
        disk_id = ""
        if upload:
            try:
                disk_id = upload_pdf(client, pdf_path, f"agent-{agent.id}-{day}.pdf")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Disk upload failed for %s: %s", agent.id, exc)

        row.status = "done"
        row.metrics_json = json.dumps(snap.as_dict(), ensure_ascii=True)
        row.ai_summary = summary
        row.pdf_path = str(pdf_path)
        row.disk_file_id = disk_id
        row.error = ""
        db.commit()
        db.refresh(row)
        return row
    except Exception as exc:  # noqa: BLE001
        logger.exception("Generate failed for agent %s", agent.id)
        row.status = "failed"
        row.error = str(exc)[:2000]
        db.commit()
        db.refresh(row)
        return row


def run_daily_reports(
    db: Session,
    *,
    day: date | None = None,
    trigger: str = "manual",
    agent_ids: list[int] | None = None,
    notify: bool = True,
    upload: bool = True,
) -> ReportRun:
    settings = get_settings()
    tz = ZoneInfo(settings.agent_report_tz)
    report_day = day or datetime.now(tz).date()
    client = _client()
    agents = list_sales_ts_agents(client, settings.dept_id_list())
    if agent_ids:
        wanted = set(agent_ids)
        agents = [a for a in agents if a.id in wanted]

    run = ReportRun(
        day=report_day,
        status="running",
        trigger=trigger,
        agent_count=len(agents),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    digest_lines: list[str] = []
    for agent in agents:
        row = generate_one(db, agent=agent, day=report_day, run=run, upload=upload)
        if row.status == "done":
            try:
                metrics = json.loads(row.metrics_json or "{}")
            except json.JSONDecodeError:
                metrics = {}
            leads = (metrics.get("leads") or {}).get("total_open", "?")
            calls = (metrics.get("calls") or {}).get("count", "?")
            checked = (metrics.get("timeman") or {}).get("checked_in")
            digest_lines.append(
                f"• {row.agent_name}: check-in={'yes' if checked else 'no'}, "
                f"open leads={leads}, calls={calls}"
            )
        else:
            digest_lines.append(f"• {row.agent_name}: FAILED — {row.error[:120]}")

    run.status = "done"
    run.finished_at = datetime.now(tz)
    db.commit()
    db.refresh(run)

    if notify and digest_lines:
        try:
            deliver_digest(
                client,
                day=report_day.isoformat(),
                lines=digest_lines,
                pdf_note=f"Generated {run.agent_count} agent PDF(s).",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Digest notify failed: %s", exc)

    return run
