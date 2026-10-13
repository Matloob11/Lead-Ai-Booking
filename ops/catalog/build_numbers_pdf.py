"""Simple black-and-white PDF of Official WhatsApp numbers roster."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RAW = Path(__file__).with_name("_numbers_roster.raw")
OUT = Path(__file__).resolve().parents[2] / "Official-WhatsApp-Numbers-Roster.pdf"


def load_rows() -> list[dict]:
    text = RAW.read_text(encoding="utf-8", errors="replace")
    started = False
    lines = []
    for ln in text.splitlines():
        if ln.startswith("phone_number,"):
            started = True
        if not started:
            continue
        if ln.strip() == "PROBE_OK":
            break
        if ln.strip():
            lines.append(ln)
    return list(csv.DictReader(lines))


def status_of(r: dict) -> str:
    if r["is_active"] != "yes":
        return "inactive"
    if (r.get("agent_name") or "").strip():
        return "assigned"
    return "unassigned"


def main():
    rows = load_rows()
    rows = sorted(
        rows,
        key=lambda r: (
            0 if r["is_active"] == "yes" else 1,
            0 if (r.get("agent_name") or "").strip() else 1,
            (r.get("agent_name") or "").lower(),
            r["phone_number"],
        ),
    )
    active = sum(1 for r in rows if r["is_active"] == "yes")
    assigned = sum(1 for r in rows if r["is_active"] == "yes" and (r.get("agent_name") or "").strip())
    unassigned = active - assigned

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="Official WhatsApp Numbers Roster",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "T",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.black,
        spaceAfter=2,
    )
    sub = ParagraphStyle(
        "S",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.black,
        spaceAfter=6,
    )
    cell = ParagraphStyle(
        "C",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        textColor=colors.black,
        leading=9,
    )

    story = [
        Paragraph("Official WhatsApp Numbers Roster", title),
        Paragraph(
            f"Date: {date.today().isoformat()} &nbsp;|&nbsp; "
            f"Total: {len(rows)} &nbsp;|&nbsp; Active: {active} &nbsp;|&nbsp; "
            f"Assigned: {assigned} &nbsp;|&nbsp; Unassigned: {unassigned} &nbsp;|&nbsp; "
            f"Inactive: {len(rows) - active}",
            sub,
        ),
    ]

    data = [
        [
            Paragraph("<b>#</b>", cell),
            Paragraph("<b>Phone</b>", cell),
            Paragraph("<b>Label</b>", cell),
            Paragraph("<b>Agent</b>", cell),
            Paragraph("<b>Community</b>", cell),
            Paragraph("<b>Account</b>", cell),
            Paragraph("<b>Status</b>", cell),
        ]
    ]
    for i, r in enumerate(rows, start=1):
        st = status_of(r)
        data.append(
            [
                Paragraph(str(i), cell),
                Paragraph(r["phone_number"], cell),
                Paragraph((r.get("number_label") or "-").replace("&", "&amp;"), cell),
                Paragraph((r.get("agent_name") or "-").replace("&", "&amp;"), cell),
                Paragraph((r.get("community") or "-").replace("&", "&amp;"), cell),
                Paragraph((r.get("account") or "-").replace("&", "&amp;"), cell),
                Paragraph(st, cell),
            ]
        )

    table = Table(
        data,
        colWidths=[12 * mm, 32 * mm, 55 * mm, 50 * mm, 40 * mm, 28 * mm, 22 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Black &amp; white table from live Official inbox. "
            "Webhook: https://wa.srv1802669.hstgr.cloud/api/gateway/webhook/alots/",
            sub,
        )
    )
    doc.build(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
