"""Fetch Bitrix users via BITRIX_WEBHOOK_BASE and write a simple PDF list."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "agent-reports" / "backend"))
from app.bitrix.client import BitrixClient  # noqa: E402

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _name(user: dict) -> str:
    parts = [str(user.get("NAME") or "").strip(), str(user.get("LAST_NAME") or "").strip()]
    name = " ".join(p for p in parts if p).strip()
    return name or str(user.get("LOGIN") or "")


def _esc(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _dept_names_from(webhook: str) -> dict[int, str]:
    client = BitrixClient(webhook)
    rows = client.call("department.get") or []
    if isinstance(rows, dict):
        rows = rows.get("result") or list(rows.values())
    out: dict[int, str] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            out[int(row["ID"])] = str(row.get("NAME") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _dept_names() -> dict[int, str]:
    candidates = [
        os.getenv("AGENT_REPORT_BITRIX_WEBHOOK"),
        os.getenv("BITRIX_WEBHOOK_BASE"),
        os.getenv("BITRIX_TELEPHONY_WEBHOOK_URL"),
    ]
    last_error = None
    for raw in candidates:
        webhook = (raw or "").strip()
        if not webhook:
            continue
        try:
            names = _dept_names_from(webhook)
            if names:
                return names
        except Exception as exc:  # noqa: BLE001 — try the next inbound webhook
            last_error = exc
    if last_error:
        raise last_error
    return {}


def _user_departments(user: dict, names: dict[int, str]) -> str:
    raw = user.get("UF_DEPARTMENT") or []
    if not isinstance(raw, list):
        raw = [raw]
    seen: list[str] = []
    for item in raw:
        try:
            dept_id = int(item)
        except (TypeError, ValueError):
            continue
        label = names.get(dept_id) or str(dept_id)
        if label and label not in seen:
            seen.append(label)
    return ", ".join(seen)


def fetch_users(webhook: str) -> list[dict]:
    client = BitrixClient(webhook)
    names = _dept_names()
    active = client.call_list("user.get", {"FILTER": {"ACTIVE": "true"}, "ADMIN_MODE": True})
    inactive = client.call_list("user.get", {"FILTER": {"ACTIVE": "false"}, "ADMIN_MODE": True})
    by_id: dict[str, dict] = {}
    for user in active + inactive:
        by_id[str(user.get("ID"))] = user
    rows = []
    for user in sorted(by_id.values(), key=lambda u: int(u.get("ID") or 0)):
        rows.append(
            {
                "id": str(user.get("ID") or ""),
                "name": _name(user),
                "email": str(user.get("EMAIL") or ""),
                "department": _user_departments(user, names),
                "active": str(user.get("ACTIVE") or "").lower() in ("1", "true", "y", "yes"),
            }
        )
    return rows


def write_pdf(rows: list[dict], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Bitrix Users",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, spaceAfter=4)
    sub = ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#333333"), spaceAfter=10)
    cell = ParagraphStyle("C", parent=styles["Normal"], fontSize=7.5, leading=10)
    head = ParagraphStyle("H", parent=cell, fontName="Helvetica-Bold")

    active = sum(1 for r in rows if r["active"])
    inactive = len(rows) - active
    story = [
        Paragraph("Bitrix Users", title),
        Paragraph(
            f"Total {len(rows)} users &nbsp;&nbsp;·&nbsp;&nbsp; Active {active} &nbsp;&nbsp;·&nbsp;&nbsp; Inactive {inactive}",
            sub,
        ),
    ]

    data = [[
        Paragraph("#", head),
        Paragraph("Bitrix ID", head),
        Paragraph("Name", head),
        Paragraph("Email", head),
        Paragraph("Department", head),
    ]]
    for i, row in enumerate(rows, start=1):
        data.append([
            Paragraph(str(i), cell),
            Paragraph(_esc(row["id"]), cell),
            Paragraph(_esc(row["name"]), cell),
            Paragraph(_esc(row["email"]), cell),
            Paragraph(_esc(row["department"]), cell),
        ])

    table = Table(data, colWidths=[12 * mm, 22 * mm, 42 * mm, 58 * mm, 52 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#000000")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))
    doc.build(story)


def main() -> None:
    webhook = (os.getenv("BITRIX_WEBHOOK_BASE") or "").strip()
    if not webhook:
        raise SystemExit("BITRIX_WEBHOOK_BASE missing from .env")
    rows = fetch_users(webhook)
    dest = ROOT / "files" / "briefs" / "Bitrix-Users.pdf"
    write_pdf(rows, dest)
    print(f"total={len(rows)}")
    print(f"active={sum(1 for r in rows if r['active'])}")
    print(f"inactive={sum(1 for r in rows if not r['active'])}")
    print(f"with_department={sum(1 for r in rows if r['department'])}")
    depts = sorted({r["department"] for r in rows if r["department"]})
    print("departments", len(depts))
    for name in depts:
        print(f"  {name}")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
