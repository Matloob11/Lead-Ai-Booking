# One-off (2026-10-19): give Lead AI access (Agent.can_lead_ai) to named agents, as a panel admin would in
# "Agents & access" (apps/catalog/views.set_agent_admin), and show the result. Run in the web container through
# `ops/wa.sh leadai-grant-access <bitrix ids...>`; GRANT_IDS holds the ids, comma-separated.
import os

from django.contrib.auth import get_user_model

Agent = get_user_model()
ids = [part.strip() for part in os.environ.get("GRANT_IDS", "").split(",") if part.strip()]
if not ids:
    raise SystemExit("GRANT_IDS is empty")
rows = list(Agent.objects.filter(bitrix_user_id__in=ids, is_active=True).order_by("display_name"))
missing = sorted(set(ids) - {row.bitrix_user_id for row in rows})
if missing:
    raise SystemExit(f"no active agent for Bitrix id(s): {', '.join(missing)}")
for agent in rows:
    before = agent.can_lead_ai
    if not agent.can_official_api:
        print(f"  SKIP {agent.display_name} (Bitrix {agent.bitrix_user_id}): no Official API access, the desk needs it")
        continue
    if not before:
        agent.can_lead_ai = True
        agent.save(update_fields=["can_lead_ai"])
    print(f"  {agent.display_name} (Bitrix {agent.bitrix_user_id}): can_lead_ai {before} -> {agent.can_lead_ai}")
print(f"agents with Lead AI access now: {Agent.objects.filter(can_lead_ai=True, is_active=True).count()}")
