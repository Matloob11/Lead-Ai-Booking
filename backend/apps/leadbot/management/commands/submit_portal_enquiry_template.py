"""Submit portal_enquiry_reply (C68) to the eight sending WABAs (board D4).

Lives under leadbot (not leadai) so the catalog package on the box does not
need a new management/ tree. Same submit path as submit_leadbot_template.

    python manage.py submit_portal_enquiry_template --dry-run
    python manage.py submit_portal_enquiry_template
    python manage.py submit_portal_enquiry_template --category MARKETING
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import WabaNumber, WaTemplate, WaTemplateHide
from apps.catalog.views import _parse_template_form, _submit_template_to_waba

SENDING_NUMBERS = (
    "971581058719",
    "971581058720",
    "971581058721",
    "971581058722",
    "971581058723",
    "971581058724",
    "971581058725",
    "971581058726",
)

NAME = "portal_enquiry_reply"
BODY = (
    "Hi {{1}}, thank you for your enquiry about {{2}} with A7 Group Real Estate. "
    "Are you still looking? Reply here and I will share the details, photos and "
    "available viewing times."
)


def digits(raw) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def wabas_for(numbers: list[str]) -> tuple[dict, list[str]]:
    by_digits = {}
    for row in WabaNumber.objects.all().order_by("pk"):
        by_digits.setdefault(digits(row.phone_number), row)
    targets: dict[str, list[str]] = {}
    problems = []
    for number in numbers:
        row = by_digits.get(number)
        if row is None:
            problems.append(f"+{number}: no such number here, left out")
        elif not row.is_active:
            problems.append(f"+{number}: the number is not active, left out")
        elif not (row.waba_business_id or "").strip():
            problems.append(f"+{number}: the number has no WhatsApp Business account id, left out")
        else:
            phones = targets.setdefault(row.waba_business_id.strip(), [])
            if number not in phones:
                phones.append(number)
    return targets, problems


def existing(waba: str, name: str) -> str:
    rows = list(
        WaTemplate.objects.filter(waba_business_id=waba, name=name).values_list(
            "status", "language", "category"
        )
    )
    if rows:
        return ", ".join(
            f"{status}/{category} ({language})" for status, language, category in rows
        )
    if WaTemplateHide.objects.filter(waba_business_id=waba, name=name).exists():
        return "hidden in the panel"
    return ""


class Command(BaseCommand):
    help = "Submit portal_enquiry_reply to the eight sending WABAs (C68)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--category",
            default="UTILITY",
            choices=["UTILITY", "MARKETING"],
            help="Meta category (default UTILITY; use MARKETING if Meta refuses UTILITY).",
        )

    def handle(self, *args, **options):
        category = options["category"]
        dry = options["dry_run"]
        form = {
            "name": NAME,
            "category": category,
            "language": "en",
            "body_text": BODY,
            "body_examples": {
                "1": "Sara",
                "2": "the 2-bedroom in Serena",
            },
        }
        parsed, err = _parse_template_form(form)
        if err:
            raise CommandError(err)

        targets, problems = wabas_for(list(SENDING_NUMBERS))
        for line in problems:
            self.stdout.write(self.style.WARNING(line))
        if not targets:
            raise CommandError("No sending WABAs found.")

        self.stdout.write(f"template={NAME} category={category} language=en wabas={len(targets)}")
        for waba, phones in sorted(targets.items()):
            label = ",".join(f"+{p}" for p in phones)
            have = existing(waba, NAME)
            if have:
                self.stdout.write(f"{waba} ({label}) already {have}")
                continue
            if dry:
                self.stdout.write(f"{waba} ({label}) would submit {category}")
                continue
            template, error, skipped = _submit_template_to_waba(waba, parsed)
            if error:
                self.stdout.write(self.style.ERROR(f"{waba} ({label}) FAILED {error}"))
            elif skipped:
                status = getattr(template, "status", "")
                cat = getattr(template, "category", "")
                self.stdout.write(f"{waba} ({label}) already {status}/{cat}")
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{waba} ({label}) submitted {template.status}/{template.category}"
                    )
                )
        if dry:
            self.stdout.write("dry-run: nothing submitted.")
        else:
            self.stdout.write("Meta must APPROVE before Lead AI can send the greet.")
