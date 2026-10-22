"""The new-lead greet (round 22; the board's Bot 1 beginnings): a brand-new Bitrix lead gets its first WhatsApp message
from the Lead AI within minutes of landing, and the assistant talks from the first reply — about the listing they
enquired on (lead_context, inventory.enquired), then the usual flow: the unit, the budget, the cluster, two free slots,
the office viewing, a person when one is needed.

How: Cursor's C67 handler on the box pings ``POST /api/leadai/bitrix/new-lead/`` when a lead is created
(bitrix_views.new_lead); ``tasks.greet_new_lead`` runs ``greet`` a minute later (the portal's fields land after the
row), which reads the lead (crm.lead.get), checks it is still a New lead with a phone, not too old, not opted out, not
a broker or Lost, not in a Lead AI chat already and not greeted before, and sends the greet template through the
campaign popup's own path (campaigns.crm_leads.send_from_leads: a one-recipient Lead AI campaign on the ic_shops
playbook, the chat's community from the lead), so everything after is what the popup gives: the chat on the Lead AI
screen, the reply answered by the engine, the lead's fields written. Settings (LeadAiSettings, Django admin): the
switch, the agent it is sent as, the number, the template's name, how old a lead may be.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

NAME_PREFIX = "New lead · Lead AI"
NEW_STATUS = "NEW"
# The inbox label every chat the greet opened carries (Matloob 2026-10-22): agents tell an automatic reply's chat from a
# campaign's. Put on by the sweep (label_greeted) once the campaign's send made the chat.
AUTO_REPLY_LABEL = "AI auto reply"
AUTO_REPLY_COLOUR = "#7C3AED"
LABEL_BATCH = 200
# The template's second variable: the listing in words ("the 2-bedroom in Serena"); "your enquiry" when nothing is known.
UNIT_WORDS = {"studio": "the studio", "one_br": "the one-bedroom", "two_plus": "the apartment", "villa": "the villa", "townhouse": "the townhouse", "shop": "the shop"}
FALLBACK_WORDS = "your enquiry"
# The first variable for a lead with no usable name, the popup's own word (campaigns.crm_leads._GREETING_FALLBACK).
GREETING_FALLBACK = "there"


def settings_ready(settings_row) -> str:
    """'' when the greet may run, else why not (the admin's four settings and the switch)."""
    if not settings_row.greet_enabled:
        return "greet off"
    if not settings_row.assistant_enabled:
        return "assistant off"
    agent = settings_row.greet_agent
    if agent is None or not agent.is_active or not agent.can_official_api:
        return "no greet agent"
    if settings_row.greet_number is None or not settings_row.greet_number.is_active:
        return "no greet number"
    if not agent.visible_numbers.filter(pk=settings_row.greet_number_id).exists():
        return "greet number not the greet agent's"
    if not (settings_row.greet_template or "").strip():
        return "no greet template"
    return ""


def greet_template(settings_row):
    """The approved template of the settings' name on the greet number's WABA (English first), or None."""
    from apps.catalog.models import WaTemplate

    rows = list(
        WaTemplate.objects.filter(
            name=(settings_row.greet_template or "").strip(), waba_business_id=settings_row.greet_number.waba_business_id,
            status=WaTemplate.Status.APPROVED,
        ).order_by("-pk")
    )
    return next((row for row in rows if str(row.language or "").lower().startswith("en")), rows[0] if rows else None)


def template_ready(template) -> str:
    """'' when the greet may use this template, else why not: the greet carries no media, fills {{1}} and {{2}} only, and
    is a portal template by name (ic_templates.PORTAL: the engine reads a reply to it with the lead context first; a
    template it reads as a shops one would put a studio lead's chat on the shop track, as chat 52745 was, round 22e)."""
    from .. import ic_templates

    if getattr(template, "requires_header_media", False):
        return "greet template has a media header"
    if int(getattr(template, "variable_count", 0) or 0) > 2:
        return "greet template needs more than {{1}} and {{2}}"
    if ic_templates.kind(getattr(template, "name", "")) != ic_templates.PORTAL:
        return f"greet template must be a portal one (a name starting {ic_templates.PORTAL_PREFIX})"
    return ""


def greeted_already(lead_id: int) -> bool:
    """A Lead AI campaign reached this lead already (the greet, or an agent's own popup send)."""
    from apps.campaigns.models import CampaignRecipient

    return CampaignRecipient.objects.filter(crm_lead_id=lead_id, campaign__lead_ai__isnull=False).exists()


PHONE_WITHIN = dt.timedelta(hours=24)


def phone_greeted_lately(phone_digits: str, now) -> bool:
    """A Lead AI campaign was made for this phone within PHONE_WITHIN, sent or still pending (a customer who enquired on
    two listings in a row makes two leads a minute apart: one greet)."""
    from apps.campaigns.models import CampaignRecipient

    return CampaignRecipient.objects.filter(
        phone=phone_digits, campaign__lead_ai__isnull=False, campaign__created_at__gte=now - PHONE_WITHIN
    ).exists()


def talking_already(phone_digits: str) -> bool:
    """The customer wrote to one of our numbers before (a conversation with an inbound message): a lead made for a chat
    in progress (the inbox's "Create lead", a hand-made lead) is no portal enquiry to greet, and the greet must never
    take an agent's chat onto the Lead AI screen."""
    from apps.inbox.models import Conversation

    return Conversation.objects.filter(contact__wa_id=phone_digits, last_inbound_at__isnull=False).exists()


def listing_words(context: dict, unit=None) -> str:
    """"the 2-bedroom townhouse in Mudon" from the enquired unit, else from the lead's bedrooms and community, else
    "your enquiry". English words only: the template is English and the model's reply follows the customer."""
    if unit is not None:
        from . import inventory

        noun = inventory.unit_words(unit)
        place = unit.community or str(context.get("community") or "")
        return f"the {noun} in {place}" if place else f"the {noun}"
    # A villa, a townhouse or a shop names the home whatever the bedrooms field says (tracks._pack_unit's rule).
    prop = str(context.get("property") or "")
    noun = UNIT_WORDS[prop] if prop in ("villa", "townhouse", "shop") else UNIT_WORDS.get(str(context.get("unit") or ""), "")
    place = str(context.get("community") or context.get("cluster") or "").strip()
    if noun and place:
        return f"{noun} in {place}"
    if noun:
        return noun
    return f"the home in {place}" if place else FALLBACK_WORDS


def popup_row(lead_id: int, row: dict, phone: str) -> dict:
    """The lead as the campaign popup sends it (campaigns.crm_leads.build_recipients reads these keys)."""
    from . import crm_fields, filters

    # {{1}} as the assistant's own lines greet (filters.first_name): "AHMED KHAN" is Ahmed, "Bayut WhatsApp | Md Sumon"
    # (a title) is Sumon; a placeholder ("Unknown", "Lead", an e-mail) is nobody, greeted "there" as the popup greets a
    # lead with no usable name (crm_leads._GREETING_FALLBACK; round 22e's review).
    first = filters.first_name(str(row.get("NAME") or "")) or filters.first_name(str(row.get("TITLE") or "")) or GREETING_FALLBACK
    return {
        "id": lead_id,
        "phone": phone,
        "name": first,
        "first_name": first,
        "last_name": str(row.get("LAST_NAME") or ""),
        "title": str(row.get("TITLE") or ""),
        "bot_status": row.get(crm_fields.FIELD_BOT_STATUS),
        "wa_opt_out": row.get(crm_fields.FIELD_OPT_OUT),
    }


def label_greeted() -> int:
    """The "AI auto reply" label on every chat a greet campaign made that lacks it (LABEL_BATCH a run). Returns how many."""
    from apps.campaigns.models import CampaignRecipient
    from apps.inbox.models import Label

    label, _ = Label.objects.get_or_create(name=AUTO_REPLY_LABEL, defaults={"colour": AUTO_REPLY_COLOUR})
    pending = list(
        CampaignRecipient.objects.filter(campaign__name__startswith=NAME_PREFIX, campaign__lead_ai__isnull=False, conversation__isnull=False)
        .exclude(conversation__labels=label)
        .order_by("pk")
        .values_list("conversation_id", flat=True)
        .distinct()[:LABEL_BATCH]
    )
    if pending:
        from .. import lane

        label.conversations.add(*pending)
        for conversation_id in pending:
            lane._announce(conversation_id)  # the chip shows on open screens now, not on the next reload
    return len(pending)


def _created_at(row: dict):
    raw = str(row.get("DATE_CREATE") or "").strip()
    if not raw:
        return None
    try:
        moment = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=dt.timezone.utc)


