"""Copies the conversations that already exist into their CRM records.

The live mirror only catches messages sent from the moment it was switched on.
Everything before that is in the panel and nowhere else, which is the half of
the history a manager opening a lead actually wants — the enquiry that started
it, not only what happened since this afternoon.

Runs oldest first, so a timeline reads in the order the conversation happened.

Nothing is posted twice: every message that goes across is recorded in
``Mirror``, and a second run skips what the first one did. That matters more
than it sounds — Bitrix will happily hold a hundred copies of the same line and
has no idea any of them is a duplicate.

Dry run by default. This writes into a live CRM that people are working in, and
a command that starts writing the moment it is typed is the wrong shape for
that.
"""

import time

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.crmlink import client
from apps.crmlink.models import Mirror
from apps.crmlink.tasks import _line, _record_for
from apps.inbox.models import Conversation, Message

# Bitrix answers about two requests a second before it starts refusing. This is
# slower than it needs to be on purpose: the backfill is not in a hurry, and
# being throttled halfway through leaves a half-copied timeline.
PAUSE_SECONDS = 0.6


class Command(BaseCommand):
    help = "Posts existing WhatsApp messages into the timeline of the lead or contact holding that number."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write",
            action="store_true",
            help="Actually post. Without this the command only reports what it would do.",
        )
        parser.add_argument(
            "--conversation",
            type=int,
            default=None,
            help="One conversation only, by id. Useful for trying it on a single thread first.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after this many messages. 0 means no limit.",
        )

    def handle(self, *args, **options):
        if not client.configured():
            self.stderr.write("BITRIX_WEBHOOK_URL is not set — nothing to do.")
            return

        write = options["write"]
        conversations = Conversation.objects.select_related("contact").annotate(
            total=Count("messages")
        ).filter(total__gt=0)
        if options["conversation"]:
            conversations = conversations.filter(pk=options["conversation"])

        already = set(Mirror.objects.values_list("message_id", flat=True))

        matched = skipped = posted = failed = 0
        no_record = []

        for conversation in conversations.order_by("pk"):
            record = _record_for(conversation)
            if not record:
                no_record.append(conversation.contact.wa_id)
                continue

            matched += 1
            messages = list(
                Message.objects.filter(conversation=conversation)
                .select_related("sent_by")
                .order_by("created_at", "id")
            )
            pending = [m for m in messages if m.pk not in already]
            skipped += len(messages) - len(pending)

            self.stdout.write(
                f"{conversation.contact.wa_id} -> {record['type']} {record['id']}: "
                f"{len(pending)} to post, {len(messages) - len(pending)} already there"
            )

            if not write:
                continue

            for message in pending:
                if options["limit"] and posted >= options["limit"]:
                    break
                try:
                    comment_id = client.add_comment(record["type"], record["id"], _line(message))
                except client.BitrixError as exc:
                    failed += 1
                    self.stderr.write(f"  message {message.pk}: {exc}")
                    continue

                Mirror.objects.get_or_create(
                    message_id=message.pk,
                    defaults={
                        "entity_type": record["type"],
                        "entity_id": record["id"],
                        "comment_id": comment_id if isinstance(comment_id, int) else None,
                    },
                )
                posted += 1
                time.sleep(PAUSE_SECONDS)

            if options["limit"] and posted >= options["limit"]:
                break

        self.stdout.write("")
        self.stdout.write(f"conversations with a CRM record : {matched}")
        self.stdout.write(f"conversations without one       : {len(no_record)}")
        self.stdout.write(f"messages already mirrored       : {skipped}")
        if write:
            self.stdout.write(f"messages posted                 : {posted}")
            self.stdout.write(f"messages that failed            : {failed}")
        else:
            self.stdout.write("")
            self.stdout.write("Nothing was written. Add --write to post.")
