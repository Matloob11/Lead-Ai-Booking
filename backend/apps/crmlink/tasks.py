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
from .models import Mirror

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


def _records_for(conversation):
    """Every CRM record this customer's number belongs to.

    Cached on the conversation would be faster, but a lead can be created after
    the first message — which is the normal order of things when a customer
    writes before anybody has entered them — so it is asked each time.
    """
    return client.find_records(conversation.contact.wa_id)


def _line_with_role(message, role):
    """Live timeline line, with Tenant or Owner when the chat came from Renewals."""
    line = _line(message)
    label = {"tenant": "Tenant", "owner": "Owner"}.get(str(role or "").strip().lower())
    if not label:
        return line
    return line.replace("WhatsApp · ", f"WhatsApp · {label} · ", 1)


def _renewal_deals(conversation):
    """Deals a Renewals campaign already messaged on this WhatsApp number.

    Looked up by the number we sent from and the customer's phone, so a later
    reply — from them or from an agent — lands on the same deal timeline.
    """
    from apps.campaigns.models import CampaignRecipient

    phone = "".join(ch for ch in str(getattr(conversation.contact, "wa_id", "") or "") if ch.isdigit())
    number_id = getattr(conversation, "number_id", None)
    if not phone or not number_id:
        return []
    found = {}
    rows = (
        CampaignRecipient.objects.filter(
            phone=phone,
            campaign__number_id=number_id,
            crm_deal_id__isnull=False,
        )
        .exclude(status=CampaignRecipient.Status.SKIPPED)
        .order_by("id")
    )
    for row in rows:
        found[int(row.crm_deal_id)] = row.crm_role or ""
    return [
        {"type": "deal", "id": deal_id, "kind": "deal", "role": role}
        for deal_id, role in found.items()
    ]


def _mirror_records(conversation):
    """Lead, contact, Owner Data, plus any Renewals deal this chat was sent to."""
    records = list(_records_for(conversation))
    seen = {(record["type"], record["id"]) for record in records}
    for record in _renewal_deals(conversation):
        key = (record["type"], record["id"])
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def _record_for(conversation):
    """The first of them, for the one caller that only wants somewhere to write."""
    records = _records_for(conversation)
    return records[0] if records else None


def _line(message):
    """One message, as the timeline should read it."""
    who = "Customer" if message.direction == Message.Direction.INBOUND else "Agent"
    if message.direction == Message.Direction.OUTBOUND and message.sent_by:
        who = f"Agent · {message.sent_by.display_name or message.sent_by.get_username()}"
    payload = message.payload if isinstance(message.payload, dict) else {}
    if message.direction == Message.Direction.OUTBOUND and str(payload.get("source") or "").startswith("leadai"):
        # Written by the Lead AI assistant, not by a person.
        who = "Lead AI assistant"

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

    records = _mirror_records(message.conversation)
    if not records:
        # Nothing in the CRM carries this number. Deliberately silent: the
        # customer simply is not entered anywhere, which is not an error.
        return

    # Per record, not per message. The same number can be on a lead and on an
    # Owner Data item, and one of them having the message already is no reason
    # to skip the other.
    done = set(
        Mirror.objects.filter(message_id=message.pk).values_list("entity_type", "entity_id")
    )

    for record in records:
        if (record["type"], record["id"]) in done:
            continue

        try:
            text = _line_with_role(message, record.get("role")) if record.get("type") == "deal" else _line(message)
            comment_id = client.add_comment(record["type"], record["id"], text)
        except client.BitrixError as exc:
            logger.warning("Could not mirror message %s to %s: %s", message_id, record, exc)
            continue

        # Recorded after the fact. The other order would mark a message as sent
        # across and then fail to send it, which is the one mistake this table
        # cannot recover from.
        Mirror.objects.get_or_create(
            message_id=message.pk,
            entity_type=record["type"],
            entity_id=record["id"],
            defaults={"comment_id": comment_id if isinstance(comment_id, int) else None},
        )

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

    records = _mirror_records(conversation)
    if not records:
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

    # A Lead AI chat (owner's choice, 2026-10-09): the summary is a comment
    # only. Every lead update re-runs Bitrix's Lead Automation, which plans a
    # new "Viewing/Meeting" to-do each time a lead sits in Meeting/Viewing
    # Scheduled, and the assistant's own messages make these chats busier.
    from apps.leadai.lane import is_lead_ai

    comment_only = is_lead_ai(conversation)

    for record in records:
        # The pinned fields exist on leads and contacts, where
        # `setup_crm_fields` created them. A smart-process item has no such
        # fields, so it gets the summary as a comment and nothing is written
        # into a field that is not there.
        if record["type"] in ("lead", "contact") and not comment_only:
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

        # And a timeline entry everywhere, so the summary's own history is
        # readable — how a customer's score moved is worth more than where it
        # currently sits.
        try:
            client.add_comment(
                record["type"],
                record["id"],
                f"WhatsApp summary · updated\n{pinned}",
            )
        except client.BitrixError as exc:
            logger.warning("Could not post the summary comment on %s: %s", record, exc)
