"""Scheduled work for the inbox."""

import logging

from celery import shared_task
from django.utils import timezone

from .events import publish_to_agent
from .models import Conversation, Reminder
from .serializers import serialize_conversation

logger = logging.getLogger(__name__)


@shared_task
def fire_due_reminders():
    """Tell agents about follow-ups that have come due.

    Fired once and marked, so a reminder does not nag every minute. It stays
    open until the agent marks it done — an alert seen while busy would
    otherwise be an alert lost.
    """
    due = Reminder.objects.filter(
        is_done=False, fired_at__isnull=True, due_at__lte=timezone.now()
    ).select_related("conversation", "conversation__contact", "conversation__number")

    count = 0
    for reminder in due:
        publish_to_agent(
            reminder.agent_id,
            "reminder.due",
            {
                "id": reminder.pk,
                "note": reminder.note,
                "due_at": reminder.due_at.isoformat(),
                "conversation": serialize_conversation(reminder.conversation),
            },
        )
        reminder.fired_at = timezone.now()
        reminder.save(update_fields=["fired_at"])
        count += 1

    if count:
        logger.info("Fired %d reminder(s)", count)
    return count


@shared_task
def warn_closing_windows():
    """Flag chats whose free-form window is about to shut.

    Once it closes, saying anything at all costs a template and Meta's
    marketing cap may refuse it — so the hour before is the last cheap chance
    to reply.
    """
    now = timezone.now()
    soon = now + timezone.timedelta(hours=1)

    closing = Conversation.objects.filter(
        status=Conversation.Status.OPEN,
        is_archived=False,
        session_expires_at__gt=now,
        session_expires_at__lte=soon,
        assigned_agent__isnull=False,
    ).select_related("contact", "number", "assigned_agent")

    count = 0
    for conversation in closing:
        publish_to_agent(
            conversation.assigned_agent_id,
            "session.closing",
            {"conversation": serialize_conversation(conversation)},
        )
        count += 1

    return count
