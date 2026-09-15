"""Read-only live proof for restored Asma history and agent-10 OpenWA scope.

Run inside Django's already-configured web container. Secrets remain in memory;
output contains counts/status only, never API keys, phone numbers, chat ids, or messages.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
import httpx

from apps.accounts.models import OpenWaAssignment


OLD_ID = "e209881a-0aa3-4463-849f-ff0ed37144b5"
REMOVED_ID = "1faa69b9-3409-494d-8c93-2df8a9eb4975"
AGENT_ID = 10


def require(condition, message):
    if not condition:
        raise RuntimeError(f"VERIFY_FAILED: {message}")


Agent = get_user_model()
agent = Agent.objects.get(pk=AGENT_ID)
assignments = list(
    OpenWaAssignment.objects.filter(agent_id=AGENT_ID, is_active=True).values_list("session_id", flat=True)
)
require(OLD_ID in assignments, "agent 10 has no active assignment to restored Asma id")
require(REMOVED_ID not in assignments, "agent 10 is assigned to removed replacement id")
require(bool(agent.openwa_api_key), "agent 10 has no existing OpenWA API key; refusing to mint one")

base = getattr(settings, "OPENWA_INTERNAL_URL", "http://openwa-api:2785").rstrip("/")
headers = {"X-API-Key": agent.openwa_api_key}
with httpx.Client(timeout=20, headers=headers) as client:
    response = client.get(f"{base}/api/sessions")
    require(response.status_code == 200, f"scoped session list returned HTTP {response.status_code}")
    sessions = response.json()
    if isinstance(sessions, dict):
        sessions = sessions.get("sessions", sessions.get("data", []))
    restored = [row for row in sessions if row.get("id") == OLD_ID and row.get("name") == "asma"]
    require(len(restored) == 1, "restored Asma is absent from agent 10 scoped session list")
    require(restored[0].get("status") == "disconnected", "restored Asma status is not disconnected")

    response = client.get(f"{base}/api/sessions/{OLD_ID}/chats", params={"limit": 1000})
    require(response.status_code == 200, f"stored chat list returned HTTP {response.status_code}")
    chats = response.json()
    require(isinstance(chats, list) and len(chats) > 0, "stored chat list is empty")

    chat_id = chats[0].get("id") or chats[0].get("chatId")
    require(bool(chat_id), "first stored chat has no dashboard chat id")
    response = client.get(
        f"{base}/api/sessions/{OLD_ID}/messages",
        params={"chatId": chat_id, "limit": 100},
    )
    require(response.status_code == 200, f"stored thread returned HTTP {response.status_code}")
    thread = response.json()
    require(isinstance(thread, dict), "stored thread response is not an object")
    require(thread.get("total", 0) > 0 and len(thread.get("messages", [])) > 0, "stored thread is empty")

print("django-active-assignment=PASS")
print("agent-10-scoped-session=PASS")
print(f"stored-chat-count={len(chats)}")
print(f"opened-thread-total={thread['total']}")
print("dashboard-stored-history-path=PASS")
