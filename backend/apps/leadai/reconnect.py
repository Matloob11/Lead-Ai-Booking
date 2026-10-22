"""Reconnect again (Matloob 2026-10-22): the mixed campaign's customers who never said no get one more template, so the
assistant can talk to them.

The 19 October campaign (intl_city_property_reconnect, five numbers, 1,295 leads) reached 781 people, of whom 246 wrote
back; 412 were never messaged at all (Meta's marketing daily cap stopped the campaign) and 102 could not be reached. Who
gets the second template (``audience``):

- **in the chat** (``CHAT``): a lead the campaign reached (its CampaignRecipient has a conversation on the Lead AI screen)
  whose customer never wrote back, or wrote and has been quiet for ``QUIET_HOURS``, as long as nothing says no:
  followups.blocked (stopped, paused, handed to a person, not interested, opted out, off the screen), no viewing booked
  or held, the number not dead (undeliverable, banned: only the cap's failures count as reachable), and the second
  template not sent in that chat yet. It goes inside the same chat, from the same number, as Template B goes
  (inbox services.send_template with transcript.FOLLOW_UP), so the engine reads the reply as a first answer to a mixed
  template (ic_templates.kind: AGAIN_NAME is MIXED) and the chat stays what it was.
- **fresh** (``FRESH``): a lead the campaign skipped (never messaged) or whose send the cap refused with no chat left
  behind: a one-recipient-per-lead Lead AI campaign on the original number through the popup's own path
  (campaigns.crm_leads.send_from_leads), which applies the popup's rules again (opt-out, Bot Status, an active Lead AI
  chat, the same template within 30 days) on the lead as Bitrix holds it now (crm.lead.list).
- left out, with the reason: a phone seen already in these campaigns, a dead number, a chat that said no.

Nothing here is automatic: the management command leadai_reconnect_again lists the audience (a dry run), and sends only
with --send, inside Template B's hours (11:00 to 18:00 Dubai, Monday to Saturday) unless --any-hour.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field

from django.utils import timezone

from . import followups, ic_templates, lane
from .assistant import newlead, transcript
from .models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings

logger = logging.getLogger(__name__)

FOLLOWUP_KIND = "reconnect_again"
QUIET_HOURS = 48
# A send Meta refused for the per-customer marketing cap (131049), or the campaign stopped for it: the number is fine.
CAP_WORDS = ("131049", "daily cap")
CHAT = "chat"
FRESH = "fresh"
NAME_PREFIX = "Reconnect again · Lead AI"
LEAD_FIELDS = ("ID", "NAME", "LAST_NAME", "TITLE", "PHONE", "SOURCE_ID", "STATUS_ID", "ASSIGNED_BY_ID")
PAGE = 50
PAUSE = 0.25  # between two in-chat sends: the gateway's own pace, never a burst


@dataclass
class Row:
    recipient: object
    path: str = ""  # CHAT, FRESH, or "" when left out
    why: str = ""  # why it is left out, or "" when it goes
    conversation: object = None
    chat: object = None
    state: object = None
    result: str = ""  # what the send did

    @property
    def phone(self) -> str:
        return str(self.recipient.phone or "")

    @property
    def lead_id(self) -> int:
        return int(self.recipient.crm_lead_id or 0)


def _sendable(template) -> bool:
    return int(getattr(template, "variable_count", 0) or 0) == 1 and not getattr(template, "requires_header_media", False)


def approved_template(number):
    """The reconnect-again template APPROVED on this number's WABA (English first), one variable, no media, else None."""
    from apps.catalog.models import WaTemplate

    waba = str(getattr(number, "waba_business_id", "") or "")
    if not waba:
        return None
    rows = WaTemplate.objects.filter(name=ic_templates.AGAIN_NAME, waba_business_id=waba, status=WaTemplate.Status.APPROVED)
    rows = sorted(rows, key=lambda row: (not str(row.language or "").lower().startswith("en"), -row.pk))
    return next((row for row in rows if _sendable(row)), None)


# A failed send that provably never reached the customer: the gateway refused it outright, or Meta refused it after
# taking it (the per-customer cap, an unreachable number): the next run may try again.
NEVER_LEFT = ("credit", "not approved", "needs", "value", "invalid", "131049", "131026", "131047", "130472", "400", "401", "403", "404", "422", "429")


