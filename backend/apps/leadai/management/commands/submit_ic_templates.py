"""Submit the International City mixed template to the sending numbers' WABAs (board Q34).

    python manage.py submit_ic_templates --dry-run      what would be submitted, nothing sent
    python manage.py submit_ic_templates                 submit what is missing
    python manage.py submit_ic_templates --numbers 971581058719,971581058725

- intl_city_property_reconnect (MARKETING, en, no header): for a campaign of shop, studio and
  one-bedroom leads; quick replies [Yes, still looking] [Not now] [Stop messages].

The text and the composer's fields are ic_templates.py's. Each WABA of the numbers (default: the
eight sending numbers, board D4) that does not have it yet in ANY status or language gets it,
through apps.catalog's own create (the Template Center's code, never a Meta call of its own). An
existing template, or one hidden in the panel, is never touched. The numbers and WABA helpers are
submit_shops_templates's.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.leadai import ic_templates
from apps.leadai.management.commands.submit_shops_templates import existing, parse_numbers, wabas_for
from apps.leadai.models import LeadAiSettings


class Command(BaseCommand):
    help = f"Submit {ic_templates.MIXED_NAME} to the sending numbers' WABAs that do not have it yet (any status)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Say what would be submitted; submit nothing.")
        parser.add_argument(
            "--numbers", default="", metavar="9715...,...", help="Comma-separated numbers; default: the eight sending numbers."
        )

    def handle(self, *args, **options):
        from apps.catalog.views import _parse_template_form, _submit_template_to_waba

        dry = bool(options.get("dry_run"))
        numbers = parse_numbers(options.get("numbers") or "")
        targets, problems = wabas_for(numbers)
        for line in problems:
            self.stdout.write(self.style.WARNING(line))
        if not targets:
            raise CommandError("None of the numbers can take a template.")
        facts = LeadAiSettings.load().shops_facts
        name = ic_templates.MIXED_NAME
        self.stdout.write(f"{name}: {ic_templates.mixed_body(facts)}")
        self.stdout.write(f"  buttons: {' | '.join(ic_templates.MIXED_BUTTONS)}")
        parsed, error = _parse_template_form(ic_templates.mixed_form(facts))
        if error:
            raise CommandError(f"{name}: {error}")

        submitted = skipped = failed = 0
        for waba, phones in sorted(targets.items()):
            label = f"WABA {waba} ({', '.join('+' + phone for phone in phones)})"
            have = existing(waba, name)
            if have:
                skipped += 1
                self.stdout.write(f"{label}: already {have}, left alone")
            elif dry:
                submitted += 1
                self.stdout.write(f"{label}: would be submitted")
            else:
                template, error, was_skipped = _submit_template_to_waba(waba, parsed)
                if error:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f"{label}: FAILED {error}"))
                elif was_skipped:
                    skipped += 1
                    self.stdout.write(f"{label}: Meta has it already ({getattr(template, 'status', '')}), left alone")
                else:
                    submitted += 1
                    self.stdout.write(self.style.SUCCESS(f"{label}: submitted, {template.status} at Meta"))
        verb = "would submit" if dry else "submitted"
        self.stdout.write(f"{verb}={submitted} skipped={skipped} failed={failed}")
        if not dry and submitted:
            self.stdout.write(
                "Meta must APPROVE it before use, and it must not be SENT before batch 2e is live: until then the "
                "assistant treats every campaign template as a shops one."
            )
