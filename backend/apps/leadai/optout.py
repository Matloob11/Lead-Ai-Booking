"""The global WhatsApp opt-out registry (board T60, owner's choice Q8: block the phone
on every number and campaign).

- ``phones_blocked(phones)``: the campaigns' hook (campaigns/crm_leads.py
  phones_blocked_by_registry imports this module and calls it with a set of
  phone strings, then reads each returned value's digits). It answers with the
  blocked ones among them, each as the digits it was given and in its canonical
  form, so the hook's own comparison (by digits, or by its normalised phone)
  finds every one of them.
- ``record(phone, reason, source)``: a phone that asked us to stop. Written on
  every Lead AI stop, spam or wrong number (engine.record_opt_out), when a person
  sets Opted out or WhatsApp Opt-out in Bitrix (bitrix_status.py), inbox-wide
  when an inbound message is a STOP or a wrong number by the rules, or an
  Unsubscribe / Stop / Stop messages / Stop promotions tap (signals.py), and by
  the back-fill command (leadai_optout_import).
- ``message_opt_out(message)``: which inbound messages count (pure).
- ``ambiguous(message)`` and ``answers_campaign(message)``: a few typed stop
  words mean something else as often as a stop outside a Lead AI chat: a bare
  "الغاء" / "إلغاء" cancels a booked viewing or a renewal, "block" names a
  building's block, "band karo" asks to switch something off. Inbox-wide they
  count only as the customer's answer to a campaign's template, the way a
  marketing message offers them. A Lead AI chat's own turn reads them knowing
  whether a meeting is booked (engine._item_opt_out).

A row is never overwritten: the first reason stays. Deleting one in the Django
admin lets the phone be messaged again, and writes nothing to Bitrix.
"""

from __future__ import annotations

import logging

from django.db import DatabaseError, IntegrityError, transaction

from .assistant import rules
from .models import LeadAiOptOut

logger = logging.getLogger(__name__)

Source = LeadAiOptOut.Source
REASON_MAX = 255
# Not a stop: "not interested" declines one offer (engine.STOP_KINDS says the same).
KINDS = (rules.STOP_ALL, rules.WRONG_NUMBER)
# Typed stop words that are as often something else outside a Lead AI chat (see the module note),
# with the bare "cancel" words a booked meeting gives (rules.MEETING_CANCEL).
AMBIGUOUS = frozenset(rules.normalize_text(word) for word in ("الغاء", "إلغاء", "block", "band karo", "بند کریں", "बंद करो")) | rules.MEETING_CANCEL


def digits(raw) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def canonical(raw) -> str:
    """The phone as WhatsApp ids are stored: digits, country code first; '' when it is none.

    A leading 00 (the international prefix) is dropped, and a UAE mobile written
    locally (05x xxx xxxx, or 5x xxx xxxx) gets its 971, as the campaigns read one.
    """
    text = digits(raw)
    if text.startswith("00"):
        text = text[2:]
    if text.startswith("05") and len(text) == 10:
        text = "971" + text[1:]
    elif text.startswith("5") and len(text) == 9:
        text = "971" + text
    return text if 8 <= len(text) <= 15 else ""


def phones_blocked(phones) -> set[str]:
    """The phones among these that the registry blocks (see the module note)."""
    given: dict[str, set[str]] = {}
    for raw in phones or ():
        key = canonical(raw)
        if key:
            given.setdefault(key, set()).update({key, digits(raw)})
    if not given:
        return set()
    found = set(LeadAiOptOut.objects.filter(phone__in=list(given)).values_list("phone", flat=True))
    out: set[str] = set()
    for key in found:
        out |= given[key]
    return {phone for phone in out if phone}


def is_blocked(phone) -> bool:
    key = canonical(phone)
    return bool(key) and LeadAiOptOut.objects.filter(phone=key).exists()


def source_for(kind: str) -> str:
    """The registry source of a Lead AI opt-out kind."""
    return {rules.WRONG_NUMBER: Source.WRONG_NUMBER, rules.SPAM: Source.LEADAI_SPAM}.get(kind, Source.LEADAI_STOP)


def _reason(text) -> str:
    """The customer's words (or ours), on one line, no markup."""
    line = " ".join(str(text or "").split())
    return line.translate(str.maketrans({"<": "‹", ">": "›", "[": "(", "]": ")"}))[:REASON_MAX]


