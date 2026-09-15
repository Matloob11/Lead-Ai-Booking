"""Write a simple PDF of Official +971 numbers and who holds them.

Rows are the live Official catalog as of the last `ops/wa.sh sql app` pull
in this file's GENERATED stamp. Re-query before regenerating if the roster
may have changed.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "files" / "briefs" / "Official-971-Numbers.pdf"
GENERATED = "2026-09-10"

# phone, active, label, community, account, agent (empty = unassigned)
ROWS: list[tuple[str, bool, str, str, str, str]] = [
    ("971507563104", True, "Property Consultant", "coexistence", "Dubai07WBX", ""),
    ("971524077268", True, "minahil sanaullah", "International city", "A7GroupWBX", "minahil sanaullah"),
    ("971524473103", True, "Mehreen", "Damac Hills 2", "A7GroupWBX", "Mehreen"),
    ("971524492026", True, "Asma Aslam", "International city", "A7GroupWBX", "Asma Aslam"),
    ("971525531548", False, "Dubai05WBX", "coexistence", "Dubai05WBX", ""),
    ("971527514497", True, "shahid", "coexistence", "Dubai02WBX", ""),
    ("971529312577", True, "Abdul", "coexistence", "Dubai06WBX", ""),
    ("971543752608", True, "kanwal", "coexistence", "Dubai08WBX", ""),
    ("971555306149", True, "eman Fazal", "Arabian Ranchers 3", "A7GroupWBX", "eman Fazal"),
    ("971555497521", True, "Khazeema", "Arabian Ranchers 3", "A7GroupWBX", "Khazeema"),
    ("971555689029", True, "nimra akbar", "Damac Hills 2", "A7GroupWBX", "nimra akbar"),
    ("971555716422", True, "Aila Shehzadi", "Villa Nova", "A7GroupWBX", "Aila Shehzadi"),
    ("971555817694", True, "Fozia razzaq", "International city", "A7GroupWBX", "Fozia razzaq"),
    ("971555832603", True, "uzma jamshaid", "Damac Lagoon, Costa Brava, Portfino", "A7GroupWBX", "uzma jamshaid"),
    ("971555850765", True, "Warda Hassan", "Damac Hills 2", "A7GroupWBX", "Warda Hassan"),
    ("971555956439", True, "Areeba", "Arabian Ranchers 3", "A7GroupWBX", "Areeba"),
    ("971556037342", True, "Hassan T.L", "Head Telesale", "A7GroupWBX", "Hassan T.L"),
    ("971556059331", True, "Rana Muhammad Hussnain Ali", "Head Telesale", "A7GroupWBX", "Rana Muhammad Hussnain Ali"),
    ("971556082710", True, "Ruqia Faisal", "Damac Lagoon", "A7GroupWBX", "Ruqia Faisal"),
    ("971556354628", True, "Javeria bibi", "Mudon Al Ranim", "A7GroupWBX", ""),
    ("971556441831", True, "Talha Sheikh", "", "A7GroupWBX", "Talha Sheikh"),
    ("971556748730", True, "Blue Brick", "", "A7GroupWBX", ""),
    ("971556829046", True, "Blue Brick", "", "A7GroupWBX", ""),
    ("971557327268", True, "Blue Brick", "", "A7GroupWBX", ""),
    ("971557466914", True, "tehreem Ijaaz", "the acers", "A7GroupWBX", "tehreem Ijaaz"),
    ("971558448678", True, "Dubai03WBX", "coexistence", "Dubai03WBX", ""),
    ("971559193588", True, "Irum Yasin", "The valley", "A7GroupWBX", "Irum Yasin"),
    ("971559430556", True, "shareen Shahid", "International city", "A7GroupWBX", "shareen Shahid"),
    ("971559477395", True, "Farhat Shahid", "International city", "A7GroupWBX", "Farhat Shahid"),
    ("971559481572", True, "mehnaz", "Damac Hills 2", "A7GroupWBX", "mehnaz"),
    ("971559632895", True, "SAPNA", "coexistence", "A7GroupWBX", "SAPNA"),
    ("971559668904", True, "esha ghazi", "Damac Hills 2", "A7GroupWBX", "Esha Ghazi"),
    ("971559759052", True, "NABIHA", "", "Dubai10WBX", "NABIHA"),
    ("971559783176", True, "Fameeda", "coexistence", "Dubai10WBX", ""),
    ("971559791401", True, "Dubai04WBX", "coexistence", "Dubai04WBX", ""),
    ("971563523109", False, "Dubai01WBX", "coexistence", "Dubai01WBX", ""),
    ("971564821835", True, "Real Estate Consultant", "coexistence", "Dubai09WBX", ""),
]


def _esc(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _table(data: list[list], widths: list) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#000000")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
            ]
        )
    )
    return table


def write_pdf() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    assigned = [r for r in ROWS if r[5]]
    remaining = [r for r in ROWS if not r[5]]
    active = [r for r in ROWS if r[1]]
    inactive = [r for r in ROWS if not r[1]]
    remaining_active = [r for r in remaining if r[1]]

    doc = SimpleDocTemplate(
        str(DEST),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Official 971 Numbers",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, spaceAfter=4)
    heading = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=11, spaceBefore=10, spaceAfter=6)
    sub = ParagraphStyle(
        "S",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#333333"),
        spaceAfter=8,
        leading=12,
    )
    cell = ParagraphStyle("C", parent=styles["Normal"], fontSize=8, leading=10)
    head = ParagraphStyle("H", parent=cell, fontName="Helvetica-Bold")

    story = [
        Paragraph("Official +971 WhatsApp numbers", title),
        Paragraph(
            f"Live Official catalog &nbsp;&nbsp;·&nbsp;&nbsp; {GENERATED}<br/>"
            f"Total {len(ROWS)} &nbsp;&nbsp;·&nbsp;&nbsp; Active {len(active)} "
            f"&nbsp;&nbsp;·&nbsp;&nbsp; Inactive {len(inactive)}<br/>"
            f"Assigned to an agent {len(assigned)} &nbsp;&nbsp;·&nbsp;&nbsp; "
            f"Unassigned {len(remaining)} ({len(remaining_active)} active, "
            f"{len(remaining) - len(remaining_active)} inactive)",
            sub,
        ),
        Paragraph("Assigned", heading),
    ]

    assigned_data = [[
        Paragraph("#", head),
        Paragraph("Number", head),
        Paragraph("Assigned to", head),
        Paragraph("Community", head),
        Paragraph("Account", head),
    ]]
    for i, (phone, _active, _label, community, account, agent) in enumerate(assigned, start=1):
        assigned_data.append([
            Paragraph(str(i), cell),
            Paragraph(_esc(phone), cell),
            Paragraph(_esc(agent), cell),
            Paragraph(_esc(community), cell),
            Paragraph(_esc(account), cell),
        ])
    story.append(_table(assigned_data, [12 * mm, 32 * mm, 52 * mm, 52 * mm, 32 * mm]))

    story.append(Paragraph("Unassigned (still available or unused)", heading))
    story.append(
        Paragraph(
            "These have no active NumberAssignment. A label can still show a name "
            "(for example Javeria bibi) without the number being assigned.",
            sub,
        )
    )

    left_data = [[
        Paragraph("#", head),
        Paragraph("Number", head),
        Paragraph("Status", head),
        Paragraph("Label", head),
        Paragraph("Community", head),
        Paragraph("Account", head),
    ]]
    for i, (phone, is_active, label, community, account, _agent) in enumerate(remaining, start=1):
        left_data.append([
            Paragraph(str(i), cell),
            Paragraph(_esc(phone), cell),
            Paragraph("Active" if is_active else "Inactive", cell),
            Paragraph(_esc(label), cell),
            Paragraph(_esc(community), cell),
            Paragraph(_esc(account), cell),
        ])
    story.append(_table(left_data, [12 * mm, 30 * mm, 20 * mm, 42 * mm, 38 * mm, 28 * mm]))
    story.append(Spacer(1, 8))
    doc.build(story)


def main() -> None:
    write_pdf()
    assigned = sum(1 for r in ROWS if r[5])
    remaining = [r for r in ROWS if not r[5]]
    print(f"total={len(ROWS)}")
    print(f"active={sum(1 for r in ROWS if r[1])}")
    print(f"inactive={sum(1 for r in ROWS if not r[1])}")
    print(f"assigned={assigned}")
    print(f"unassigned={len(remaining)}")
    print(f"unassigned_active={sum(1 for r in remaining if r[1])}")
    print(f"wrote {DEST}")


if __name__ == "__main__":
    main()
