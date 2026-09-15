from datetime import date
from pathlib import Path

from app.bitrix.metrics import AgentDaySnapshot, CallStats, LeadBook, TaskStats, TimemanSnapshot
from app.reports.ai_summary import _fallback_summary
from app.reports.pdf import build_pdf_bytes, write_pdf


def _snap():
    return AgentDaySnapshot(
        agent_id=99,
        agent_name="Test Agent",
        day=date(2026, 8, 21),
        timezone="Asia/Dubai",
        timeman=TimemanSnapshot(status="OPENED", checked_in=True),
        leads=LeadBook(classic_open=10, owner_data_open=2, new_classic_today=1),
        tasks=TaskStats(open_count=3, completed_today=1),
        calls=CallStats(count=4, talk_seconds=600),
    )


def test_fallback_summary_contains_name():
    text = _fallback_summary(_snap())
    assert "Test Agent" in text
    assert "4" in text


def test_pdf_bytes_non_empty():
    raw = build_pdf_bytes(_snap(), "Agent focused on follow-ups today.")
    assert raw[:4] == b"%PDF"
    assert len(raw) > 500


def test_write_pdf(tmp_path: Path):
    path = tmp_path / "t.pdf"
    write_pdf(_snap(), "Summary text", path)
    assert path.is_file()
    assert path.stat().st_size > 500
