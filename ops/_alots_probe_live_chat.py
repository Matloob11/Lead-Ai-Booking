"""Probe GetUserChatMessages with the gitignored Omni cookie. Prints counts only."""

from pathlib import Path

import httpx

raw = Path("deploy/.env.alots_ui").read_text(encoding="utf-8").strip()
prefix = "ALOTS_UI_COOKIE="
if not raw.startswith(prefix):
    raise SystemExit("no cookie env")
cookie = raw[len(prefix) :].strip()
if cookie.startswith('"') and cookie.endswith('"'):
    cookie = cookie[1:-1].replace('\\"', '"').replace("\\\\", "\\")
with httpx.Client(timeout=30, follow_redirects=False) as client:
    response = client.get(
        "https://alots.io/WAMessage/UserLiveChat/GetUserChatMessages",
        params={
            "senderNumber": "971566471256",
            "channelNumber": "971555817694",
            "chatType": "All",
            "pageSize": "50",
        },
        headers={"Accept": "application/json", "Cookie": cookie},
    )
n = -1
if response.status_code == 200:
    try:
        n = len((response.json() or {}).get("chatList") or [])
    except ValueError:
        n = -2
print("status", response.status_code, "n", n)