def record(phone, reason: str = "", source: str = Source.LEADAI_STOP, conversation=None) -> bool:
    """Block this phone everywhere; True when it was not blocked before. Never raises."""
    key = canonical(phone)
    if not key:
        return False
    if source not in Source.values:
        source = Source.LEADAI_STOP
    try:
        with transaction.atomic():
            _, created = LeadAiOptOut.objects.get_or_create(
                phone=key,
                defaults={
                    "reason": _reason(reason),
                    "source": source,
                    "conversation_id": getattr(conversation, "pk", None),
                },
            )
    except IntegrityError:
        return False  # recorded a moment ago by another worker
    except DatabaseError:
        logger.exception("Lead AI could not record the opt-out of a phone")
        return False
    if created:
        logger.info("Lead AI opt-out registry: +%s blocked (%s)", key, source)
    return created


def release_for_resume(conversation, stop_reason: str) -> bool:
    """Resume AI on a chat the assistant itself stopped as spam or as a wrong number: both are code's
    reading (rules.looks_like_spam, "wrong no..." opening a message), so the registry row that stop
    wrote from this chat goes too, and campaigns reach the phone again. A STOP the customer asked
    for stays on the registry; only deleting it in the Django admin undoes it. True when a row went."""
    kind = {rules.SPAM: rules.SPAM, rules.WRONG_NUMBER: rules.WRONG_NUMBER}.get(str(stop_reason or ""))
    if kind is None:
        return False
    phone = canonical(conversation.contact.wa_id)
    if not phone:
        return False
    deleted, _ = LeadAiOptOut.objects.filter(phone=phone, conversation_id=conversation.pk, source=source_for(kind)).delete()
    if deleted:
        logger.info("Lead AI opt-out registry: +%s released by Resume AI (%s)", phone, stop_reason)
    return bool(deleted)


def _tap_label(message) -> str:
    payload = message.payload if isinstance(message.payload, dict) else {}
    if message.kind == "button":
        return str((payload.get("button") or {}).get("text") or message.body or "").strip()
    interactive = payload.get("interactive") or {}
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    return str(reply.get("title") or message.body or "").strip()


def message_opt_out(message) -> str:
    """The opt-out an inbound message is, by the rules every chat shares: a STOP or a
    wrong number typed (rules.opt_out_from_text), or a tap on Unsubscribe, Stop,
    Stop messages or Stop promotions; else ''. "Not interested" is not one."""
    if getattr(message, "direction", "") != "in":
        return ""
    if message.kind in ("button", "interactive"):
        label = _tap_label(message)
        kind = rules.opt_out_from_button(label) or rules.shops_opt_out(label)
        return kind if kind == rules.STOP_ALL else ""
    if message.kind == "text":
        kind = rules.opt_out_from_text(message.body or "")
        return kind if kind in KINDS else ""
    return ""


def inbox_source(kind: str) -> str:
    return Source.WRONG_NUMBER if kind == rules.WRONG_NUMBER else Source.INBOX_TAP


def is_tap(message) -> bool:
    return getattr(message, "kind", "") in ("button", "interactive")


def ambiguous(message) -> bool:
    """A typed stop that is a stop inbox-wide only as the answer to a campaign (AMBIGUOUS): "الغاء",
    "block", "band karo", with at most one polite word beside it ("please")."""
    if getattr(message, "kind", "") != "text":
        return False
    words = rules.normalize_text(message.body or "")
    if not words:
        return False
    heads = {words} | {words.removeprefix(filler + " ") for filler in rules.FILLERS}
    candidates = heads | {head.removesuffix(" " + filler) for head in heads for filler in rules.FILLERS}
    return bool(candidates & AMBIGUOUS)


def answers_campaign(message) -> bool:
    """Our side's last message before this one in the chat is a template a campaign of this chat
    sent (its CampaignRecipient rows say which): the customer is answering that campaign."""
    from apps.inbox.models import Message

    from .assistant import transcript

    previous = (
        Message.objects.filter(conversation_id=message.conversation_id, direction=Message.Direction.OUTBOUND, pk__lt=message.pk)
        .exclude(kind=Message.Kind.SYSTEM)
        .exclude(mirrored_from__isnull=False)
        .order_by("-pk")
        .only("kind", "template_id")
        .first()
    )
    if previous is None or previous.kind != Message.Kind.TEMPLATE or not previous.template_id:
        return False
    return previous.template_id in transcript.campaign_template_ids(message.conversation_id)


def counts(message) -> str:
    """The opt-out this inbound message is inbox-wide, else '': message_opt_out, and an ambiguous
    word only as the answer to a campaign (queries the chat for that one case)."""
    kind = message_opt_out(message)
    if kind and ambiguous(message) and not answers_campaign(message):
        return ""
    return kind
