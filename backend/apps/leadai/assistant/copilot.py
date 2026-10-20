"""The co-pilot: while a person has the chat, what the assistant would have said, kept for the agent (Matloob,
2026-10-20: the handover becomes a co-pilot, not silence; the advance plan's workstream D).

- The draft is the model's own reply of that turn — the words code did not send because the chat is handed over (the
  holding line goes instead), or because this very turn handed it over. engine._run_claimed keeps the model's reply on
  the answer (``copilot_draft``) with the turn's context for the amount filter (``copilot_context``); engine._apply
  stores it on the chat's state (``draft``) through ``remember``. No second model call.
- ``kind``: PERSON when the handover reason is one a person must answer (a call asked for, a person asked for, upset,
  legal, a broker) — the agent decides, nothing goes by itself; ORDINARY otherwise (a question the rules handed over,
  "unclear"): the agent sends, edits or drops it, and after LeadAiSettings.copilot_auto_send_minutes with nobody writing
  it goes by itself (``auto_send``, from the sweep), so a customer never waits an hour for an ordinary answer again
  (the first mixed campaign: 42 hand-over alerts answered 40–80 minutes late or never).
- Ask AI (``ask``): the agent's own question about the chat, or "write me a reply", answered from the chat's lines
  and the facts, as a draft with the question kept (one model call, ASK_SYSTEM).
- Every draft's fate is recorded (LeadAiDraftOutcome: sent as it was, edited, sent by itself, dismissed), with the
  agent's final words: the raw material of the knowledge base.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import LeadAiChatState, LeadAiDraftOutcome, LeadAiSettings
from . import filters, live, openai_client, residential, shops, transcript

logger = logging.getLogger(__name__)

PERSON = "person"
ORDINARY = "ordinary"
# The handover reasons a person must answer (engine.HIGH_HANDOVER, the legal handover, a broker): never sent by itself.
PERSON_REASONS = frozenset(
    {"customer_asked_human", "call_requested", "complaint_or_upset", "owner_viewing_slot", "legal_visa_licence_contract", "broker_or_for_client", "broker"}
)
ASK_MAX = 500
ASK_LINES = 20
ASK_SYSTEM = (
    "You help an agent of a Dubai real-estate team answer a WhatsApp customer. The agent asked you a question about this "
    "chat, or for a reply to send. Write the reply the agent can send to the customer, in the customer's language, as the "
    "team (\"we\"), short, with only the facts in FACTS; where the facts are silent, say our agent will confirm. Never "
    "promise a call or a visit that is not booked, never name a colleague, never say you are an AI or that this is a "
    "draft. Answer with JSON: reply (the message to send) and language (en, ar, ur, ur_latin or hi)."
)
ASK_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "language": {"type": "string"}},
    "required": ["reply", "language"],
    "additionalProperties": False,
}
AUTO_PAYLOAD = {"source": transcript.ASSISTANT, "copilot": "auto"}


def kind_for(reason: str) -> str:
    return PERSON if (reason or "") in PERSON_REASONS else ORDINARY


def draft_text(raw: str, context: str) -> str:
    """The model's words as a draft: no figure the chat and the facts lack (filters.clean_reply), no availability claim
    (residential.claims_availability); the agent edits the rest."""
    text, _ = filters.clean_reply(str(raw or ""), str(context or ""), max_questions=2)
    kept = [s for s in filters.split_sentences(text) if not residential.claims_availability(s)]
    return " ".join(kept).strip()


def remember(answer: dict, now, *, reason: str, language: str) -> dict | None:
    """The turn's draft from the answer's kept reply (engine._apply stores it), or None when nothing is worth keeping."""
    text = draft_text(answer.get("copilot_draft") or "", answer.get("copilot_context") or "")
    went_out = " ".join(str(answer.get("copilot_sent") if "copilot_sent" in answer else answer.get("reply") or "").split())
    if not text or text == went_out:
        return None  # nothing, or the very words that went out
    return {
        "text": text,
        "at": now.isoformat(),
        "reason": reason or "unclear",
        "kind": kind_for(reason),
        "language": language or "en",
        "question": "",
        "by": "assistant",
    }


def ask(conversation, question: str, agent_id: int | None = None) -> dict | None:
    """The agent's question answered as a draft on the chat (a model call), stored and announced; None when it failed."""
    question = " ".join(str(question or "").split())[:ASK_MAX]
    if not question or not openai_client.configured():
        return None
    settings_row = LeadAiSettings.load()
    state = LeadAiChatState.for_conversation(conversation)
    campaign_templates = transcript.campaign_template_ids(conversation)
    lines = []
    for row in transcript.conversation_rows(conversation, limit=ASK_LINES):
        heard = transcript.transcript_text(row) if row.kind == "audio" else None
        lines.append(transcript.line(row, campaign_templates, heard))
    facts = json.dumps({k: v for k, v in (state.facts or {}).items() if v not in (None, "", [])}, ensure_ascii=False)
    blocks = [
        f"BRAND: {settings_row.brand_name}",
        f"OUR OFFICE: {settings_row.office_address}",
        "FACTS (shops): " + shops.facts_block(settings_row.shops_facts),
        "FACTS (rent): " + residential.facts_block("rent", "", (), settings_row.residential_facts),
        "FACTS (sale): " + residential.facts_block("sale", "", (), settings_row.residential_facts),
        "KNOWN FACTS: " + facts,
        "CHAT (oldest first):",
        *lines,
        f"THE AGENT ASKS: {question}",
    ]
    context = "\n".join(blocks)
    try:
        completion = openai_client.complete_json(
            [{"role": "system", "content": ASK_SYSTEM}, {"role": "user", "content": context}],
            ASK_SCHEMA,
            name="leadai_copilot",
            user=openai_client.safety_id(conversation.pk),
            cache_key="leadai-copilot",
        )
    except Exception as exc:  # noqa: BLE001 - the agent sees no draft, the log says why
        logger.warning("Lead AI co-pilot could not answer on conversation %s: %s", conversation.pk, exc)
        return None
    data = completion.data if isinstance(completion.data, dict) else {}
    text = draft_text(str(data.get("reply") or ""), context)
    if not text:
        return None
    draft = {
        "text": text,
        "at": timezone.now().isoformat(),
        "reason": state.handover_reason or "",
        "kind": PERSON,  # asked for by an agent: theirs to send, never by itself
        "language": str(data.get("language") or state.language or "en")[:16],
        "question": question,
        "by": "agent",
    }
    LeadAiChatState.objects.filter(pk=state.pk).update(draft=draft)
    live.appointment_changed(conversation.pk)
    return draft


