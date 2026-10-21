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
# The template's second variable: the listing in words ("the 2-bedroom in Serena"); "your enquiry" when nothing is known.
UNIT_WORDS = {"studio": "the studio", "one_br": "the one-bedroom", "two_plus": "the apartment", "villa": "the villa", "townhouse": "the townhouse", "shop": "the shop"}
FALLBACK_WORDS = "your enquiry"


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
    if not (settings_row.greet_template or "").strip():
        return "no greet template"
    return ""


def greeted_already(lead_id: int) -> bool:
    """A Lead AI campaign reached this lead already (the greet, or an agent's own popup send)."""
    from apps.campaigns.models import CampaignRecipient

    return CampaignRecipient.objects.filter(crm_lead_id=lead_id, campaign__lead_ai__isnull=False).exists()


def listing_words(context: dict, unit=None) -> str:
    """"the 2-bedroom townhouse in Mudon" from the enquired unit, else from the lead's bedrooms and community, else
    "your enquiry". English words only: the template is English and the model's reply follows the customer."""
    if unit is not None:
        from . import inventory

        noun = inventory.unit_words(unit)
        place = unit.community or str(context.get("community") or "")
        return f"the {noun} in {place}" if place else f"the {noun}"
    noun = UNIT_WORDS.get(str(context.get("unit") or ""), "")
    if not noun and context.get("property") in ("villa", "townhouse", "shop"):
        noun = UNIT_WORDS[context["property"]]
    place = str(context.get("community") or context.get("cluster") or "").strip()
    if noun and place:
        return f"{noun} in {place}"
    if noun:
        return noun
    return f"the home in {place}" if place else FALLBACK_WORDS


def popup_row(lead_id: int, row: dict, phone: str) -> dict:
    """The lead as the campaign popup sends it (campaigns.crm_leads.build_recipients reads these keys)."""
    from . import crm_fields

    return {
        "id": lead_id,
        "phone": phone,
        "name": str(row.get("NAME") or ""),
        "first_name": str(row.get("NAME") or ""),
        "last_name": str(row.get("LAST_NAME") or ""),
        "title": str(row.get("TITLE") or ""),
        "bot_status": row.get(crm_fields.FIELD_BOT_STATUS),
        "wa_opt_out": row.get(crm_fields.FIELD_OPT_OUT),
    }


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
    from apps.catalog.models import WaTemplate
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
    number = settings_row.greet_number
    template = (
        WaTemplate.objects.filter(name=settings_row.greet_template.strip(), waba_business_id=number.waba_business_id, status=WaTemplate.Status.APPROVED)
        .order_by("-pk")
        .first()
    )
    if template is None:
        return {"skipped": "no approved template on the greet number"}
    context = lead_context.parse(row)
    from . import inventory

    words = listing_words(context, inventory.enquired(context))
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
        logger.info("Lead AI greet: lead %s not sent (%s)", lead_id, str(exc)[:120])
        return {"skipped": str(exc)[:120]}
    if result.get("skipped"):
        reason = "; ".join(str(item.get("reason") or "") for item in result["skipped"])
        return {"skipped": reason or "left out", "campaign_id": result.get("campaign_id")}
    from apps.campaigns.models import Campaign

    campaign = Campaign.objects.filter(pk=result["campaign_id"]).first()
    if campaign is not None:
        Campaign.objects.filter(pk=campaign.pk).update(name=f"{NAME_PREFIX} · {template.name}"[:200])
        # The chat's community from the lead (communities.campaign_community reads it until their words say otherwise).
        lane.mark_campaign(campaign, playbook=lane.IC_SHOPS, community=str(context.get("community") or ""))
    logger.info("Lead AI greet: lead %s gets %s from %s (%s)", lead_id, template.name, number.phone_number, words)
    return {"sent": True, "campaign_id": result.get("campaign_id"), "words": words, "template": template.name}
