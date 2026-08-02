"""Rebuild every free-form window from the customer's own last message.

Sending a template used to open the window, which Meta does not do: only an
inbound message starts the 24 hours. Conversations touched by that are sitting
on a window that looks open and is not, so the panel invites the agent to type
a message Meta will refuse with 131047.

The truth is recoverable — the newest inbound message in each chat is exactly
what the window should have been counted from — so the rows are recomputed
rather than merely cleared.
"""

from datetime import timedelta

from django.db import migrations


def repair(apps, schema_editor):
    Conversation = apps.get_model("inbox", "Conversation")
    Message = apps.get_model("inbox", "Message")

    for conversation in Conversation.objects.all().iterator():
        newest = (
            Message.objects.filter(conversation=conversation, direction="in")
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        conversation.last_inbound_at = newest
        # 24h is the setting's default; a migration must not read live settings,
        # which may have moved on since this ran.
        conversation.session_expires_at = newest + timedelta(hours=24) if newest else None
        conversation.save(update_fields=["last_inbound_at", "session_expires_at"])


def noop(apps, schema_editor):
    """Nothing to undo — the repaired values are the correct ones."""


class Migration(migrations.Migration):

    dependencies = [("inbox", "0008_message_is_starred")]

    operations = [migrations.RunPython(repair, noop)]
