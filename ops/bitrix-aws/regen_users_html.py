"""Rebuild agent-reports/bitrix-all-users.{html,json} from a JSON dump."""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "agent-reports"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "_users_live.json"
    rows = json.loads(src.read_text(encoding="utf-8"))
    by_id = {int(r["id"]): r for r in rows}
    rows = sorted(by_id.values(), key=lambda r: int(r["id"]))

    body_rows = []
    for r in rows:
        cls = "" if r["active"] else ' class="off"'
        needle = html.escape(f"{r['id']} {r['name'].lower()} {r['email'].lower()}")
        body_rows.append(
            "<tr{cls} data-s=\"{needle}\">"
            "<td>{id}</td><td>{name}</td><td>{email}</td>"
            "<td>{pos}</td><td>{active}</td></tr>".format(
                cls=cls,
                needle=needle,
                id=int(r["id"]),
                name=html.escape(str(r["name"])),
                email=html.escape(str(r["email"])),
                pos=html.escape(str(r.get("work_position") or "")),
                active="yes" if r["active"] else "no",
            )
        )

    active = sum(1 for r in rows if r["active"])
    inactive = len(rows) - active
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Bitrix Users</title>
  <style>
    body {{ font: 14px/1.4 system-ui, sans-serif; margin: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
    th {{ background: #f4f4f4; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    .off {{ opacity: 0.55; }}
    #q {{ padding: 8px; width: min(420px, 100%); margin-bottom: 12px; }}
  </style>
</head>
<body>
  <h1>Bitrix users ({len(rows)})</h1>
  <p>Active: {active} / Inactive: {inactive}</p>
  <input id="q" placeholder="Filter by name / id / email" oninput="filterRows()" />
  <table>
    <thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Position</th><th>Active</th></tr></thead>
    <tbody id="tb">
      {"".join(body_rows)}
    </tbody>
  </table>
  <script>
    function filterRows() {{
      const q = document.getElementById("q").value.toLowerCase();
      for (const tr of document.querySelectorAll("#tb tr")) {{
        tr.style.display = tr.dataset.s.includes(q) ? "" : "none";
      }}
    }}
  </script>
</body>
</html>
"""
    html_path = OUT_DIR / "bitrix-all-users.html"
    json_path = OUT_DIR / "bitrix-all-users.json"
    html_path.write_text(page, encoding="utf-8")
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {html_path}")
    print(f"wrote {json_path}")
    print(f"total={len(rows)} active={active} inactive={inactive}")


if __name__ == "__main__":
    main()