def never_left(message) -> bool:
    """A FAILED reconnect-again row that did not reach the customer: a wamid (the gateway took it, Meta then failed it:
    the cap, undeliverable), or the gateway's own refusal (no credit, not approved, a bad value). A failure with no
    wamid and none of those words (a read timeout, a 502 after the send) may have gone out: it counts as sent, so no
    customer gets the template twice (the review before the gate, 2026-10-22)."""
    if getattr(message, "wamid", None):
        return True
    detail = f"{message.error_code or ''} {message.error_detail or ''}".lower()
    return any(word in detail for word in NEVER_LEFT)


def sent_already(conversation) -> bool:
    """The reconnect-again template went to this chat already (sent, delivered, read, queued, or failed in a way that
    may have reached them)."""
    from apps.inbox.models import Message

    rows = Message.objects.filter(
        conversation=conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template__name=ic_templates.AGAIN_NAME
    )
    return any(row.status != Message.Status.FAILED or not never_left(row) for row in rows)


def lead_ai_chat_before(phone: str) -> bool:
    """A Lead AI chat exists for this phone on any of our numbers: an active one the popup's rules refuse; one off the
    screen a person took over (moved to the inbox), and the campaign must not pull it back."""
    return LeadAiChat.objects.filter(conversation__contact__wa_id=phone).exists()


def in_reconnect_campaign(phone: str) -> bool:
    """A reconnect-again campaign holds this phone already, queued or sent (two --send runs minutes apart must not
    queue a lead twice: the popup's 30-day and active-chat rules see a send only once the runner made it)."""
    from apps.campaigns.models import CampaignRecipient

    return (
        CampaignRecipient.objects.filter(phone=phone, campaign__name__startswith=NAME_PREFIX)
        .exclude(status__in=(CampaignRecipient.Status.SKIPPED, CampaignRecipient.Status.EXHAUSTED, CampaignRecipient.Status.FAILED))
        .exists()
    )


def dead_number(recipient) -> bool:
    """The campaign's send failed for good for a reason that is the number's (undeliverable, banned, an experiment),
    not Meta's marketing cap."""
    from apps.campaigns.models import CampaignRecipient

    if recipient.status not in (CampaignRecipient.Status.FAILED, CampaignRecipient.Status.EXHAUSTED):
        return False
    detail = str(recipient.error_detail or "")
    return not any(word in detail for word in CAP_WORDS)


def open_appointment(conversation) -> bool:
    return LeadAiAppointment.objects.filter(conversation=conversation, status__in=("confirmed", "tentative")).exists()


