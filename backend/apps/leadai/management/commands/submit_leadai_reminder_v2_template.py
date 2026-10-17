"""Submit the Lead AI meeting reminder v2 (UTILITY, 4 quick replies) to every active number's WABA (board T45).

v2 is v1 (a7_leadai_meeting_reminder) with a fourth quick reply, [Office Location], whose tap the
assistant answers with the office pin and Maps link (the PDF's reminder). The first three buttons
are v1's, so a v1 reminder and a v2 reminder are answered the same way. Same body, and like v1 the
wording names no company. v1 went to every active number (the owner's choice of 2026-10-09); v2
goes where the Lead AI campaigns go now, the eight sending numbers (board D4); run it again if
that ever widens.

Since batch 2e the assistant sends v2 wherever it is APPROVED on the chat's number, else v1
(reminders.approved_template), and answers [Office Location] with the office pin and Maps link
(taps.py). Idempotent: a WABA that already has v2 (any status) is skipped.
"""

from django.core.management.base import BaseCommand

from apps.catalog.models import WabaNumber, WaTemplate
from apps.catalog.views import _submit_template_to_waba
from apps.leadai.assistant import reminders
from apps.leadai.management.commands.submit_shops_templates import SENDING_NUMBERS

V2_NAME = reminders.TEMPLATE_V2_NAME
# (action, button title): v1's three, then the office location. Titles fit WhatsApp's 20 characters. The assistant reads
# a tap by these labels (reminders.ACTION_BY_LABEL), so they live there.
V2_BUTTONS = reminders.V2_BUTTONS
BODY = "Hi {{1}}, a reminder of your meeting today at {{2}} at {{3}}. Please tap below to let us know."
EXAMPLE = ["Ahmed", "5:00 PM", "Russia Cluster, Building V03, Shop 20, Dubai International City"]


def reminder_v2_parsed() -> dict:
    components = [
        {"type": "BODY", "text": BODY, "example": {"body_text": [EXAMPLE]}},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": label} for _, label in V2_BUTTONS]},
    ]
    return {
        "clean_name": V2_NAME,
        "category": "UTILITY",
        "language": "en",
        "components": components,
        "payload": {"name": V2_NAME, "category": "UTILITY", "language": "en", "components": components},
        "via_graph": False,
    }


def active_wabas() -> dict:
    """{waba_id: {phone, ...}} for each active sending number (board D4) whose WABA lacks v2 (in any status)."""
    have = set(WaTemplate.objects.filter(name=V2_NAME).values_list("waba_business_id", flat=True))
    seen: dict = {}
    for phone, waba in WabaNumber.objects.filter(is_active=True).order_by("id").values_list("phone_number", "waba_business_id"):
        phone = "".join(ch for ch in str(phone or "") if ch.isdigit())
        waba = (waba or "").strip()
        if phone in SENDING_NUMBERS and waba and waba not in have:
            seen.setdefault(waba, set()).add(phone)
    return seen


class Command(BaseCommand):
    help = f"Submit {V2_NAME} (UTILITY, 4 quick replies) to the sending numbers' WABAs that lack it."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List the WABAs, submit nothing.")

    def handle(self, *args, **options):
        self.stdout.write(f"{V2_NAME}: {BODY}")
        self.stdout.write(f"  buttons: {' | '.join(label for _, label in V2_BUTTONS)}")
        targets = active_wabas()
        if not targets:
            self.stdout.write("Every sending number's WABA has v2 already.")
            return
        self.stdout.write(f"{len(targets)} WABA(s) of the sending numbers without v2.")
        if options.get("dry_run"):
            for waba, phones in sorted(targets.items()):
                self.stdout.write(f"{waba} ({','.join(sorted(phones))}) would be submitted")
            return
        parsed = reminder_v2_parsed()
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
        self.stdout.write("Meta must APPROVE v2 before use; until then the assistant sends v1 on that number.")
