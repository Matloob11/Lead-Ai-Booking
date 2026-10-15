"""Set the office address text Lead AI sends, as the AI settings dialog would.

Run through `ops/wa.sh set-leadai-office-address "TEXT"`: the verb passes the text
as an environment variable and pipes this file into `manage.py shell` in the web
container. The text is cleaned the way the settings view cleans it
(apps.leadai.views: spaces squashed, never empty, at most 255 characters), and
the change is recorded in the settings history.
"""

import os

from django.utils import timezone

from apps.leadai.models import LeadAiSettings

address = " ".join(os.environ.get("LEADAI_OFFICE_ADDRESS", "").split())[:255]

if not address:
    print("REFUSED: The office address cannot be empty.")
else:
    row = LeadAiSettings.load()
    old = row.office_address
    if old != address:
        row.office_address = address
        row.history = (list(row.history or []) + [
            {"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": {"office_address": [str(old), address]}}
        ])[-100:]
        row.save()
    print("office_address=", row.office_address)
    print("changed:", "office_address" if old != address else "nothing (already set)")
