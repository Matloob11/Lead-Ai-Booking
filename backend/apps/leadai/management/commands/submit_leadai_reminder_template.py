"""Submit the Lead AI meeting reminder (UTILITY, 3 quick replies) to every active number's WABA.

The owner chose (2026-10-09, after seeing that most CRM campaigns go out from
+44 numbers) to submit it to EVERY active number with an agent, not only the
+971 ones. It is only needed when the 30-minute reminder falls outside the
customer's 24-hour window; inside it the reminder goes as a free-form message
with the same three buttons.

The wording names no company: campaigns go out under several brands (A7,
AR Properties, ...) and a reminder from a name the customer never saw would
look like a scam.

Idempotent: a WABA that already has the template (any status) is skipped.
"""

from django.core.management.base import BaseCommand

from apps.catalog.models import NumberAssignment
from apps.catalog.views import _submit_template_to_waba
from apps.leadai.assistant.reminders import BUTTONS, TEMPLATE_NAME

BODY = "Hi {{1}}, a reminder of your meeting today at {{2}} at {{3}}. Please tap below to let us know."
EXAMPLE = ["Ahmed", "5:00 PM", "Russia Cluster, Building V02/V03, Shop 20, Dubai International City"]


def reminder_parsed() -> dict:
    components = [
        {"type": "BODY", "text": BODY, "example": {"body_text": [EXAMPLE]}},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": label} for _, label in BUTTONS]},
    ]
    return {
        "clean_name": TEMPLATE_NAME,
        "category": "UTILITY",
        "language": "en",
        "components": components,
        "payload": {
            "name": TEMPLATE_NAME,
            "category": "UTILITY",
            "language": "en",
            "components": components,
        },
        "via_graph": False,
    }


def active_wabas() -> dict:
    """{waba_id: {phone, ...}} for every active number that an active agent is assigned to."""
    seen: dict = {}
    rows = (
        NumberAssignment.objects.filter(is_active=True, number__is_active=True)
        .select_related("number")
        .order_by("id")
    )
    for row in rows:
        phone = "".join(ch for ch in str(row.number.phone_number or "") if ch.isdigit())
        waba = (row.number.waba_business_id or "").strip()
        if phone and waba:
            seen.setdefault(waba, set()).add(phone)
    return seen


class Command(BaseCommand):
    help = f"Submit {TEMPLATE_NAME} (UTILITY, 3 quick replies) to every active assigned number's WABA."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List the WABAs, submit nothing.")

    def handle(self, *args, **options):
        targets = active_wabas()
        if not targets:
            self.stdout.write("No active assigned numbers.")
            return
        self.stdout.write(f"{len(targets)} WABA(s) with an active assigned number.")
        if options.get("dry_run"):
            for waba, phones in sorted(targets.items()):
                self.stdout.write(f"{waba} ({','.join(sorted(phones))}) would be submitted")
            return
        parsed = reminder_parsed()
        submitted = skipped = failed = 0
        for waba, phones in sorted(targets.items()):
            label = ",".join(sorted(phones))
            template, err, was_skipped = _submit_template_to_waba(waba, parsed)
            if err:
                failed += 1
                self.stdout.write(self.style.ERROR(f"{waba} ({label}) FAILED {err}"))
            elif was_skipped:
                skipped += 1
                self.stdout.write(f"{waba} ({label}) already {getattr(template, 'status', '')}")
            else:
                submitted += 1
                self.stdout.write(self.style.SUCCESS(f"{waba} ({label}) submitted {template.status}"))
        self.stdout.write(f"submitted={submitted} skipped={skipped} failed={failed}")
        self.stdout.write(
            "Meta must APPROVE the template before it is used. Until then a reminder outside "
            "the 24-hour window is not sent and the agents are told instead."
        )
