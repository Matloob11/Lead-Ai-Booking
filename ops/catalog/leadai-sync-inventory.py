# The Lead AI inventory refreshed by hand (apps/leadai/assistant/inventory.py): Property Finder's live listings and
# the clean Availability cards into LeadAiUnit, then the counts and a few units, so a deploy can prove the sync works
# before the half-hourly beat job does it. Prints no owner number (none is stored) and no key.
#
# Run in the web container through `ops/wa.sh leadai-sync-inventory`.

import json

from django.conf import settings
from django.db.models import Count

from apps.leadai.assistant import inventory
from apps.leadai.models import LeadAiUnit

print("pf configured:", inventory.pf_configured(), "| bitrix webhook:", bool(getattr(settings, "BITRIX_WEBHOOK_URL", "")))
result = inventory.sync()
print("sync:", json.dumps(result))
active = LeadAiUnit.objects.filter(active=True)
print("active units:", active.count(), "| by source:", dict(active.values("source").annotate(n=Count("pk")).values_list("source", "n")))
by_place = {}
for row in active.values("community", "unit", "deal"):
    key = f"{row['community'] or '?'} / {row['unit'] or '?'} / {row['deal'] or '?'}"
    by_place[key] = by_place.get(key, 0) + 1
for key, n in sorted(by_place.items(), key=lambda kv: -kv[1])[:15]:
    print(f"  {n:4d}  {key}")
print("--- International City studios / one-bedrooms for rent (what the campaigns' chats would see):")
for row in inventory.matches(inventory.DEFAULT_COMMUNITY, [], "studio", "rent") + inventory.matches(inventory.DEFAULT_COMMUNITY, [], "one_br", "rent"):
    print(" ", inventory.line(row))
print("DONE")
