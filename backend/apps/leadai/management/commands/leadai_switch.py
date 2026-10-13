"""The Lead AI assistant's switch from the server: on, off, status, test numbers.

Run through `ops/wa.sh leadai-switch on|off|status` or
`ops/wa.sh leadai-test-number <digits>`. The same switch is in the Lead AI
screen's AI settings and in Django admin.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.leadai.assistant import openai_client
from apps.leadai.models import LeadAiSettings
from apps.leadai.views import normalize_number


class Command(BaseCommand):
    help = "Switch the Lead AI assistant on or off, show its state, or set its test numbers."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["on", "off", "status", "test-numbers"])
        parser.add_argument("numbers", nargs="*", help="For test-numbers: digits with country code.")

    def handle(self, *args, action, numbers, **options):
        row = LeadAiSettings.load()
        if action in ("on", "off"):
            enabled = action == "on"
            if row.assistant_enabled != enabled:
                row.history = (list(row.history or []) + [
                    {"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": {"assistant_enabled": [str(row.assistant_enabled), str(enabled)]}}
                ])[-100:]
                row.assistant_enabled = enabled
                if enabled:
                    row.paused_until = None
                    row.consecutive_failures = 0
                row.save()
        elif action == "test-numbers":
            # The same rule as the Lead AI screen: 00 dropped, a local 0... refused.
            clean = []
            for item in numbers:
                digits, error = normalize_number(item)
                if error:
                    raise CommandError(error)
                clean.append(digits)
            row.history = (list(row.history or []) + [
                {"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": {"test_numbers": [str(row.test_numbers), str(clean)]}}
            ])[-100:]
            row.test_numbers = clean
            row.save()
        self.stdout.write(f"assistant_enabled={row.assistant_enabled}")
        self.stdout.write(f"test_numbers={len(row.test_numbers or [])}")
        self.stdout.write(f"key_configured={openai_client.configured()} model={openai_client.chat_model()}")
        self.stdout.write(f"paused_until={row.paused_until or '-'} last_sweep_at={row.last_sweep_at or '-'}")
