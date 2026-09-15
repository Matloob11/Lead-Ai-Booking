"""Shape-only helpers for Alots/Meta webhook blobs. No Django."""

from datetime import datetime, timezone as dt_timezone

ECHO_KEYS = ("smb_message_echoes", "message_echoes", "echoes")
MESSAGE_LIST_KEYS = ("messages",) + ECHO_KEYS
PLACEHOLDER_BODY = "Sent from WhatsApp"
GRAPH_MEDIA_KINDS = ("image", "document", "audio", "video", "sticker")


def digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def iso_to_unix(value):
    """Alots flat outbound uses ISO ``datetime``; Meta uses unix ``timestamp``."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return text
    try:
        cleaned = text.replace("Z", "+00:00")
        # fromisoformat rejects >6 fractional digits — trim extras.
        if "." in cleaned:
            head, rest = cleaned.split(".", 1)
            frac = ""
            tz = ""
            for i, ch in enumerate(rest):
                if ch.isdigit():
                    frac += ch
                else:
                    tz = rest[i:]
                    break
            cleaned = f"{head}.{frac[:6]}{tz}"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return str(int(dt.timestamp()))
    except ValueError:
        return ""


def _flat_has_message_body(payload):
    """True when a flat Alots row carries text/media content (not status-only)."""
    kind = str(payload.get("type") or "")
    if kind in GRAPH_MEDIA_KINDS and isinstance(payload.get(kind), dict):
        return True
    text = payload.get("text")
    if isinstance(text, dict) and (text.get("body") or "").strip():
        return True
    if isinstance(text, str) and text.strip():
        return True
    return bool((payload.get("body") or "").strip())


def is_alots_flat_outbound(payload):
    """True when Alots posts a single outbound message with body (not Meta envelope).

    ``phone_number_id`` is often missing on phone-app / some panel paths; we still
    accept the row and resolve the WABA number from ``from`` (our MSISDN) later.

    Coexistence / WBX channels (Alots 2026-08): same Cloud API send shape, sometimes
    without ``id`` / ``from`` — only ``to`` + ``type`` + ``text.body`` +
    ``messaging_product``. Those still carry the real body (vs status stubs).
    """
    if not isinstance(payload, dict) or payload.get("entry"):
        return False
    if not payload.get("type"):
        return False
    # Must look like a message we can store (has to/from and not a status-only row).
    if payload.get("status") and not payload.get("text") and payload.get("type") == "status":
        return False
    if not (payload.get("to") or payload.get("from")):
        return False
    if not _flat_has_message_body(payload):
        return False
    if payload.get("id"):
        return True
    # Coexistence send-shape sample: messaging_product + to + text, no wamid yet.
    return bool(
        payload.get("messaging_product") == "whatsapp"
        or payload.get("recipient_type")
        or payload.get("phone_number_id")
        or payload.get("from")
    )


def normalize_webhook_payload(payload):
    """Wrap Alots flat outbound-with-body into Meta ``entry/changes/value`` shape.

    Sample Alots body (2026-08-25)::

        {
          "to": "9186…", "from": "1555…", "type": "text",
          "text": {"body": "Hello"}, "id": "wamid.…",
          "phone_number_id": "1125…", "datetime": "2026-08-25T…"
        }

    Coexistence sample (body without id)::

        {
          "messaging_product": "whatsapp", "recipient_type": "individual",
          "to": "9194…", "type": "text",
          "text": {"preview_url": false, "body": "Hello"}
        }

    Phone/app path often omits ``phone_number_id`` and prefixes ``to`` with ``+``.
    We put it under ``smb_message_echoes`` so ingest treats it as outbound
    even when ``from`` is a Meta cloud display id rather than our MSISDN.
    """
    if not isinstance(payload, dict):
        return payload

    # Bare ``messages: [{… from_user_id …}]`` fragment Alots showed for coexistence.
    if (
        not payload.get("entry")
        and isinstance(payload.get("messages"), list)
        and payload["messages"]
        and not payload.get("statuses")
        and not is_alots_flat_outbound(payload)
    ):
        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": str(meta.get("phone_number_id") or ""),
                                    "display_phone_number": digits(meta.get("display_phone_number")),
                                },
                                "contacts": payload.get("contacts") or [],
                                "messages": payload["messages"],
                            },
                        }
                    ]
                }
            ],
        }

    if not is_alots_flat_outbound(payload):
        return payload

    blob = dict(payload)
    # Customer wa_id must be digits-only for Contact.wa_id uniqueness.
    if blob.get("to"):
        blob["to"] = digits(blob["to"]) or blob["to"]
    if not blob.get("timestamp"):
        unix = iso_to_unix(blob.get("datetime"))
        if unix:
            blob["timestamp"] = unix

    phone_number_id = str(blob.get("phone_number_id") or "")
    display = digits(blob.get("from")) or digits(blob.get("display_phone_number"))
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "phone_number_id": phone_number_id,
                                "display_phone_number": display,
                            },
                            "smb_message_echoes": [blob],
                        },
                    }
                ]
            }
        ],
    }


def is_group_recipient(wa_id):
    text = str(wa_id or "")
    return "@g.us" in text or "@broadcast" in text or text.endswith("@lid")


def is_our_sender(number, from_value, metadata=None):
    """True when ``from`` is this WABA number, not the customer."""
    from_digits = digits(from_value)
    if not from_digits:
        return False
    ours = {
        digits(getattr(number, "phone_number", "")),
        digits(getattr(number, "phone_number_id", "")),
        digits((metadata or {}).get("display_phone_number")),
        digits((metadata or {}).get("phone_number_id")),
    }
    ours.discard("")
    return from_digits in ours


def iter_message_blobs(value):
    """Yield (blob, force_outbound) from every known message array on ``value``."""
    for key in MESSAGE_LIST_KEYS:
        for blob in value.get(key) or []:
            yield blob, key != "messages"


def customer_wa_id(blob, number, metadata, profiles, outbound):
    if outbound:
        for key in ("to", "recipient", "recipient_id"):
            raw = blob.get(key)
            if raw and not is_our_sender(number, raw, metadata):
                return digits(raw) or str(raw).split("@")[0]
        for wa_id in profiles:
            if wa_id and not is_our_sender(number, wa_id, metadata):
                return digits(wa_id) or wa_id
        return ""
    raw = blob.get("from") or ""
    return digits(raw) or raw


def extract_graph_message_text(blob):
    """Pull a display body and kind out of a Meta/Alots message object."""
    if not isinstance(blob, dict):
        return "", ""
    if isinstance(blob.get("messages"), list) and blob["messages"]:
        return extract_graph_message_text(blob["messages"][0])
    if isinstance(blob.get("data"), dict):
        return extract_graph_message_text(blob["data"])
    if isinstance(blob.get("message"), dict):
        return extract_graph_message_text(blob["message"])

    kind = blob.get("type") or ""
    text = blob.get("text")
    if isinstance(text, dict):
        body = (text.get("body") or "").strip()
        if body:
            return body, kind or "text"
    if isinstance(text, str) and text.strip():
        return text.strip(), kind or "text"
    body = (blob.get("body") or blob.get("caption") or "").strip()
    if isinstance(body, str) and body and kind in ("", "text"):
        return body, "text"
    if kind in GRAPH_MEDIA_KINDS:
        part = blob.get(kind) if isinstance(blob.get(kind), dict) else {}
        cap = (part.get("caption") or "").strip()
        return cap or f"[{kind}]", kind
    if kind == "location":
        return "[location]", kind
    if kind == "contacts":
        return "[contact]", kind
    if kind == "interactive":
        interactive = blob.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        title = (reply.get("title") or "").strip()
        return title or "[interactive]", kind
    return "", kind


def live_chat_preview(row):
    """Display body from one Alots Live Agent ``chatList`` row."""
    if not isinstance(row, dict):
        return "", ""
    kind = str(row.get("messageType") or "text").strip().lower() or "text"
    text = str(row.get("messageText") or "").strip()
    if text:
        return text, kind
    if kind in GRAPH_MEDIA_KINDS:
        return f"[{kind}]", kind
    if kind in ("location", "contacts", "interactive"):
        return f"[{kind}]", kind
    return "", kind


def preview_for_wamid(chat_list, wamid):
    want = str(wamid or "").strip()
    if not want:
        return "", ""
    for row in chat_list or []:
        mid = str((row or {}).get("messageId") or "").strip()
        if mid and mid == want:
            return live_chat_preview(row)
    return "", ""

