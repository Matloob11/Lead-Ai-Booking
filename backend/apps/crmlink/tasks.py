"""Putting the WhatsApp conversation where the CRM can see it.

Two jobs, both out of band. Nothing here may delay a message reaching an agent,
and nothing here may lose one either: if Bitrix is down, the message is already
stored and only its copy in the timeline is missing.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.inbox.models import Conversation, Message

from . import client, summary as ai

logger = logging.getLogger(__name__)

# Where the pinned summary lives on a lead or contact. Created by
# `manage.py setup_crm_fields`, which is safe to run again.
FIELD_SUMMARY = "UF_CRM_WA_SUMMARY"
FIELD_CLIENT = "UF_CRM_WA_CLIENT_SCORE"
FIELD_AGENT = "UF_CRM_WA_AGENT_SCORE"

# Contacts get their own copies of the same fields, under the portal's own
# naming for that entity.
CONTACT_FIELDS = {
    FIELD_SUMMARY: "UF_CRM_WA_SUMMARY",
    FIELD_CLIENT: "UF_CRM_WA_CLIENT_SCORE",
    FIELD_AGENT: "UF_CRM_WA_AGENT_SCORE",
}


def _record_for(conversation):
    """The CRM record this customer's number belongs to, if any.

    Cached on the conversation would be faster, but a lead can be created after
    the first message — which is the normal order of things when a customer
    writes before anybody has entered them — so it is asked each time.
    """
    return client.find_record(conversation.contact.wa_id)


def _line(message):
    """One message, as the timeline should read it."""
    who = "Customer" if message.direction == Message.Direction.INBOUND else "Agent"
    if message.direction == Message.Direction.OUTBOUND and message.sent_by:
        who = f"Agent · {message.sent_by.display_name or message.sent_by.get_username()}"

    body = (message.body or "").strip()
    if not body:
        body = f"[{message.get_kind_display().lower()}]"
    elif message.kind != Message.Kind.TEXT:
        body = f"[{message.get_kind_display().lower()}] {body}"

    stamp = timezone.localtime(message.created_at).strftime("%d %b %H:%M")
    return f"WhatsApp · {who} · {stamp}\n{body}"


@shared_task(ignore_result=True)
def mirror_message(message_id):
    """Copies one message into the CRM record's timeline."""
    if not client.configured():
        return

    message = Message.objects.select_related(
        "conversation__contact", "sent_by"
    ).filter(pk=message_id).first()
    if not message:
        return

    record = _record_for(message.conversation)
    if not record:
        # No lead and no contact for this number. Deliberately silent: the
        # customer simply is not in the CRM, which is not an error.
        return

    try:
        client.add_comment(record["type"], record["id"], _line(message))
    except client.BitrixError as exc:
        logger.warning("Could not mirror message %s: %s", message_id, exc)
        return

    # Every Nth message, rewrite what the manager reads.
    total = Message.objects.filter(conversation_id=message.conversation_id).count()
    if settings.SUMMARY_EVERY_N_MESSAGES > 0 and total % settings.SUMMARY_EVERY_N_MESSAGES == 0:
        refresh_summary.delay(message.conversation_id)


@shared_task(ignore_result=True)
def refresh_summary(conversation_id):
    """Rewrites the pinned summary and the two scores."""
    if not (client.configured() and ai.configured()):
        return

    conversation = Conversation.objects.select_related("contact").filter(pk=conversation_id).first()
    if not conversation:
        return

    record = _record_for(conversation)
    if not record:
        return

    # The tail of the conversation. What somebody wants now matters more than
    # what they asked three weeks ago, and the whole thread would cost more per
    # call for an answer that is mostly about the end of it anyway.
    messages = list(
        Message.objects.filter(conversation_id=conversation_id)
        .order_by("-created_at", "-id")[: settings.SUMMARY_CONTEXT_MESSAGES]
    )
    messages.reverse()

    try:
        result = ai.summarise(messages)
    except ai.SummaryError as exc:
        logger.warning("Summary for conversation %s failed: %s", conversation_id, exc)
        return

    stamp = timezone.localtime().strftime("%d %b %Y %H:%M")
    pinned = (
        f"{result['summary']}\n\n"
        f"Customer {result['client_score']}/100 — {result['client_reason']}\n"
        f"Our handling {result['agent_score']}/100 — {result['agent_reason']}\n"
        f"(updated {stamp}, after {len(messages)} messages)"
    )

    try:
        client.update_fields(
            record["type"],
            record["id"],
            {
                FIELD_SUMMARY: pinned,
                FIELD_CLIENT: result["client_score"],
                FIELD_AGENT: result["agent_score"],
            },
        )
    except client.BitrixError as exc:
        logger.warning("Could not write the summary fields on %s: %s", record, exc)

    # And a timeline entry, so the summary's own history is readable — how a
    # customer's score moved is worth more than where it currently sits.
    try:
        client.add_comment(
            record["type"],
            record["id"],
            f"WhatsApp summary · updated\n{pinned}",
        )
    except client.BitrixError as exc:
        logger.warning("Could not post the summary comment on %s: %s", record, exc)