def audience(campaign_ids, now=None, quiet_hours: int = QUIET_HOURS) -> list[Row]:
    """Every recipient of these Lead AI campaigns with its path (CHAT, FRESH) or why it is left out."""
    from apps.campaigns.models import CampaignRecipient

    now = now or timezone.now()
    quiet_since = now - dt.timedelta(hours=int(quiet_hours))
    settings_row = LeadAiSettings.load()
    recipients = (
        CampaignRecipient.objects.filter(campaign_id__in=[int(pk) for pk in campaign_ids], campaign__lead_ai__isnull=False)
        .select_related("campaign", "conversation__contact", "conversation__number")
        .order_by("pk")
    )
    seen: set[str] = set()
    rows: list[Row] = []
    for recipient in recipients:
        row = Row(recipient=recipient)
        rows.append(row)
        phone = str(recipient.phone or "")
        if phone in seen:
            row.why = "the phone is in these campaigns already"
            continue
        seen.add(phone)
        if dead_number(recipient):
            row.why = "the number cannot receive (" + " ".join(str(recipient.error_detail or "").split())[:40] + ")"
            continue
        if in_reconnect_campaign(phone):
            row.why = "in a reconnect-again campaign already"
            continue
        if recipient.conversation_id is None:
            # Never messaged: a fresh send, unless the customer talks to us already (a campaign would pull an agent's
            # chat onto the Lead AI screen: the review before the gate) or a Lead AI chat of theirs exists already.
            if recipient.status not in (CampaignRecipient.Status.SKIPPED, CampaignRecipient.Status.EXHAUSTED, CampaignRecipient.Status.FAILED):
                row.why = f"no chat and not skipped ({recipient.status})"
            elif not row.lead_id:
                row.why = "no Bitrix lead on the row"
            elif newlead.talking_already(phone):
                row.why = "talking to us already"
            elif lead_ai_chat_before(phone):
                row.why = "a Lead AI chat of theirs exists already"
            else:
                row.path = FRESH
            continue
        conversation = recipient.conversation
        row.conversation = conversation
        row.chat = LeadAiChat.objects.filter(conversation=conversation).first()
        row.state = LeadAiChatState.objects.filter(conversation=conversation).first()
        why = followups.blocked(conversation, row.chat, row.state, settings_row)
        if why:
            row.why = why
            continue
        if lane.playbook_for(conversation) != lane.IC_SHOPS:
            row.why = "not a shops chat"
            continue
        if open_appointment(conversation):
            row.why = "a viewing is booked or held"
            continue
        if conversation.last_inbound_at is not None and conversation.last_inbound_at > quiet_since:
            row.why = f"wrote to us in the last {int(quiet_hours)} hours"
            continue
        # What the chat's words say that the state does not (the follow-ups' own holds, followups.holds): they rented
        # elsewhere, said "Not now" (a check-back planned), turned the offer down in words, or wait for the reply cap.
        reading = followups.read_since(conversation)
        facts = (row.state.facts if row.state is not None else None) or {}
        if followups.rented_still(facts, reading):
            row.why = "rented elsewhere already"
            continue
        if followups.said_not_now(row.state, reading, now):
            row.why = "said not now (a check-back is planned)"
            continue
        if followups.turned_down(reading, now):
            row.why = "declined in words"
            continue
        if followups.cap_pending(conversation, reading):
            row.why = "their last message waits for the reply cap"
            continue
        if sent_already(conversation):
            row.why = "sent already"
            continue
        row.path = CHAT
    return rows


def summary(rows) -> dict:
    """Counts: how many go in the chat, how many fresh, and why the rest stay out."""
    out = {"recipients": len(rows), CHAT: 0, FRESH: 0, "out": {}}
    for row in rows:
        if row.path:
            out[row.path] += 1
        else:
            out["out"][row.why] = out["out"].get(row.why, 0) + 1
    return out


def send_in_chat(row: Row, now=None) -> str:
    """One chat's reconnect-again template, as Template B goes: "sent", or why not."""
    from apps.inbox import services as inbox_services

    from .assistant import reminders

    now = now or timezone.now()
    conversation = row.conversation
    template = approved_template(conversation.number)
    if template is None:
        return "no approved reconnect-again template on this number"
    if sent_already(conversation):
        return "sent already"
    # What the Bitrix lead says now (one REST read): a person's Bot Status or opt-out that never reached us, a meeting a
    # person booked, a closed stage (followups.bitrix_blocks, as before Template B). A lead that cannot be read waits.
    why = followups.bitrix_blocks(conversation, row.chat, (row.state.facts if row.state is not None else None) or {})
    if why:
        return why
    attempt = f"{FOLLOWUP_KIND}:{now.isoformat()}"
    values = {"1": reminders.template_value(followups._first_name(conversation, row.state) or "there")}
    try:
        inbox_services.send_template(
            conversation, None, template, values, payload={"source": transcript.FOLLOW_UP, "followup": FOLLOWUP_KIND, "attempt": attempt}
        )
    except Exception as exc:  # noqa: BLE001 - recorded; the agents see a failed message in the chat, the next run tries again
        logger.warning("Lead AI reconnect again for conversation %s failed: %s", conversation.pk, exc)
        return f"failed ({type(exc).__name__}: {str(exc)[:80]})"
    followups._changed(conversation.pk)
    return "sent"


def read_leads(lead_ids) -> dict:
    """{lead id: the lead's fields} from Bitrix (crm.lead.list, PAGE ids a call), with the fields the popup's rules read."""
    from apps.crmlink import client as bitrix

    from .assistant import crm_fields

    ids = sorted({int(pk) for pk in lead_ids if int(pk) > 0})
    select = [*LEAD_FIELDS, crm_fields.FIELD_BOT_STATUS, crm_fields.FIELD_OPT_OUT]
    found: dict = {}
    for start in range(0, len(ids), PAGE):
        chunk = ids[start : start + PAGE]
        result = bitrix.call("crm.lead.list", {"filter": {"ID": chunk}, "select": select, "start": 0}) or []
        for item in result if isinstance(result, list) else []:
            if isinstance(item, dict) and str(item.get("ID") or "").isdigit():
                found[int(item["ID"])] = item
    return found


