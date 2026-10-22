"""Reconnect again (apps/leadai/reconnect.py; Matloob 2026-10-22): the mixed campaign's customers who never said no get
one more template, so the assistant can talk to them.

    python manage.py leadai_reconnect_again --campaigns 549,550,551,552,553             the audience, nothing sent
    python manage.py leadai_reconnect_again --campaigns 549,550 --show 20               with sample rows (phones masked)
    python manage.py leadai_reconnect_again --campaigns 549,550 --send [--limit 200]    the sends, in Template B's hours

Who goes where is reconnect.audience: in the chat (the campaign reached them and nothing says no), fresh (the campaign
never messaged them: the popup's path on the lead as Bitrix holds it now), or out with the reason. --agent is the Bitrix
user id the fresh campaigns are sent as (Matloob, 2311); --quiet-hours how long a customer must have been quiet.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Agent
from apps.leadai import followups, reconnect
from apps.leadai.models import LeadAiSettings


def masked(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return f"{digits[:3]}{'*' * max(0, len(digits) - 6)}{digits[-3:]}" if len(digits) >= 7 else "***"


class Command(BaseCommand):
    help = "Reconnect again: the mixed campaign's customers who never said no get one more template (a dry run unless --send)."

    def add_arguments(self, parser):
        parser.add_argument("--campaigns", required=True, metavar="549,550,...", help="The Lead AI campaigns' ids, comma-separated.")
        parser.add_argument("--send", action="store_true", help="Send (the default lists the audience and sends nothing).")
        parser.add_argument("--limit", type=int, default=0, help="At most this many sends in this run (the chats first).")
        parser.add_argument("--quiet-hours", type=int, default=reconnect.QUIET_HOURS, help="A customer who wrote within these hours is left alone.")
        parser.add_argument("--agent", default="2311", metavar="BITRIX_ID", help="The Bitrix user the fresh campaigns are sent as.")
        parser.add_argument("--any-hour", action="store_true", help="Send outside Template B's hours (11:00-18:00 Dubai, Monday to Saturday).")
        parser.add_argument("--show", type=int, default=0, help="List this many rows per group, phones masked.")

    def handle(self, *args, **options):
        try:
            ids = sorted({int(part) for part in str(options["campaigns"]).split(",") if part.strip()})
        except ValueError as exc:
            raise CommandError(f"--campaigns takes numbers: {exc}") from exc
        if not ids:
            raise CommandError("--campaigns names no campaign")
        now = timezone.now()
        quiet = max(1, int(options["quiet_hours"] or reconnect.QUIET_HOURS))
        rows = reconnect.audience(ids, now, quiet_hours=quiet)
        if not rows:
            raise CommandError(f"no recipient of a Lead AI campaign among {ids}")
        counts = reconnect.summary(rows)
        self.stdout.write(f"campaigns {','.join(str(pk) for pk in ids)}: {counts['recipients']} recipients")
        self.stdout.write(f"  in the chat: {counts[reconnect.CHAT]}  (the second template inside the same chat, from the same number)")
        self.stdout.write(f"  fresh: {counts[reconnect.FRESH]}  (never messaged: a Lead AI campaign on the original number)")
        for why, count in sorted(counts["out"].items(), key=lambda item: -item[1]):
            self.stdout.write(f"  out, {why}: {count}")
        show = int(options["show"] or 0)
        if show:
            for path in (reconnect.CHAT, reconnect.FRESH):
                self.stdout.write(f"--- {path} (first {show})")
                for row in [row for row in rows if row.path == path][:show]:
                    extra = f" chat {row.conversation.pk}" if row.conversation is not None else ""
                    self.stdout.write(f"  lead {row.lead_id} {masked(row.phone)} campaign {row.recipient.campaign_id}{extra}")
        numbers = {row.recipient.campaign.number for row in rows if row.path}
        without = sorted(str(number.phone_number) for number in numbers if reconnect.approved_template(number) is None)
        if without:
            self.stdout.write(self.style.WARNING(f"no approved {reconnect.ic_templates.AGAIN_NAME} on: {', '.join(without)}"))
        if not options["send"]:
            self.stdout.write("dry run: nothing sent (--send to send)")
            return
        settings_row = LeadAiSettings.load()
        if not options["any_hour"] and not followups.send_hours(now, settings_row.closed_dates):
            raise CommandError("outside Template B's hours (11:00-18:00 Dubai, Monday to Saturday): --any-hour to send anyway")
        if followups.credit_out():
            raise CommandError("the gateway is out of credit")
        if len(without) == len(numbers):
            raise CommandError("the template is not approved on any of the numbers")
        agent = Agent.objects.filter(bitrix_user_id=str(options["agent"]).strip(), is_active=True).first()
        if agent is None:
            raise CommandError(f"no active agent for Bitrix user {options['agent']}")
        result = reconnect.send(rows, agent, limit=max(0, int(options["limit"] or 0)), now=now)
        self.stdout.write(f"chats: {result['chat_sent']} sent, {result['chat_failed']} not sent")
        failed = {}
        for row in rows:
            if row.path == reconnect.CHAT and row.result and row.result != "sent":
                failed[row.result] = failed.get(row.result, 0) + 1
        for why, count in sorted(failed.items(), key=lambda item: -item[1]):
            self.stdout.write(f"  {why}: {count}")
        for report in result["fresh"]:
            line = f"fresh from {report['number']}: campaign {report['campaign_id']}, {report['sent']} queued"
            if report["skipped"]:
                reasons = {}
                for item in report["skipped"]:
                    reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
                line += "; skipped " + ", ".join(f"{count} {why}" for why, count in sorted(reasons.items(), key=lambda item: -item[1]))
            if report["error"]:
                line += f"; ERROR {report['error']}"
            self.stdout.write(line)
