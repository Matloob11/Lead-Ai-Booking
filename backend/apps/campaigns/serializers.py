from .models import MAX_SEND_ATTEMPTS, RETRY_AFTER_MINUTES, Campaign, CampaignRecipient
from .services import recipient_counts


def serialize_campaign(campaign: Campaign) -> dict:
    counts = recipient_counts(campaign)
    return {
        "id": campaign.pk,
        "name": campaign.name,
        "status": campaign.status,
        "number_id": campaign.number_id,
        "number": campaign.number.phone_number,
        "template_id": campaign.template_id,
        "template_name": campaign.template.name,
        "total": campaign.total,
        "sent": counts["sent"],
        "failed": counts["failed"],
        "retrying": counts["retrying"],
        "pending": counts["pending"],
        "skipped": counts["skipped"],
        "max_attempts": MAX_SEND_ATTEMPTS,
        "retry_after_minutes": RETRY_AFTER_MINUTES,
        "created_at": campaign.created_at.isoformat(),
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "finished_at": campaign.finished_at.isoformat() if campaign.finished_at else None,
        "error_detail": campaign.error_detail,
    }


def serialize_recipient(row: CampaignRecipient) -> dict:
    return {
        "id": row.pk,
        "phone": row.phone,
        "name": row.name,
        "status": row.status,
        "owner_data_id": row.owner_data_id,
        "owner_data_created": row.owner_data_created,
        "conversation_id": row.conversation_id,
        "error_detail": row.error_detail,
        "attempt_count": row.attempt_count,
        "max_attempts": MAX_SEND_ATTEMPTS,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    }
