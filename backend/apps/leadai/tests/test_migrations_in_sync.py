"""Every model change has its migration in the repo (CLAUDE.md: a migration that exists in one place only has bitten this
project twice). The same check as ops/wa.sh django-check, but on the image under test, before it is up."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class MigrationsInSyncTests(TestCase):
    def test_makemigrations_check_finds_nothing(self):
        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"a model change has no migration:\n{out.getvalue()}")
        self.assertIn("No changes detected", out.getvalue())
