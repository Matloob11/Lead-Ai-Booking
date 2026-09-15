"""Dump all Bitrix users (id + name) to HTML/JSON pages in repo root."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "agent-reports" / ".env")
load_dotenv(ROOT / ".env")

import sys

sys.path.insert(0, str(ROOT / "agent-reports" / "backend"))
from app.bitrix.client import BitrixClient  # noqa: E402


def display_name(user: dict) -> str:
    parts = [str(user.get("NAME") or "").strip(), str(user.get("LAST_NAME") or "").strip()]
    name = " ".join(p for p in parts if p).strip()
    return name or str(user.get("EMAIL") or user.get("LOGIN") or user.get("ID") or "")


def main() -> None:
    webhook = (os.getenv("AGENT_REPORT_BITRIX_WEBHOOK") or "").strip()
    if not webhook:
        raise SystemExit("AGENT_REPORT_BITRIX_WEBHOOK missing")

    client = BitrixClient(webhook)
    active = client.call_list("user.get", {"FILTER": {"ACTIVE": "true"}, "ADMIN_MODE": True})
    inactive = client.call_list("user.get", {"FILTER": {"ACTIVE": "false"}, "ADMIN_MODE": True})

    by_id: dict[str, dict] = {}
    for user in active + inactive:
        by_id[str(user.get("ID"))] = user

    users = sorted(by_id.values(), key=lambda u: int(u.get("ID") or 0))
    rows = []
    for user in users:
        rows.append(
            {
                "id": int(user.get("ID") or 0),
                "name": display_name(user),
                "email": str(user.get("EMAIL") or ""),
                "active": str(user.get("ACTIVE") or "").lower() in ("1", "true", "y", "yes"),
                "work_position": str(user.get("WORK_POSITION") or ""),
            }
        )

    html_path = ROOT / "bitrix-all-users.html"
    json_path = ROOT / "bitrix-all-users.json"

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
                id=r["id"],
                name=html.escape(r["name"]),
                email=html.escape(r["email"]),
                pos=html.escape(r["work_position"]),
                active="yes" if r["active"] else "no",
            )
        )

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
  <p>Active: {sum(1 for r in rows if r["active"])} · Inactive: {sum(1 for r in rows if not r["active"])}</p>
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
    html_path.write_text(page, encoding="utf-8")
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {html_path}")
    print(f"wrote {json_path}")
    print(f"count={len(rows)}")


if __name__ == "__main__":
    main()
