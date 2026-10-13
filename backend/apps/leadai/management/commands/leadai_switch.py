"""The Lead AI assistant's switch from the server: on, off, status, test numbers,
and the Bitrix users who also get its booking, broker and handover alerts.

Run through `ops/wa.sh leadai-switch on|off|status`,
`ops/wa.sh leadai-test-numbers <digits>` or `ops/wa.sh leadai-alert-ids <ids>`.
The same settings are in the Lead AI screen's AI settings and in Django admin.
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.leadai.assistant import openai_client
from apps.leadai.models import LeadAiSettings
from apps.leadai.views import normalize_number

MAX_ALERT_IDS = 10  # the AI settings dialog's limit


class Command(BaseCommand):
    help = "Switch the Lead AI assistant on or off, show its state, or set its test numbers or alert ids."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["on", "off", "status", "test-numbers", "alert-ids"])
        parser.add_argument("numbers", nargs="*", help="test-numbers: digits with country code; alert-ids: Bitrix user ids.")

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
        elif action == "alert-ids":
            # Same rule as the AI settings dialog: digits only, at most 10, no repeats.
            clean = []
            for item in numbers:
                if not re.fullmatch(r"\d{1,10}", item):
                    raise CommandError(f"'{item}' is not a Bitrix user id (digits only)")
                if item not in clean:
                    clean.append(item)
            if len(clean) > MAX_ALERT_IDS:
                raise CommandError(f"at most {MAX_ALERT_IDS} alert ids")
            row.history = (list(row.history or []) + [
                {"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": {"alert_bitrix_user_ids": [str(row.alert_user_ids()), str(clean)]}}
            ])[-100:]
            row.alert_bitrix_user_ids = clean
            row.save()
        self.stdout.write(f"assistant_enabled={row.assistant_enabled}")
        self.stdout.write(f"test_numbers={len(row.test_numbers or [])}")
        self.stdout.write(f"alert_ids={','.join(row.alert_user_ids()) or '-'}")
        self.stdout.write(f"key_configured={openai_client.configured()} model={openai_client.chat_model()}")
        self.stdout.write(f"paused_until={row.paused_until or '-'} last_sweep_at={row.last_sweep_at or '-'}")
