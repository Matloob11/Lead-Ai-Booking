"""Collect one agent's Bitrix activity for a Dubai calendar day."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .client import BitrixClient, BitrixError


class TimemanSnapshot(BaseModel):
    status: str = ""
    checked_in: bool = False
    time_start: str | None = None
    time_finish: str | None = None
    duration_seconds: int | None = None
    raw_note: str = ""


class CallStats(BaseModel):
    count: int = 0
    talk_seconds: int = 0

    @property
    def talk_minutes(self) -> float:
        return round(self.talk_seconds / 60.0, 1)


class TaskStats(BaseModel):
    open_count: int = 0
    completed_today: int = 0


class LeadBook(BaseModel):
    classic_open: int = 0
    owner_data_open: int = 0
    new_classic_today: int = 0
    new_owner_data_today: int = 0

    @property
    def total_open(self) -> int:
        return self.classic_open + self.owner_data_open


class AgentDaySnapshot(BaseModel):
    agent_id: int
    agent_name: str
    day: date
    timezone: str
    timeman: TimemanSnapshot = Field(default_factory=TimemanSnapshot)
    leads: LeadBook = Field(default_factory=LeadBook)
    tasks: TaskStats = Field(default_factory=TaskStats)
    calls: CallStats = Field(default_factory=CallStats)
    errors: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["leads"]["total_open"] = self.leads.total_open
        data["calls"]["talk_minutes"] = self.calls.talk_minutes
        return data


def dubai_day_bounds(day: date, tz_name: str = "Asia/Dubai") -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def _bitrix_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _safe(errors: list[str], label: str, fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}: {exc}")
        return None


def collect_timeman(client: BitrixClient, user_id: int, day: date | None = None, tz_name: str = "Asia/Dubai") -> TimemanSnapshot:
    try:
        raw = client.call("timeman.status", {"USER_ID": user_id}) or {}
    except BitrixError as exc:
        return TimemanSnapshot(raw_note=str(exc))
    if not isinstance(raw, dict):
        return TimemanSnapshot()
    status = str(raw.get("STATUS") or raw.get("status") or "")
    time_start = str(raw.get("TIME_START") or "") or None
    time_finish = str(raw.get("TIME_FINISH") or "") or None
    status_u = status.upper()
    live = status_u in {"OPENED", "PAUSED", "EXPIRED"}
    on_day = False
    if day and time_start:
        try:
            # Bitrix returns ISO with offset, e.g. 2024-12-14T14:16:03+04:00
            started = datetime.fromisoformat(time_start)
            on_day = started.astimezone(ZoneInfo(tz_name)).date() == day
        except ValueError:
            on_day = False
    checked = live or on_day
    duration = None
    if str(raw.get("DURATION") or "").isdigit():
        duration = int(raw["DURATION"])
    return TimemanSnapshot(
        status=status,
        checked_in=checked,
        time_start=time_start,
        time_finish=time_finish,
        duration_seconds=duration,
        raw_note="" if checked else "No check-in recorded for this day",
    )


def _count_leads(
    client: BitrixClient,
    *,
    assigned_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    only_open: bool = False,
) -> int:
    filt: dict[str, Any] = {"ASSIGNED_BY_ID": assigned_id}
    if only_open:
        filt["!STATUS_ID"] = ["CONVERTED", "JUNK"]
    if date_from:
        filt[">=DATE_CREATE"] = _bitrix_dt(date_from)
    if date_to:
        filt["<DATE_CREATE"] = _bitrix_dt(date_to)
    return client.call_total("crm.lead.list", {"filter": filt, "select": ["ID"], "start": 0})


def _count_owner_data(
    client: BitrixClient,
    *,
    entity_type_id: int,
    assigned_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    filt: dict[str, Any] = {"assignedById": assigned_id}
    if date_from:
        filt[">=createdTime"] = _bitrix_dt(date_from)
    if date_to:
        filt["<createdTime"] = _bitrix_dt(date_to)
    return client.call_total(
        "crm.item.list",
        {
            "entityTypeId": entity_type_id,
            "filter": filt,
            "select": ["id"],
            "start": 0,
        },
    )


def collect_calls(client: BitrixClient, user_id: int, day: date, tz_name: str) -> CallStats:
    start, end = dubai_day_bounds(day, tz_name)
    filt = {
        "PORTAL_USER_ID": user_id,
        ">=CALL_START_DATE": _bitrix_dt(start),
        "<CALL_START_DATE": _bitrix_dt(end),
    }
    rows = client.call_list("voximplant.statistic.get", {"FILTER": filt})
    talk = 0
    for row in rows:
        try:
            talk += int(row.get("CALL_DURATION") or row.get("callDuration") or 0)
        except (TypeError, ValueError):
            continue
    return CallStats(count=len(rows), talk_seconds=talk)


def collect_tasks(client: BitrixClient, user_id: int, day: date, tz_name: str) -> TaskStats:
    start, end = dubai_day_bounds(day, tz_name)
    open_rows = client.call_list(
        "tasks.task.list",
        {
            "filter": {"RESPONSIBLE_ID": user_id, "!REAL_STATUS": 5},
            "select": ["ID"],
        },
    )
    done_rows = client.call_list(
        "tasks.task.list",
        {
            "filter": {
                "RESPONSIBLE_ID": user_id,
                "REAL_STATUS": 5,
                ">=CLOSED_DATE": _bitrix_dt(start),
                "<CLOSED_DATE": _bitrix_dt(end),
            },
            "select": ["ID"],
        },
    )
    return TaskStats(open_count=len(open_rows), completed_today=len(done_rows))


def collect_agent_day(
    client: BitrixClient,
    *,
    agent_id: int,
    agent_name: str,
    day: date,
    tz_name: str = "Asia/Dubai",
    owner_data_entity_type_id: int = 1042,
) -> AgentDaySnapshot:
    errors: list[str] = []
    start, end = dubai_day_bounds(day, tz_name)

    timeman = _safe(
        errors, "timeman", lambda: collect_timeman(client, agent_id, day=day, tz_name=tz_name)
    ) or TimemanSnapshot()

    classic_open = _safe(
        errors,
        "leads_open",
        lambda: _count_leads(client, assigned_id=agent_id, only_open=True),
    )
    classic_new = _safe(
        errors,
        "leads_new",
        lambda: _count_leads(client, assigned_id=agent_id, date_from=start, date_to=end),
    )
    od_open = _safe(
        errors,
        "owner_data_open",
        lambda: _count_owner_data(
            client, entity_type_id=owner_data_entity_type_id, assigned_id=agent_id
        ),
    )
    od_new = _safe(
        errors,
        "owner_data_new",
        lambda: _count_owner_data(
            client,
            entity_type_id=owner_data_entity_type_id,
            assigned_id=agent_id,
            date_from=start,
            date_to=end,
        ),
    )
    leads = LeadBook(
        classic_open=int(classic_open or 0),
        owner_data_open=int(od_open or 0),
        new_classic_today=int(classic_new or 0),
        new_owner_data_today=int(od_new or 0),
    )

    tasks = _safe(errors, "tasks", lambda: collect_tasks(client, agent_id, day, tz_name)) or TaskStats()
    calls = _safe(errors, "calls", lambda: collect_calls(client, agent_id, day, tz_name)) or CallStats()

    return AgentDaySnapshot(
        agent_id=agent_id,
        agent_name=agent_name,
        day=day,
        timezone=tz_name,
        timeman=timeman,
        leads=leads,
        tasks=tasks,
        calls=calls,
        errors=errors,
    )
