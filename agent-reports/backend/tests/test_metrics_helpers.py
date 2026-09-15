from datetime import date
from zoneinfo import ZoneInfo

from app.bitrix.metrics import AgentDaySnapshot, dubai_day_bounds


def test_dubai_day_bounds():
    start, end = dubai_day_bounds(date(2026, 8, 21), "Asia/Dubai")
    assert start.tzinfo == ZoneInfo("Asia/Dubai")
    assert (end - start).days == 1
    assert start.hour == 0


def test_snapshot_totals():
    snap = AgentDaySnapshot(
        agent_id=1,
        agent_name="Test",
        day=date(2026, 8, 21),
        timezone="Asia/Dubai",
    )
    snap.leads.classic_open = 3
    snap.leads.owner_data_open = 2
    snap.calls.talk_seconds = 150
    data = snap.as_dict()
    assert data["leads"]["total_open"] == 5
    assert data["calls"]["talk_minutes"] == 2.5
