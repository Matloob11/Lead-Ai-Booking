# Read-only probe (2026-10-22, Lead AI round 23): as the real agents who are the Bitrix responsibles of the chats on a
# handover desk, through the test client inside web: /api/auth/me/ carries their desk's count, /api/leadai/desk/mine/
# lists exactly their chats (the chat and the customer, nothing of the team), the chat detail opens (trimmed when they
# have the chat through the desk alone), a colleague's desk chat is refused (404), another agent's desk is refused (403),
# and a panel admin may look at a desk with ?agent=. Phones are masked. Nothing is written; no message is sent.
from django.contrib.auth import get_user_model
from django.test import Client

from apps.inbox.models import Conversation
from apps.leadai import handover_desk
from apps.leadai.models import LeadAiChatState

Agent = get_user_model()
HOST = "wa.srv1802669.hstgr.cloud"
ROW_KEYS = {
    "id", "number_id", "contact", "last_message_at", "last_message_preview", "last_message_kind", "unread_count",
    "is_session_open", "session_expires_at", "desk", "ai", "appointment",
}


def mask(value) -> str:
    text = str(value or "")
    return f"{text[:4]}…{text[-2:]}" if len(text) > 6 else "…"


on_desk = LeadAiChatState.objects.filter(desk_at__isnull=False, conversation__lead_ai_chat__active=True)
responsibles = sorted({row for row in on_desk.values_list("responsible_bitrix_user_id", flat=True) if row})
by_responsible = {bitrix: list(on_desk.filter(responsible_bitrix_user_id=bitrix).values_list("conversation_id", flat=True)) for bitrix in responsibles}
rows = []
admin = Agent.objects.filter(is_active=True, is_wa_admin=True).order_by("pk").first()
for bitrix in responsibles:
    agent = Agent.objects.filter(bitrix_user_id=bitrix, is_active=True).first()
    if agent is None:
        print(f"SKIP | Bitrix {bitrix}: no panel account ({len(by_responsible[bitrix])} chats stay on the Lead AI screen for admins)")
        continue
    client = Client(HTTP_HOST=HOST)
    client.force_login(agent)
    me = client.get("/api/auth/me/", secure=True)
    me_data = me.json() if me.status_code == 200 else {}
    mine = client.get("/api/leadai/desk/mine/", secure=True)
    mine_data = mine.json() if mine.status_code == 200 else {}
    results = mine_data.get("results") or []
    expected = set(by_responsible[bitrix])
    listed = {row["id"] for row in results}
    keys_ok = all(set(row) == ROW_KEYS for row in results)
    detail_ok = trimmed = None
    if results:
        first = results[0]
        conversation = Conversation.objects.get(pk=first["id"])
        detail = client.get(f"/api/leadai/chats/{first['id']}/", secure=True)
        row = detail.json() if detail.status_code == 200 else {}
        alone = handover_desk.only_through_desk(agent, conversation)
        trimmed = bool(row) and row.get("assigned_agent") is None and set(row.get("number") or {}) == {"id", "phone_number"} and row.get("lead_ai_info") is None and row.get("leadbot") is None
        detail_ok = detail.status_code == 200 and (trimmed if alone else True)
    others = [pk for other, pks in by_responsible.items() if other != bitrix for pk in pks]
    refused = client.get(f"/api/leadai/chats/{others[0]}/", secure=True).status_code == 404 if others else True
    refused_messages = client.get(f"/api/inbox/conversations/{others[0]}/messages/", secure=True).status_code == 404 if others else True
    other_desk = next((other for other in responsibles if other != bitrix), None)
    forbidden = client.get(f"/api/leadai/desk/mine/?agent={other_desk}", secure=True).status_code == 403 if other_desk else True
    chats = client.get("/api/leadai/chats/?limit=100", secure=True)
    chat_count = len((chats.json() or {}).get("results", [])) if chats.status_code == 200 else None
    ok = (
        me.status_code == 200
        and (me_data.get("handover_desk") or {}).get("count") == len(expected)
        and mine.status_code == 200
        and listed == expected
        and keys_ok
        and (detail_ok is not False)
        and refused and refused_messages and forbidden
    )
    rows.append(ok)
    sample = f"first {mask(results[0]['contact'].get('wa_id'))} reason={results[0]['desk'].get('reason')} wait={results[0]['desk'].get('waiting_minutes')}m" if results else "no rows"
    print(
        f"{'PASS' if ok else 'FAIL'} | Bitrix {bitrix} numbers={len(me_data.get('numbers', []))} admin={me_data.get('is_wa_admin')} "
        f"lead_ai={me_data.get('can_lead_ai')} me.count={(me_data.get('handover_desk') or {}).get('count')} desk={mine.status_code}/{len(results)} "
        f"expected={len(expected)} keys={keys_ok} detail={detail_ok} trimmed={trimmed} list={chat_count} "
        f"other404={refused}/{refused_messages} otherdesk403={forbidden} | {sample}"
    )
    client.logout()
if admin is not None and responsibles:
    client = Client(HTTP_HOST=HOST)
    client.force_login(admin)
    bitrix = responsibles[0]
    view = client.get(f"/api/leadai/desk/mine/?agent={bitrix}", secure=True)
    count = len((view.json() or {}).get("results", [])) if view.status_code == 200 else None
    ok = view.status_code == 200 and count == len(by_responsible[bitrix])
    rows.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} | admin (Bitrix {admin.bitrix_user_id}) ?agent={bitrix}: {view.status_code}/{count} expected {len(by_responsible[bitrix])}")
    client.logout()
print(f"passed {sum(rows)} of {len(rows)}")
print("PROBE_OK" if rows and all(rows) else "PROBE_FAILED")