def greet(lead_id: int, *, now=None) -> dict:
    """The greet for one lead: {"sent": True, "campaign_id": N, ...} or {"skipped": why}. Raises BitrixTransient for
    the task to try again; any other Bitrix refusal is a skip."""
    from apps.campaigns import crm_leads
    from apps.crmlink import client as bitrix

    from .. import lane
    from ..models import LeadAiSettings
    from . import crm, lead_context

    now = now or timezone.now()
    lead_id = int(lead_id)
    settings_row = LeadAiSettings.load()
    why = settings_ready(settings_row)
    if why:
        return {"skipped": why}
    if greeted_already(lead_id):
        return {"skipped": "greeted already"}
    if not bitrix.configured():
        return {"skipped": "no Bitrix webhook"}
    try:
        row = crm.read_record("lead", lead_id)["fields"] or {}
    except bitrix.BitrixTransient:
        raise
    except bitrix.BitrixError as exc:
        logger.info("Lead AI greet: lead %s not read (%s)", lead_id, str(exc)[:80])
        return {"skipped": "lead not read"}
    if str(row.get("STATUS_ID") or "").upper() != NEW_STATUS:
        return {"skipped": f"not a new lead ({str(row.get('STATUS_ID') or '')[:24]})"}
    # A portal's lead only (lead_context.SOURCES: Property Finder, Bayut, Dubizzle): a lead the inbox's "Create lead"
    # made for a chat in progress, a hand-made lead, an agent's own test lead is nobody's enquiry to greet.
    context = lead_context.enrich(lead_context.parse(row))
    if not context.get("source"):
        return {"skipped": f"not a portal lead ({str(row.get('SOURCE_ID') or '')[:24]})"}
    created = _created_at(row)
    if created is not None and now - created > dt.timedelta(hours=int(settings_row.greet_within_hours or 0)):
        return {"skipped": "too old"}
    phones = sorted(crm_leads._lead_phones(row))
    if not phones:
        return {"skipped": "no phone"}
    row_for_popup = popup_row(lead_id, row, phones[0])
    why = crm_leads.opt_out_reason(row_for_popup) or crm_leads.lead_ai_skip_reason(row_for_popup)
    if why:
        return {"skipped": why.rstrip(".").lower()}
    digits = crm_leads._digits(phones[0])
    if talking_already(digits):
        return {"skipped": "talking to us already"}
    if phone_greeted_lately(digits, now):
        return {"skipped": "greeted this phone today"}
    number = settings_row.greet_number
    template = greet_template(settings_row)
    if template is None:
        return {"skipped": "no approved template on the greet number"}
    why = template_ready(template)
    if why:
        return {"skipped": why}
    from . import inventory

    unit = inventory.enquired(context)
    words = listing_words(context, unit)
    # The chat's community: the lead's Community field, else the enquired listing's (a Property Finder lead carries the
    # listing and often no community: the first greet, 2026-10-22, left the Serena townhouse's chat with none).
    community = str(context.get("community") or (unit.community if unit is not None else "") or "")
    field_map = {"1": "name"}
    extra_body = {"2": words} if int(template.variable_count or 0) >= 2 else {}
    try:
        result = crm_leads.send_from_leads(
            agent=settings_row.greet_agent,
            template_id=template.pk,
            leads=[row_for_popup],
            extra_body=extra_body,
            number_id=number.pk,
            entity="lead",
            lead_ai=True,
            lead_ai_playbook=lane.IC_SHOPS,
            field_map=field_map,
        )
    except (crm_leads.CrmLeadSendError, crm_leads.CampaignError) as exc:
        logger.warning("Lead AI greet: lead %s not sent (%s): a setting is off", lead_id, str(exc)[:120])
        return {"skipped": str(exc)[:120]}
    if result.get("skipped"):
        reason = "; ".join(str(item.get("reason") or "") for item in result["skipped"])
        return {"skipped": reason or "left out", "campaign_id": result.get("campaign_id")}
    from apps.campaigns.models import Campaign

    campaign = Campaign.objects.filter(pk=result["campaign_id"]).first()
    if campaign is not None:
        Campaign.objects.filter(pk=campaign.pk).update(name=f"{NAME_PREFIX} · {template.name}"[:200])
        # The chat's community (communities.campaign_community reads it until their words say otherwise).
        lane.mark_campaign(campaign, playbook=lane.IC_SHOPS, community=community)
    logger.info("Lead AI greet: lead %s gets %s from %s (%s)", lead_id, template.name, number.phone_number, words)
    return {"sent": True, "campaign_id": result.get("campaign_id"), "words": words, "template": template.name}
