# Read-only live check, run through `ops/wa.sh probe-crm-entities`:
# the CRM-leads campaign code in the live web image must understand
# deal and contact rows (deal -> crm_deal_id, contact -> no CRM id,
# lead -> crm_lead_id). Nothing is sent and nothing is written.
from apps.campaigns.crm_leads import ENTITY_NOUNS, build_recipients, crm_entity


class T:
    variable_count = 1


print("crm_entity:", {k: crm_entity(k) for k in ("lead", "owner_data", "deal", "contact", "x")})
rows, _ = build_recipients(template=T(), leads=[{"id": 501, "phone": "+971 50 111 2222", "name": "Ali"}], extra_body={}, entity="deal")
print("deal row:", rows[0])
rows, _ = build_recipients(template=T(), leads=[{"id": 77, "phone": "971509998888", "first_name": "Sara", "last_name": "Khan"}], extra_body={}, entity="contact")
print("contact row:", rows[0])
rows, _ = build_recipients(template=T(), leads=[{"id": 9, "phone": "971501234567", "name": "Lead X"}], extra_body={}, entity="lead")
print("lead row:", rows[0])
print("labels:", {k: v[2] for k, v in ENTITY_NOUNS.items()})
print("PROBE_OK")
