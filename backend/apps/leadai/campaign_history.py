"""Lead AI Campaigns history (Tools → Campaigns): serialize Lead AI campaigns with
queue counts and Message delivered/read aggregates.

Only campaigns with a ``LeadAiCampaign`` row. Delivered/read come from the template
``Message`` matched to each sent recipient (same idea as ``ops/catalog/probe-leadai-funnel.py``:
same chat, same template, created near ``sent_at``).
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.campaigns.models import MAX_SEND_ATTEMPTS, RETRY_AFTER_MINUTES, Campaign, CampaignRecipient
from apps.campaigns.services import recipient_counts
from apps.inbox.models import Message

# Probe window: process_recipient stamps sent_at just after the gateway accepts.
MATCH_BEFORE = dt.timedelta(minutes=10)
MATCH_AFTER = dt.timedelta(minutes=1)

LIST_LIMIT_DEFAULT = 50
LIST_LIMIT_MAX = 100


def can_view(user) -> bool:
    """Anyone with Lead AI access, or a panel admin who sees every inbox chat.

    Uses ``Agent.can_lead_ai`` directly (not ``lane.has_desk_access``): round 25 may
    re-point the desk gate at ``LeadAiAccess`` before its migration is applied.
    """
    from apps.inbox.visibility import sees_all_inbox_chats

    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if sees_all_inbox_chats(user):
        return True
    return bool(getattr(user, "can_lead_ai", False) and getattr(user, "can_official_api", True))


def lead_ai_campaigns_qs():
    """Newest Lead AI campaigns first, with the bits serialize needs."""
    return (
        Campaign.objects.filter(lead_ai__isnull=False)
        .select_related(
            "number",
            "template",
            "created_by",
            "lead_ai",
        )
        .order_by("-created_at", "-id")
    )


def delivery_counts(campaigns) -> dict[int, dict[str, int]]:
    """Per campaign id: ``{delivered, read}`` from matched outbound template messages.

    A recipient without a conversation or without a matching message contributes 0.
    Read implies delivered.
    """
    campaigns = list(campaigns)
    out = {c.pk: {"delivered": 0, "read": 0} for c in campaigns}
    if not campaigns:
        return out

    by_id = {c.pk: c for c in campaigns}
    template_by_campaign = {c.pk: c.template_id for c in campaigns}

    sent_rows = list(
        CampaignRecipient.objects.filter(
            campaign_id__in=by_id,
            status=CampaignRecipient.Status.SENT,
            conversation_id__isnull=False,
            sent_at__isnull=False,
        ).values_list("campaign_id", "conversation_id", "sent_at")
    )
    if not sent_rows:
        return out

    chat_ids = {chat for _cid, chat, _sent in sent_rows if chat}
    template_ids = {tid for tid in template_by_campaign.values() if tid}
    if not chat_ids or not template_ids:
        return out

    # All candidate template messages on those chats (one pass).
    messages: dict[int, list] = {}
    for pk, chat, tpl, created_at, status, delivered_at, read_at in (
        Message.objects.filter(
            conversation_id__in=chat_ids,
            direction=Message.Direction.OUTBOUND,
            kind=Message.Kind.TEMPLATE,
            template_id__in=template_ids,
        )
        .values_list(
            "id",
            "conversation_id",
            "template_id",
            "created_at",
            "status",
            "delivered_at",
            "read_at",
        )
        .iterator(chunk_size=2000)
    ):
        messages.setdefault(chat, []).append((pk, tpl, created_at, status, delivered_at, read_at))

    used: set[int] = set()
    for campaign_id, chat, sent_at in sorted(sent_rows, key=lambda r: (r[0], r[2] or timezone.now())):
        want_tpl = template_by_campaign.get(campaign_id)
        if not want_tpl or not chat or not sent_at:
            continue
        match = None
        for row in messages.get(chat) or ():
            pk, tpl, created_at, status, delivered_at, read_at = row
            if pk in used or tpl != want_tpl:
                continue
            if not (sent_at - MATCH_BEFORE <= created_at <= sent_at + MATCH_AFTER):
                continue
            match = row
            break
        if match is None:
            continue
        pk, _tpl, _created, status, delivered_at, read_at = match
        used.add(pk)
        is_read = status == Message.Status.READ or read_at is not None
        is_delivered = (
            is_read
            or status == Message.Status.DELIVERED
            or delivered_at is not None
        )
        if is_delivered:
            out[campaign_id]["delivered"] += 1
        if is_read:
            out[campaign_id]["read"] += 1
    return out


def serialize(campaign: Campaign, *, delivery: dict | None = None) -> dict:
    """One Lead AI campaign row for the Campaigns dialog."""
    counts = recipient_counts(campaign)
    lead = getattr(campaign, "lead_ai", None)
    delivery = delivery or {"delivered": 0, "read": 0}
    creator = campaign.created_by
    return {
        "id": campaign.pk,
        "name": campaign.name,
        "status": campaign.status,
        "number_id": campaign.number_id,
        "number": campaign.number.phone_number if campaign.number_id else "",
        "number_title": campaign.number.title if campaign.number_id else "",
        "template_id": campaign.template_id,
        "template_name": campaign.template.name if campaign.template_id else "",
        "playbook": getattr(lead, "playbook", "") or "",
        "community": getattr(lead, "community", "") or "",
        "created_by": {
            "id": creator.pk,
            "display_name": getattr(creator, "display_name", "") or creator.get_username(),
        }
        if creator_id_safe(creator)
        else None,
        "total": campaign.total,
        "sent": counts["sent"],
        "failed": counts["failed"],
        "retrying": counts["retrying"],
        "pending": counts["pending"],
        "skipped": counts["skipped"],
        "delivered": int(delivery.get("delivered") or 0),
        "read": int(delivery.get("read") or 0),
        "max_attempts": MAX_SEND_ATTEMPTS,
        "retry_after_minutes": RETRY_AFTER_MINUTES,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "finished_at": campaign.finished_at.isoformat() if campaign.finished_at else None,
        "error_detail": campaign.error_detail or "",
    }


def creator_id_safe(creator) -> bool:
    return creator is not None and getattr(creator, "pk", None)


def serialize_many(campaigns) -> list[dict]:
    campaigns = list(campaigns)
    delivery = delivery_counts(campaigns)
    return [serialize(c, delivery=delivery.get(c.pk)) for c in campaigns]
