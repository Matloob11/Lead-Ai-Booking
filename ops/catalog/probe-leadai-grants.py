# Read-only probe (2026-10-23, Lead AI round 25; ops/wa.sh probe-leadai-grants): "Lead AI access" per Bitrix user, through
# the test client inside web.
# As a real panel admin: GET /api/leadai/access/ answers (the portal's users read live, merged with the panel's
# accounts; how many rows, how many in Bitrix, how many with an account, the admins, the grants), and the list refuses
# a non-admin (403). The migration's backfill: every active account with Lead AI access (can_lead_ai) and a real
# Bitrix id has its all_chats row. For every account with a row grant, /api/auth/me/ carries lead_ai_access that says
# the same as access.of. Names and counts only; no phone number; nothing is written; no grant is changed.
from django.contrib.auth import get_user_model
from django.test import Client

from apps.leadai import access
from apps.leadai.models import LeadAiAccess

Agent = get_user_model()
HOST = "wa.srv1802669.hstgr.cloud"
FLAGS = ("all_chats", "today", "needs")

problems = []
admin = Agent.objects.filter(is_active=True, is_wa_admin=True, can_official_api=True).order_by("pk").first()
if admin is None:
    problems.append("no active panel admin with the Official API inbox to look as")
else:
    client = Client(HTTP_HOST=HOST)
    client.force_login(admin)
    response = client.get("/api/leadai/access/", secure=True)
    print(f"GET /api/leadai/access/ as {admin.display_name or admin.username} (admin) -> {response.status_code}")
    if response.status_code != 200:
        problems.append(f"the list answered {response.status_code}")
    else:
        payload = response.json()
        rows = payload.get("results") or []
        bitrix = payload.get("bitrix") or {}
        print(
            f"  rows {payload.get('count')} | in Bitrix {sum(1 for r in rows if r.get('in_bitrix'))} | with an account "
            f"{sum(1 for r in rows if r.get('account'))} | admins {sum(1 for r in rows if r.get('admin'))} | flags {payload.get('flags')} | me {payload.get('me')}"
        )
        print(f"  portal read at {bitrix.get('read_at')} | users {bitrix.get('users')} | error {bitrix.get('error') or '-'}")
        if not bitrix.get("read_at") and not bitrix.get("error"):
            problems.append("the portal's users were neither read nor refused (no webhook?)")
        if bitrix.get("error"):
            problems.append(f"the portal could not be read: {bitrix.get('error')[:120]}")
        if payload.get("flags") != list(FLAGS):
            problems.append(f"flags {payload.get('flags')}")
        granted = [r for r in rows if not r.get("admin") and any(r.get("access", {}).get(flag) for flag in FLAGS)]
        print(f"  granted (not admin): {len(granted)}")
        for r in sorted(granted, key=lambda item: item["name"].lower())[:40]:
            account = r.get("account") or {}
            flags = " ".join(f"{flag}={'on' if r['access'].get(flag) else 'off'}" for flag in FLAGS)
            state = "no account" if not account else ("inactive" if not account.get("is_active") else "active")
            print(f"    {r['name']} (Bitrix {r['bitrix_user_id']}, {state}) {flags} | effective {r.get('effective')} | handovers {r.get('handovers')}")
        bad_rows = [r["bitrix_user_id"] for r in rows if r.get("bitrix_user_id") in ("", "0", "1")]
        if bad_rows:
            problems.append(f"hold users listed: {bad_rows}")
        first_admin = next((i for i, r in enumerate(rows) if r.get("admin")), None)
        last_admin = max((i for i, r in enumerate(rows) if r.get("admin")), default=None)
        if first_admin is not None and any(not r.get("admin") for r in rows[: last_admin + 1]):
            problems.append("admins are not first in the list")
    # A non-admin is refused.
    agent = Agent.objects.filter(is_active=True, is_wa_admin=False, is_superuser=False, can_official_api=True).order_by("pk").first()
    if agent is not None:
        other = Client(HTTP_HOST=HOST)
        other.force_login(agent)
        code = other.get("/api/leadai/access/", secure=True).status_code
        print(f"GET /api/leadai/access/ as {agent.display_name or agent.username} (no admin rights) -> {code}")
        if code != 403:
            problems.append(f"a non-admin got {code} from the list, not 403")

# The backfill: every active account with Lead AI access and a real Bitrix id has its all_chats row.
flagged = {
    access.bitrix_id(a): a
    for a in Agent.objects.filter(can_lead_ai=True).exclude(bitrix_user_id__isnull=True).exclude(bitrix_user_id="")
    if access.bitrix_id(a)
}
rows_on = set(LeadAiAccess.objects.filter(all_chats=True).values_list("bitrix_user_id", flat=True))
missing = sorted(set(flagged) - rows_on)
print(f"backfill: accounts with Lead AI access and a Bitrix id {len(flagged)} | all_chats rows {len(rows_on)} | missing rows {missing or 'none'}")
if missing:
    problems.append(f"accounts with Lead AI access and no all_chats row: {missing}")
rows_total = LeadAiAccess.objects.count()
print(f"LeadAiAccess rows: {rows_total}; with any grant: {LeadAiAccess.objects.filter(all_chats=True).count()} all_chats, {LeadAiAccess.objects.filter(today=True).count()} today, {LeadAiAccess.objects.filter(needs=True).count()} needs")

# Every account with a row grant: the sign-in payload says what access.of says.
checked = 0
for row in LeadAiAccess.objects.filter(all_chats=True) | LeadAiAccess.objects.filter(today=True) | LeadAiAccess.objects.filter(needs=True):
    agent = Agent.objects.filter(bitrix_user_id=row.bitrix_user_id, is_active=True).order_by("pk").first()
    if agent is None:
        continue
    client = Client(HTTP_HOST=HOST)
    client.force_login(agent)
    me = client.get("/api/auth/me/", secure=True)
    payload = me.json() if me.status_code == 200 else {}
    found = access.payload_for(Agent.objects.get(pk=agent.pk))
    checked += 1
    if payload.get("lead_ai_access") != found:
        problems.append(f"{agent.display_name or agent.username}: /api/auth/me/ lead_ai_access {payload.get('lead_ai_access')} != access.of {found}")
    if found["all_chats"] and not payload.get("can_lead_ai"):
        problems.append(f"{agent.display_name or agent.username}: can_lead_ai False in the sign-in payload while the grant is on")
print(f"sign-in payloads checked against access.of: {checked}")

if problems:
    print("PROBE_FAILED")
    for problem in problems:
        print(" -", problem)
else:
    print("passed | Lead AI access: the list answers for an admin and refuses a non-admin, the backfill is whole, the sign-in payloads agree")
