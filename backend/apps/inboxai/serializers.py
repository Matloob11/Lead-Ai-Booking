from .eligibility import CONTEXT_MAX
from .reply import configured


def _iso(value):
    return value.isoformat() if value else None


def serialize_desk(desk):
    selected = list(
        desk.selected.select_related("contact").order_by("-last_message_at")[:80]
    )
    return {
        "enabled": desk.enabled,
        "scope": desk.scope,
        "context": (desk.context or "")[:CONTEXT_MAX],
        "updated_at": _iso(desk.updated_at),
        "selected": [serialize_candidate(row) for row in selected],
        "openai_configured": configured(),
    }


def serialize_cover(cover, *, origin=None, openai_configured=None):
    if cover is None:
        return {
            "enabled": False,
            "context": "",
            "paused_at": None,
            "origin": origin,
            "openai_configured": configured() if openai_configured is None else openai_configured,
        }
    return {
        "enabled": cover.enabled,
        "context": (cover.context or "")[:CONTEXT_MAX],
        "paused_at": _iso(cover.paused_at),
        "origin": origin,
        "openai_configured": configured() if openai_configured is None else openai_configured,
    }


def serialize_candidate(conversation):
    contact = conversation.contact
    name = (
        (getattr(contact, "display_name", None) or "")
        or (getattr(contact, "profile_name", None) or "")
        or (getattr(contact, "wa_id", None) or "")
    )
    return {
        "id": conversation.pk,
        "name": name,
        "wa_id": getattr(contact, "wa_id", "") or "",
        "preview": conversation.last_message_preview or "",
        "last_message_at": _iso(conversation.last_message_at),
    }


def serialize_health_row(row):
    conversation = row.conversation
    contact = conversation.contact
    number = conversation.number
    name = (
        (getattr(contact, "display_name", None) or "")
        or (getattr(contact, "profile_name", None) or "")
        or (getattr(contact, "wa_id", None) or "")
    )
    number_label = (getattr(number, "label", None) or "") or (getattr(number, "phone_number", None) or "")
    return {
        "conversation_id": conversation.pk,
        "name": name,
        "wa_id": getattr(contact, "wa_id", "") or "",
        "number": number_label,
        "colour": row.colour or None,
        "reason": row.reason or "",
        "colour_locked": bool(row.colour_locked),
        "updated_at": _iso(row.updated_at),
    }
