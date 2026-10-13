#!/usr/bin/env python3
"""Build a simple white PDF of Official WhatsApp numbers + assignments.

Source: ops/catalog/_roster_raw.txt + _agents.txt (from live ops/wa.sh sql app).
API key is stack-wide (ALOTS_API_KEY), not per number — noted on the cover row.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "ops" / "catalog" / "_roster_raw.txt"
AGENTS = ROOT / "ops" / "catalog" / "_agents.txt"
DEST = ROOT / "files" / "briefs" / "Official-WA-Numbers-Assignments.pdf"
DEST_971 = ROOT / "files" / "briefs" / "Official-WA-971-Numbers.pdf"


def _esc(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _parse_psql_block(text: str, marker: str) -> list[list[str]]:
    if marker not in text:
        return []
    chunk = text.split(marker, 1)[1]
    for stop in ("====",):
        if stop in chunk[1:]:
            # cut at next ==== section
            nxt = chunk.find("====", 1)
            if nxt > 0:
                chunk = chunk[:nxt]
            break
    lines = [ln.rstrip() for ln in chunk.splitlines()]
    rows: list[list[str]] = []
    for ln in lines:
        if not ln.strip() or ln.strip().startswith("SET") or ln.strip().startswith("("):
            continue
        if re.match(r"^[\-\+ ]+$", ln):
            continue
        if "|" not in ln:
            continue
        # skip header-ish if first cell is phone_number / id / column_name
        cells = [c.strip() for c in ln.split("|")]
        if cells and cells[0] in {"phone_number", "id", "column_name", ""}:
            continue
        if cells and cells[0].startswith("-"):
            continue
        rows.append(cells)
    return rows


def load_agents() -> dict[int, str]:
    text = AGENTS.read_text(encoding="utf-8", errors="replace")
    out: dict[int, str] = {}
    for cells in _parse_psql_block("====X====\n" + text, "====X===="):
        if len(cells) < 2:
            continue
        try:
            aid = int(cells[0])
        except ValueError:
            continue
        name = cells[1].strip()
        if name:
            out[aid] = name
    return out


def load_numbers_and_assign() -> tuple[list[dict], dict[str, list[str]]]:
    text = RAW.read_text(encoding="utf-8", errors="replace")
    num_rows = _parse_psql_block(text, "====NUMBERS====")
    asg_rows = _parse_psql_block(text, "====ASSIGN====")
    numbers: list[dict] = []
    for cells in num_rows:
        if len(cells) < 8:
            continue
        numbers.append(
            {
                "phone": cells[0],
                "phone_number_id": cells[1],
                "waba_business_id": cells[2],
                "label": cells[3],
                "display_name": cells[4],
                "community": cells[5],
                "account": cells[6],
                "active": cells[7] in {"t", "true", "True", "1"},
            }
        )
    agents = load_agents()
    assign: dict[str, list[str]] = {}
    for cells in asg_rows:
        if len(cells) < 3:
            continue
        phone, aid_s, role = cells[0], cells[1], cells[2]
        try:
            aid = int(aid_s)
        except ValueError:
            continue
        name = agents.get(aid, f"agent#{aid}")
        assign.setdefault(phone, []).append(f"{name} ({role})")
    return numbers, assign


def write_pdf(
    *,
    phone_prefix: str = "",
    dest: Path | None = None,
    title_extra: str = "",
    exclude_coexistence: bool = False,
) -> Path:
    numbers, assign = load_numbers_and_assign()
    if phone_prefix:
        numbers = [n for n in numbers if str(n["phone"]).startswith(phone_prefix)]
    if exclude_coexistence:
        numbers = [
            n
            for n in numbers
            if "coexist" not in f"{n.get('community','')} {n.get('label','')} {n.get('display_name','')}".lower()
        ]
    out = dest or DEST
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "t",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=colors.black,
        spaceAfter=4,
        alignment=TA_LEFT,
    )
    body = ParagraphStyle(
        "b",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.black,
        leading=11,
    )
    cell = ParagraphStyle(
        "c",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        textColor=colors.black,
        leading=9,
    )

    doc = SimpleDocTemplate(
        str(out),
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    story = []
    heading = "A7 Official WhatsApp — Numbers & Assignments"
    if title_extra:
        heading = f"{heading} ({title_extra})"
    story.append(Paragraph(heading, title))
    story.append(
        Paragraph(
            f"Generated {date.today().isoformat()}. "
            + (f"Filter: numbers starting with <b>{_esc(phone_prefix)}</b>. " if phone_prefix else "")
            + ("Coexistence numbers excluded. " if exclude_coexistence else "")
            + "Columns you can reuse elsewhere: Name, Number, Phone Number ID, WABA Business ID. "
            "<b>API key is shared</b> for the whole Official stack "
            "(<font face='Courier'>ALOTS_API_KEY</font> in server "
            "<font face='Courier'>/opt/a7-wa/deploy/.env</font>) — not stored per number. "
            "Meta Graph token (if used) is <font face='Courier'>META_GRAPH_ACCESS_TOKEN</font>.",
            body,
        )
    )
    story.append(Spacer(1, 4 * mm))

    header = [
        Paragraph("<b>Name (assigned)</b>", cell),
        Paragraph("<b>Number</b>", cell),
        Paragraph("<b>Phone Number ID</b>", cell),
        Paragraph("<b>WABA Business ID</b>", cell),
        Paragraph("<b>Account</b>", cell),
        Paragraph("<b>Label / Community</b>", cell),
        Paragraph("<b>Active</b>", cell),
        Paragraph("<b>API Key</b>", cell),
    ]
    data = [header]
    for n in numbers:
        phone = n["phone"]
        names = assign.get(phone) or []
        name = ", ".join(names) if names else (n["label"] or n["display_name"] or "— unassigned —")
        label_bits = " / ".join(x for x in [n["label"], n["community"]] if x)
        data.append(
            [
                Paragraph(_esc(name), cell),
                Paragraph(_esc(phone), cell),
                Paragraph(_esc(n["phone_number_id"]), cell),
                Paragraph(_esc(n["waba_business_id"]), cell),
                Paragraph(_esc(n["account"] or "—"), cell),
                Paragraph(_esc(label_bits or "—"), cell),
                Paragraph("Yes" if n["active"] else "No", cell),
                Paragraph("Shared ALOTS_API_KEY", cell),
            ]
        )

    widths = [55 * mm, 28 * mm, 32 * mm, 32 * mm, 22 * mm, 45 * mm, 12 * mm, 32 * mm]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#333333")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 3 * mm))
    active_n = sum(1 for n in numbers if n["active"])
    assigned_n = sum(1 for n in numbers if assign.get(n["phone"]))
    story.append(
        Paragraph(
            f"Total numbers: {len(numbers)} · Active: {active_n} · With assignment: {assigned_n} · "
            f"Unassigned active: {sum(1 for n in numbers if n['active'] and not assign.get(n['phone']))}",
            body,
        )
    )
    doc.build(story)
    return out


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "971" in args:
        path = write_pdf(
            phone_prefix="971",
            dest=DEST_971,
            title_extra="+971 UAE only"
            + (" · no coexistence" if "no-coexist" in args else ""),
            exclude_coexistence="no-coexist" in args,
        )
    else:
        path = write_pdf()
    print(f"wrote {path} ({path.stat().st_size} bytes)")
