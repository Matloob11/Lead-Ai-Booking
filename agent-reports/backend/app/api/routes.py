from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bitrix.agents import list_sales_ts_agents
from ..bitrix.client import BitrixClient, BitrixError
from ..bitrix.metrics import collect_agent_day
from ..config import get_settings
from ..db import get_db
from ..models import AgentReport, ReportRun
from ..reports.pipeline import generate_one, run_daily_reports

router = APIRouter(prefix="/api")


def _client() -> BitrixClient:
    settings = get_settings()
    if not settings.webhook_base():
        raise HTTPException(status_code=503, detail="AGENT_REPORT_BITRIX_WEBHOOK is not configured")
    return BitrixClient(settings.webhook_base())


class GenerateBody(BaseModel):
    day: str | None = Field(None, description="YYYY-MM-DD Dubai")
    agent_ids: list[int] | None = None
    notify: bool = False
    upload: bool = False


@router.get("/agents")
def api_agents():
    settings = get_settings()
    try:
        agents = list_sales_ts_agents(_client(), settings.dept_id_list())
    except BitrixError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "count": len(agents),
        "dept_ids": settings.dept_id_list(),
        "agents": [a.as_dict() for a in agents],
    }


@router.get("/agents/{agent_id}/day")
def api_agent_day(
    agent_id: int,
    day: str | None = Query(None, description="YYYY-MM-DD in Asia/Dubai; default today"),
):
    settings = get_settings()
    tz = ZoneInfo(settings.agent_report_tz)
    if day:
        try:
            report_day = date.fromisoformat(day)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD") from exc
    else:
        report_day = datetime.now(tz).date()

    client = _client()
    try:
        agents = list_sales_ts_agents(client, settings.dept_id_list())
    except BitrixError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    agent = next((a for a in agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not in Sales/TS scope")

    try:
        snap = collect_agent_day(
            client,
            agent_id=agent.id,
            agent_name=agent.name,
            day=report_day,
            tz_name=settings.agent_report_tz,
            owner_data_entity_type_id=settings.agent_report_owner_data_entity_type_id,
        )
    except BitrixError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return snap.as_dict()


@router.get("/reports")
def api_list_reports(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    runs = db.scalars(select(ReportRun).order_by(ReportRun.id.desc()).limit(limit)).all()
    out = []
    for run in runs:
        reports = db.scalars(
            select(AgentReport).where(AgentReport.run_id == run.id).order_by(AgentReport.agent_name)
        ).all()
        out.append(
            {
                "id": run.id,
                "day": run.day.isoformat(),
                "status": run.status,
                "trigger": run.trigger,
                "agent_count": run.agent_count,
                "error": run.error,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "reports": [
                    {
                        "id": r.id,
                        "agent_id": r.agent_id,
                        "agent_name": r.agent_name,
                        "status": r.status,
                        "has_pdf": bool(r.pdf_path),
                        "error": r.error,
                    }
                    for r in reports
                ],
            }
        )
    return {"count": len(out), "runs": out}


@router.get("/reports/items/{report_id}")
def api_report_item(report_id: int, db: Session = Depends(get_db)):
    row = db.get(AgentReport, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        metrics = json.loads(row.metrics_json or "{}")
    except json.JSONDecodeError:
        metrics = {}
    return {
        "id": row.id,
        "run_id": row.run_id,
        "agent_id": row.agent_id,
        "agent_name": row.agent_name,
        "day": row.day.isoformat(),
        "status": row.status,
        "ai_summary": row.ai_summary,
        "metrics": metrics,
        "pdf_path": row.pdf_path,
        "disk_file_id": row.disk_file_id,
        "error": row.error,
    }


@router.get("/reports/items/{report_id}/pdf")
def api_report_pdf(report_id: int, db: Session = Depends(get_db)):
    row = db.get(AgentReport, report_id)
    if not row or not row.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")
    path = Path(row.pdf_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"agent-{row.agent_id}-{row.day}.pdf",
    )


@router.post("/reports/generate")
def api_generate(body: GenerateBody, db: Session = Depends(get_db)):
    settings = get_settings()
    tz = ZoneInfo(settings.agent_report_tz)
    if body.day:
        try:
            report_day = date.fromisoformat(body.day)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD") from exc
    else:
        report_day = datetime.now(tz).date()

    if body.agent_ids and len(body.agent_ids) == 1:
        client = _client()
        agents = list_sales_ts_agents(client, settings.dept_id_list())
        agent = next((a for a in agents if a.id == body.agent_ids[0]), None)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not in Sales/TS scope")
        run = ReportRun(
            day=report_day,
            status="running",
            trigger="single",
            agent_count=1,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        row = generate_one(
            db,
            agent=agent,
            day=report_day,
            run=run,
            upload=body.upload,
        )
        run.status = "done"
        run.finished_at = datetime.now(tz)
        db.commit()
        return {
            "run_id": run.id,
            "day": report_day.isoformat(),
            "report_id": row.id,
            "status": row.status,
            "error": row.error,
        }

    run = run_daily_reports(
        db,
        day=report_day,
        trigger="manual",
        agent_ids=body.agent_ids,
        notify=body.notify,
        upload=body.upload,
    )
    return {
        "run_id": run.id,
        "day": run.day.isoformat(),
        "status": run.status,
        "agent_count": run.agent_count,
    }
