"""Set the shop clusters Lead AI names, as the AI settings dialog would.

Run through `ops/wa.sh set-leadai-shops-clusters "France, England, ..."`: the verb passes the
comma-separated list as an environment variable and pipes this file into `manage.py shell` in the
web container. The whole shops facts go through shops.validate, the settings view's own check, so a
list the dialog would refuse is refused here too; the change is recorded in the settings history.
Board Q42 (2026-10-17): Greece Cluster is one of the shop clusters.
"""

import os

from django.utils import timezone

from apps.leadai.assistant import shops
from apps.leadai.models import LeadAiSettings

wanted = [part.strip() for part in os.environ.get("LEADAI_SHOPS_CLUSTERS", "").split(",") if part.strip()]

row = LeadAiSettings.load()
old = dict(row.shops_facts or {})
facts, errors = shops.validate({**old, "clusters": wanted})
if not wanted or errors:
    print("REFUSED:", errors or "give at least one cluster")
else:
    before, after = list(old.get("clusters") or []), facts["clusters"]
    if before != after:
        row.shops_facts = facts
        row.history = (list(row.history or []) + [
            {"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": {"shops_facts.clusters": [before, after]}}
        ])[-100:]
        row.save()
    print("clusters=", ", ".join(after))
    print("changed:", "shops_facts.clusters" if before != after else "nothing (already set)")