def send_fresh(rows, agent, now=None) -> list[dict]:
    """The fresh leads as one Lead AI campaign per original number (the popup's path and rules). Returns one dict per
    number: {"number": digits, "campaign_id": N or None, "sent": n, "skipped": [{"id", "reason"}...], "error": ""}."""
    from apps.campaigns import crm_leads
    from apps.campaigns.models import Campaign

    from .assistant import newlead

    now = now or timezone.now()
    by_number: dict = {}
    for row in rows:
        by_number.setdefault(row.recipient.campaign.number_id, []).append(row)
    out = []
    for number_id, group in sorted(by_number.items()):
        number = group[0].recipient.campaign.number
        report = {"number": str(number.phone_number), "campaign_id": None, "sent": 0, "skipped": [], "error": ""}
        out.append(report)
        template = approved_template(number)
        if template is None:
            report["error"] = "no approved reconnect-again template on this number"
            for row in group:
                row.result = report["error"]
            continue
        try:
            leads = read_leads([row.lead_id for row in group])
        except Exception as exc:  # noqa: BLE001 - Bitrix down: this number waits for the next run
            report["error"] = f"Bitrix: {str(exc)[:100]}"
            for row in group:
                row.result = report["error"]
            continue
        popup_rows = []
        for row in group:
            lead = leads.get(row.lead_id)
            if lead is None:
                row.result = "lead not in Bitrix any more"
                report["skipped"].append({"id": row.lead_id, "reason": row.result})
                continue
            popup_rows.append(newlead.popup_row(row.lead_id, lead, row.phone))
        if not popup_rows:
            continue
        try:
            result = crm_leads.send_from_leads(
                agent=agent, template_id=template.pk, leads=popup_rows, extra_body={}, number_id=number.pk, entity="lead",
                lead_ai=True, lead_ai_playbook=lane.IC_SHOPS, field_map={"1": "name"},
            )
        except (crm_leads.CrmLeadSendError, crm_leads.CampaignError) as exc:
            report["error"] = str(exc)[:160]
            for row in group:
                row.result = report["error"]
            continue
        report["campaign_id"] = result.get("campaign_id")
        skipped = {int(item.get("id") or 0): str(item.get("reason") or "") for item in result.get("skipped") or []}
        report["skipped"] += [{"id": pk, "reason": reason} for pk, reason in skipped.items()]
        for row in group:
            if row.lead_id in skipped:
                row.result = skipped[row.lead_id]
            elif not row.result:
                row.result = "sent"
                report["sent"] += 1
        if report["campaign_id"]:
            campaign = Campaign.objects.filter(pk=report["campaign_id"]).first()
            if campaign is not None:
                Campaign.objects.filter(pk=campaign.pk).update(name=f"{NAME_PREFIX} · {template.name}"[:200])
                lane.mark_campaign(campaign, playbook=lane.IC_SHOPS)
    return out


def send(rows, agent, limit: int = 0, now=None, pause: float = PAUSE) -> dict:
    """Send to the audience: the chats first, then the fresh leads; at most ``limit`` in all when given."""
    now = now or timezone.now()
    chat_rows = [row for row in rows if row.path == CHAT]
    fresh_rows = [row for row in rows if row.path == FRESH]
    if limit:
        chat_rows = chat_rows[:limit]
        fresh_rows = fresh_rows[: max(0, limit - len(chat_rows))]
    counts = {"chat_sent": 0, "chat_failed": 0, "fresh": []}
    for row in chat_rows:
        row.result = send_in_chat(row, now)
        if row.result == "sent":
            counts["chat_sent"] += 1
        else:
            counts["chat_failed"] += 1
        if pause:
            time.sleep(pause)
    if fresh_rows:
        counts["fresh"] = send_fresh(fresh_rows, agent, now)
    return counts
