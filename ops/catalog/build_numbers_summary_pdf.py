"""One-page black-and-white quantity summary for Official WhatsApp numbers."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

RAW = Path(__file__).with_name("_numbers_roster.raw")
OUT = Path(__file__).resolve().parents[2] / "Official-WhatsApp-Numbers-Summary.pdf"


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


def region(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("44"):
        return "UK"
    if digits.startswith("971"):
        return "UAE"
    return "Other"


def main():
    rows = load_rows()
    active = [r for r in rows if r["is_active"] == "yes"]

    def count(reg: str | None = None, assigned: bool | None = None) -> int:
        n = 0
        for r in active:
            if reg and region(r["phone_number"]) != reg:
                continue
            has = bool((r.get("agent_name") or "").strip())
            if assigned is True and not has:
                continue
            if assigned is False and has:
                continue
            n += 1
        return n

    uk = count("UK")
    uae = count("UAE")
    assigned = count(assigned=True)
    unassigned = count(assigned=False)
    total = len(active)

    c = canvas.Canvas(str(OUT), pagesize=A4)
    width, height = A4
    c.setTitle("Official WhatsApp Numbers - Quantity Summary")

    y = height - 28 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "Official WhatsApp Numbers")
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, y, f"Quantity summary  |  {date.today().isoformat()}")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2, y, "Active numbers only (inactive excluded)")

    # Table box
    table_top = y - 14 * mm
    row_h = 12 * mm
    col1_x = 40 * mm
    col2_x = 130 * mm
    table_w = 130 * mm
    rows_data = [
        ("TOTAL (active)", str(total)),
        ("UK (+44)", str(uk)),
        ("UAE (+971)", str(uae)),
        ("Assigned", str(assigned)),
        ("Unassigned (free)", str(unassigned)),
    ]
    table_h = row_h * (len(rows_data) + 1)

    # Outer border
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.2)
    c.rect(col1_x, table_top - table_h, table_w, table_h, stroke=1, fill=0)

    # Header
    c.setLineWidth(0.8)
    c.line(col1_x, table_top - row_h, col1_x + table_w, table_top - row_h)
    c.line(col2_x, table_top, col2_x, table_top - table_h)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col1_x + 4 * mm, table_top - 7.5 * mm, "Category")
    c.drawRightString(col1_x + table_w - 4 * mm, table_top - 7.5 * mm, "Quantity")

    c.setFont("Helvetica", 12)
    for i, (label, value) in enumerate(rows_data):
        y_line = table_top - row_h * (i + 1)
        c.line(col1_x, y_line - row_h, col1_x + table_w, y_line - row_h)
        text_y = y_line - 7.5 * mm
        if i == 0:
            c.setFont("Helvetica-Bold", 12)
        else:
            c.setFont("Helvetica", 12)
        c.drawString(col1_x + 4 * mm, text_y, label)
        c.setFont("Helvetica-Bold", 14)
        c.drawRightString(col1_x + table_w - 4 * mm, text_y, value)

    # UK / UAE split note under table
    note_y = table_top - table_h - 16 * mm
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        width / 2,
        note_y,
        f"UK: {uk}  (assigned {count('UK', True)}, unassigned {count('UK', False)})",
    )
    c.drawCentredString(
        width / 2,
        note_y - 6 * mm,
        f"UAE: {uae}  (assigned {count('UAE', True)}, unassigned {count('UAE', False)})",
    )
    c.setFont("Helvetica", 8)
    c.drawCentredString(
        width / 2,
        note_y - 16 * mm,
        f"Inactive numbers not shown: {len(rows) - total}",
    )

    c.showPage()
    c.save()
    print(f"wrote {OUT}")
    print(f"total={total} uk={uk} uae={uae} assigned={assigned} unassigned={unassigned}")


if __name__ == "__main__":
    main()