def outcome(conversation, draft: dict, kind: str, *, agent=None, sent_text: str = "") -> LeadAiDraftOutcome:
    return LeadAiDraftOutcome.objects.create(
        conversation=conversation,
        agent=agent,
        kind=kind,
        reason=str(draft.get("reason") or "")[:40],
        question=str(draft.get("question") or "")[:500],
        draft_text=str(draft.get("text") or ""),
        sent_text=sent_text,
    )


def close(conversation, state, kind: str, *, agent=None, sent_text: str = "") -> LeadAiDraftOutcome | None:
    """The draft's fate recorded and the draft cleared; None when there was none."""
    draft = state.draft
    if not draft:
        return None
    row = outcome(conversation, draft, kind, agent=agent, sent_text=sent_text)
    LeadAiChatState.objects.filter(pk=state.pk).update(draft=None)
    state.draft = None
    return row


def _draft_at(draft: dict) -> dt.datetime | None:
    try:
        at = dt.datetime.fromisoformat(str(draft.get("at") or ""))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=dt.timezone.utc)


def due(settings_row, now) -> list[LeadAiChatState]:
    """The handed-over chats whose ordinary draft is older than the setting's minutes (the sweep sends them)."""
    minutes = int(settings_row.copilot_auto_send_minutes or 0)
    if minutes <= 0:
        return []
    cutoff = now - dt.timedelta(minutes=minutes)
    rows = []
    for state in (
        LeadAiChatState.objects.filter(draft__isnull=False, handed_over_at__isnull=False, stopped_at__isnull=True, paused_at__isnull=True)
        .select_related("conversation", "conversation__contact")
        .order_by("pk")[:200]
    ):
        draft = state.draft or {}
        at = _draft_at(draft)
        if draft.get("kind") == ORDINARY and at is not None and at <= cutoff:
            rows.append(state)
    return rows


def auto_send(state, settings_row, now) -> str:
    """An ordinary draft nobody sent or dropped goes out as the assistant's reply: "sent", else why not."""
    from apps.inbox import services as inbox_services
    from apps.inbox.models import Message

    draft = state.draft or {}
    conversation = state.conversation
    if draft.get("kind") != ORDINARY:
        return "a person's draft"
    if state.handed_over_at is None or state.stopped_at is not None or state.paused_at is not None:
        return "the chat is no longer handed over"
    if not settings_row.answers(conversation.contact.wa_id):
        return "the assistant is off for this number"
    if not conversation.is_session_open:
        return "the 24-hour window is closed"
    at = _draft_at(draft)
    if at is None:
        return "no time on the draft"
    if Message.objects.filter(conversation=conversation, created_at__gt=at).filter(Q(direction="out") | Q(direction="in")).exclude(kind="system").exists():
        return "somebody wrote since the draft"
    text = str(draft.get("text") or "").strip()
    if not text:
        return "an empty draft"
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        if (fresh.draft or {}).get("at") != draft.get("at"):
            return "the draft changed"
        inbox_services.send_text(conversation, None, text, payload=dict(AUTO_PAYLOAD))
        outcome(conversation, draft, LeadAiDraftOutcome.Kind.AUTO, sent_text=text)
        fresh.draft = None
        fresh.save(update_fields=["draft", "updated_at"])
    live.appointment_changed(conversation.pk)
    return "sent"


def sweep(now=None) -> int:
    """Every due ordinary draft sent (the sweep's step); how many went."""
    now = now or timezone.now()
    settings_row = LeadAiSettings.load()
    sent = 0
    for state in due(settings_row, now):
        try:
            result = auto_send(state, settings_row, now)
        except Exception:  # noqa: BLE001 - one chat must not stop the others
            logger.exception("Lead AI co-pilot could not send the draft on conversation %s", state.conversation_id)
            continue
        if result == "sent":
            sent += 1
        else:
            logger.info("Lead AI co-pilot left the draft on conversation %s: %s", state.conversation_id, result)
    return sent
