"""Creates the fields the pinned summary is written into.

Run once, and safe to run again — Bitrix refuses a field that already exists
and that refusal is reported rather than treated as a failure.

Fields rather than only a comment, because a comment sinks: the next message
pushes it down the timeline and a manager opening the lead a week later sees
forty WhatsApp lines and no summary. A field sits at the top of the record, and
can be filtered and sorted on, which is what makes "show me every lead scoring
over 70" a question somebody can actually ask.
"""

from django.core.management.base import BaseCommand

from apps.crmlink import client

FIELDS = [
    {
        "FIELD_NAME": "UF_CRM_WA_SUMMARY",
        "USER_TYPE_ID": "string",
        "EDIT_FORM_LABEL": {"en": "WhatsApp summary"},
        "LIST_COLUMN_LABEL": {"en": "WhatsApp summary"},
        "SETTINGS": {"ROWS": 6},
    },
    {
        "FIELD_NAME": "UF_CRM_WA_CLIENT_SCORE",
        "USER_TYPE_ID": "integer",
        "EDIT_FORM_LABEL": {"en": "Customer interest (0-100)"},
        "LIST_COLUMN_LABEL": {"en": "Customer 0-100"},
    },
    {
        "FIELD_NAME": "UF_CRM_WA_AGENT_SCORE",
        "USER_TYPE_ID": "integer",
        "EDIT_FORM_LABEL": {"en": "Our handling (0-100)"},
        "LIST_COLUMN_LABEL": {"en": "Handling 0-100"},
    },
]


class Command(BaseCommand):
    help = "Creates the WhatsApp summary fields on leads and contacts in Bitrix24."

    def handle(self, *args, **options):
        if not client.configured():
            self.stderr.write("BITRIX_WEBHOOK_URL is not set — nothing to do.")
            return

        for entity in ("lead", "contact"):
            for field in FIELDS:
                name = field["FIELD_NAME"]
                try:
                    result = client.call(f"crm.{entity}.userfield.add", {"fields": field})
                    self.stdout.write(f"{entity}.{name}: created (id {result})")
                except client.BitrixError as exc:
                    # Already there is the expected answer on a second run.
                    self.stdout.write(f"{entity}.{name}: {exc}")
