#!/usr/bin/env python3
"""Install /agent-reports/ proxy into the HTTPS server block of a7-wa.conf."""
from __future__ import annotations

import re
from pathlib import Path

CONF = Path("/etc/nginx/conf.d/a7-wa.conf")
SNIP = Path("/opt/a7-wa/agent-reports/deploy/nginx-snippet.conf")


def strip_agent_reports_blocks(text: str) -> str:
    text = re.sub(
        r"\n?# Agent Reports[^\n]*\n(?:#[^\n]*\n)*\n*location \^~ /agent-reports/ \{.*?\n\}\n*",
        "\n",
        text,
        flags=re.S,
    )
    return re.sub(r"\n*location \^~ /agent-reports/ \{.*?\n\}\n*", "\n", text, flags=re.S)


def find_ssl_server(lines: list[str]) -> tuple[int, int]:
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("server {"):
            start = i
            depth = 0
            j = i
            while j < len(lines):
                depth += lines[j].count("{") - lines[j].count("}")
                j += 1
                if depth == 0:
                    break
            block = "".join(lines[start:j])
            if "listen443" in block.replace(" ", "") and "wa.srv1802669.hstgr.cloud" in block:
                return start, j
            i = j
        else:
            i += 1
    raise SystemExit("no SSL server block for wa.srv1802669.hstgr.cloud")


def indent_snippet(raw: str) -> str:
    out: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            out.append("\n")
            continue
        if line.startswith("    "):
            out.append(line + "\n")
        else:
            out.append("    " + line + "\n")
    return "".join(out) + "\n"


def main() -> None:
    if not CONF.is_file():
        raise SystemExit(f"missing {CONF}")
    if not SNIP.is_file():
        raise SystemExit(f"missing {SNIP}")

    original = CONF.read_text()
    Path(str(CONF) + ".bak-before-ssl-fix").write_text(original)

    text = strip_agent_reports_blocks(original)
    lines = text.splitlines(keepends=True)
    start, end = find_ssl_server(lines)
    block_lines = lines[start:end]

    insert_at = None
    for k, line in enumerate(block_lines):
        if re.match(r"\s*location\s+/\s*\{", line):
            insert_at = k
    if insert_at is None:
        raise SystemExit("no location / in SSL server")

    snip = indent_snippet(SNIP.read_text().rstrip())
    new_block = block_lines[:insert_at] + [snip] + block_lines[insert_at:]
    CONF.write_text("".join(lines[:start] + new_block + lines[end:]))
    print(f"ok: inserted /agent-reports/ before location / (index {insert_at}) in SSL server")


if __name__ == "__main__":
    main()
