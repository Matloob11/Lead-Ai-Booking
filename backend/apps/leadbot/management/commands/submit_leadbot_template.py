"""Submit the leadbot UTILITY template to every agent 971 WABA."""

from django.core.management.base import BaseCommand

from apps.catalog.models import NumberAssignment
from apps.catalog.views import _submit_template_to_waba
from apps.leadbot.bitrix_sync import template_name
from apps.leadbot.resolve import digits_only

BODY = (
    "Hi {{1}}, we received your property enquiry submitted on {{2}}. "
    "Property: {{3}}. Recorded budget: {{4}}. Reference: {{5}}. "
    "Please reply YES to continue, or NO if it is no longer required."
)


def outreach_parsed():
    name = template_name()
    components = [
        {
            "type": "BODY",
            "text": BODY,
            "example": {
                "body_text": [["Sara", "Property Finder", "2BR rental enquiry", "85000", "L1001"]]
            },
        },
        {"type": "FOOTER", "text": "A7 Group Real Estate"},
    ]
    return {
        "clean_name": name,
        "category": "UTILITY",
        "language": "en",
        "components": components,
        "payload": {
            "name": name,
            "category": "UTILITY",
            "language": "en",
            "components": components,
        },
        "via_graph": False,
    }


class Command(BaseCommand):
    help = "Submit a7_lead_enquiry_confirm (UTILITY) to each active agent 971 WABA."

    def handle(self, *args, **options):
        parsed = outreach_parsed()
        seen = {}
        rows = (
            NumberAssignment.objects.filter(is_active=True, number__is_active=True)
            .select_related("number")
            .order_by("id")
        )
        for row in rows:
            phone = digits_only(row.number.phone_number)
            waba = (row.number.waba_business_id or "").strip()
            if not phone.startswith("971") or not waba:
                continue
            seen.setdefault(waba, set()).add(phone)

        if not seen:
            self.stdout.write("No active agent 971 numbers.")
            return

        for waba, phones in sorted(seen.items()):
            template, err, skipped = _submit_template_to_waba(waba, parsed)
            label = ",".join(sorted(phones))
            if err:
                self.stdout.write(self.style.ERROR(f"{waba} ({label}) FAILED {err}"))
            elif skipped:
                status = getattr(template, "status", "")
                self.stdout.write(f"{waba} ({label}) already {status}")
            else:
                self.stdout.write(self.style.SUCCESS(f"{waba} ({label}) submitted {template.status}"))
        self.stdout.write(
            "Meta must APPROVE the template before outreach sends. "
            "Until then leadbot records Outreach failed."
        )
