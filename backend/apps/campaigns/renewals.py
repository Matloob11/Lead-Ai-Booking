"""Renewals (deal category 9): one click, two templates, one WhatsApp number.

A selected deal can carry a tenant phone and an owner phone. Each side is its
own campaign because a campaign has one template. Both go out from the Official
number the agent picked. One number can take 300 messages in that click; more
than that is refused so the agent adds another number rather than overloading
the line.

Same person on both sides of one deal (the two fields normalise to one phone)
gets the owner template only. ``{{1}}`` follows the Leads campaign: blank uses
that side's name, a typed value is sent to everyone, and a missing or generic
name ("Deal #39079", "Untitled") becomes "Customer".
"""

from __future__ import annotations

import logging
import re

from apps.catalog.models import WaTemplate

from .crm_leads import (
    CrmLeadSendError,
    build_recipients,
    context_for_agent,
    lead_display_name,
    left_out_sentence,
    mark_lead_ai,
    number_for_agent,
    phones_opted_out,
)
from .models import CrmTarget
from .phones import normalize_phone
from .services import create_campaign
from .tasks import run_campaign

logger = logging.getLogger(__name__)

PER_NUMBER_CAP = 300
MAX_DEALS = 500

# Bitrix titles the kanban prints when nobody stored a person's name.
_GENERIC_NAME = re.compile(r"^(untitled|unentitled|deal\s*#?\s*\d+)$", re.IGNORECASE)


class RenewalSendError(CrmLeadSendError):
    pass


def person_name(raw) -> str:
    """A name worth putting in {{1}}. Generic deal titles are not names."""
    text = str(raw or "").strip()
    if not text or _GENERIC_NAME.match(text):
        return ""
    cleaned = lead_display_name({"name": text})
    # "there" is the CRM greeting for a rejected title, not a renewals name.
    if not cleaned or cleaned == "there":
        return ""
    return cleaned


def _phone(raw) -> str:
    return normalize_phone(str(raw or "")) or ""


def _deal_id(raw: dict) -> int:
    try:
        value = int(raw.get("id") or raw.get("deal_id") or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def classify_deals(deals) -> dict:
    """Who actually gets a message, before a template is chosen.

    Duplicate phones are skipped inside one side, the same way Leads skips a
    repeated number. A deal whose tenant phone is the owner phone is owner-only.
    """
    tenants: list[dict] = []
    owners: list[dict] = []
    skipped: list[dict] = []
    rows: list[dict] = []
    seen_tenant: set[str] = set()
    seen_owner: set[str] = set()
    phone_set: set[str] = set()
    for raw in deals or []:
        if isinstance(raw, dict):
            phone_set.add(_phone(raw.get("tenant_phone")))
            phone_set.add(_phone(raw.get("owner_phone")))
    blocked = phones_opted_out({phone for phone in phone_set if phone})

    for raw in deals or []:
        if not isinstance(raw, dict):
            continue
        deal_id = _deal_id(raw)
        if deal_id <= 0:
            skipped.append({"id": 0, "role": "", "reason": "Invalid deal."})
            continue

        tenant_phone = _phone(raw.get("tenant_phone"))
        owner_phone = _phone(raw.get("owner_phone"))
        tenant_label = person_name(raw.get("tenant_name"))
        owner_label = person_name(raw.get("owner_name"))
        same = bool(tenant_phone and owner_phone and tenant_phone == owner_phone)

        tenant_state = "missing"
        owner_state = "missing"
        tenant_send = "" if same else tenant_phone
        if same:
            skipped.append(
                {
                    "id": deal_id,
                    "role": "tenant",
                    "reason": "Same number as the owner — owner message only.",
                }
            )
            tenant_state = "same"

        if tenant_send:
            if tenant_send in blocked:
                skipped.append({"id": deal_id, "role": "tenant", "reason": "Opted out."})
                tenant_state = "opted_out"
            elif tenant_send in seen_tenant:
                skipped.append({"id": deal_id, "role": "tenant", "reason": "Duplicate phone."})
                tenant_state = "duplicate"
            else:
                seen_tenant.add(tenant_send)
                tenants.append({
                    "id": deal_id,
                    "phone": tenant_send,
                    "name": tenant_label,
                    "details": raw.get("tenant_details") if isinstance(raw.get("tenant_details"), dict) else {},
                })
                tenant_state = "send"
        elif tenant_state != "same":
            skipped.append({"id": deal_id, "role": "tenant", "reason": "No phone number on this deal."})

        if owner_phone:
            if owner_phone in blocked:
                skipped.append({"id": deal_id, "role": "owner", "reason": "Opted out."})
                owner_state = "opted_out"
            elif owner_phone in seen_owner:
                skipped.append({"id": deal_id, "role": "owner", "reason": "Duplicate phone."})
                owner_state = "duplicate"
            else:
                seen_owner.add(owner_phone)
                owners.append({
                    "id": deal_id,
                    "phone": owner_phone,
                    "name": owner_label,
                    "details": raw.get("owner_details") if isinstance(raw.get("owner_details"), dict) else {},
                })
                owner_state = "send"
        else:
            skipped.append({"id": deal_id, "role": "owner", "reason": "No phone number on this deal."})

        rows.append(
            {
                "id": deal_id,
                "tenant_name": tenant_label or ("Customer" if tenant_state == "send" else ""),
                "tenant_tail": tenant_phone[-4:] if tenant_phone else "",
                "tenant_state": tenant_state,
                "owner_name": owner_label or ("Customer" if owner_state == "send" else ""),
                "owner_tail": owner_phone[-4:] if owner_phone else "",
                "owner_state": owner_state,
            }
        )

    return {
        "tenants": tenants,
        "owners": owners,
        "skipped": skipped,
        "rows": rows,
        "tenant_messages": len(tenants),
        "owner_messages": len(owners),
        "total": len(tenants) + len(owners),
        "cap": PER_NUMBER_CAP,
    }


def public_preview(classified: dict) -> dict:
    """What the Renewals popup may show. Full phone numbers stay on the server."""
    total = int(classified["total"])
    return {
        "tenant_messages": classified["tenant_messages"],
        "owner_messages": classified["owner_messages"],
        "total": total,
        "cap": PER_NUMBER_CAP,
        "over_cap": total > PER_NUMBER_CAP,
        "rows": classified["rows"],
        "skipped_count": len(classified["skipped"]),
    }


def _fill(
    template,
    people: list[dict],
    extra: dict | None,
    role: str,
    field_map: dict | None = None,
    lead_ai: bool = False,
) -> tuple[list[dict], list[dict]]:
    if not people:
        return [], []
    label = "owner" if role == "owner" else "tenant"
    if template is None:
        raise RenewalSendError(f"Pick a {label} template.")
    rows, skipped = build_recipients(
        template=template,
        leads=[
            {
                "id": person["id"],
                "phone": person["phone"],
                "name": person["name"] or "Customer",
                "details": person.get("details") if isinstance(person.get("details"), dict) else {},
                "bot_status": person.get("bot_status") or 0,
                "wa_opt_out": person.get("wa_opt_out") or 0,
            }
            for person in people
        ],
        extra_body=extra or {},
        entity="lead",
        field_map=field_map,
        lead_ai=lead_ai,
        allow_empty=True,
    )
    prepared = []
    for row in rows:
        deal_id = row.pop("crm_lead_id", None)
        row["crm_deal_id"] = deal_id
        row["crm_role"] = role
        prepared.append(row)
    for item in skipped:
        item["role"] = role
    return prepared, skipped


def build_renewal_messages(
    *,
    deals,
    tenant_template,
    owner_template,
    tenant_extra,
    owner_extra,
    tenant_field_map=None,
    owner_field_map=None,
    lead_ai: bool = False,
) -> dict:
    if len(list(deals or [])) > MAX_DEALS:
        raise RenewalSendError(f"Select at most {MAX_DEALS} deals.")
    classified = classify_deals(deals)
    tenant_rows, tenant_skipped = _fill(
        tenant_template, classified["tenants"], tenant_extra, "tenant", tenant_field_map, lead_ai
    )
    owner_rows, owner_skipped = _fill(
        owner_template, classified["owners"], owner_extra, "owner", owner_field_map, lead_ai
    )
    total = len(tenant_rows) + len(owner_rows)
    side_skipped = tenant_skipped + owner_skipped
    if total <= 0:
        sentence = left_out_sentence(side_skipped)
        if sentence:
            raise RenewalSendError(sentence)
        raise RenewalSendError("None of the selected deals have a usable phone number.")
    if total > PER_NUMBER_CAP:
        raise RenewalSendError(
            f"More numbers required. One Official number can send {PER_NUMBER_CAP} "
            f"messages. This selection is {total}."
        )
    return {
        "tenant": tenant_rows,
        "owner": owner_rows,
        "skipped": classified["skipped"] + side_skipped,
        "total": total,
        "cap": PER_NUMBER_CAP,
    }


def renewals_context(agent, deals) -> dict:
    payload = context_for_agent(agent)
    payload["preview"] = public_preview(classify_deals(deals))
    return payload


def _load_template(number, template_id, *, needed: bool, label: str):
    if not needed:
        return None
    try:
        pk = int(template_id or 0)
    except (TypeError, ValueError):
        pk = 0
    template = WaTemplate.objects.filter(pk=pk).first() if pk else None
    if template is None:
        raise RenewalSendError(f"Pick a {label} template.")
    if template.status != WaTemplate.Status.APPROVED:
        raise RenewalSendError(f"Template '{template.name}' is not approved.")
    if template.waba_business_id != number.waba_business_id:
        raise RenewalSendError("That template is not on the WhatsApp number you picked.")
    return template


def send_renewals(
    *,
    agent,
    number_id,
    deals,
    tenant_template_id,
    owner_template_id,
    tenant_variables=None,
    owner_variables=None,
    tenant_header_variables=None,
    owner_header_variables=None,
    tenant_button_variables=None,
    owner_button_variables=None,
    tenant_header_media_token="",
    owner_header_media_token="",
    lead_ai=False,
    lead_ai_playbook: str = "",
    community: str = "",
    tenant_field_map=None,
    owner_field_map=None,
) -> dict:
    """Queue the tenant campaign and the owner campaign from one Official number."""
    from .crm_media import header_media_id_for

    number = number_for_agent(agent, number_id)
    classified = classify_deals(deals)
    tenant_template = _load_template(
        number, tenant_template_id, needed=bool(classified["tenants"]), label="tenant"
    )
    owner_template = _load_template(
        number, owner_template_id, needed=bool(classified["owners"]), label="owner"
    )
    # Both files are checked before either campaign exists, so a stale owner
    # file never leaves the tenant half queued on its own.
    media = {
        "tenant": header_media_id_for(
            tenant_header_media_token, agent=agent, number=number, template=tenant_template, side="tenant"
        ),
        "owner": header_media_id_for(
            owner_header_media_token, agent=agent, number=number, template=owner_template, side="owner"
        ),
    }
    built = build_renewal_messages(
        deals=deals,
        tenant_template=tenant_template,
        owner_template=owner_template,
        tenant_extra=tenant_variables,
        owner_extra=owner_variables,
        tenant_field_map=tenant_field_map,
        owner_field_map=owner_field_map,
        lead_ai=lead_ai,
    )

    queued = []
    playbook = ""

    def queue(rows, template, header, buttons, role):
        nonlocal playbook
        if not rows or template is None:
            return
        campaign = create_campaign(
            agent=agent,
            number=number,
            template=template,
            recipients=rows,
            name=f"Renewals {role} · {'Lead AI · ' if lead_ai else ''}{template.name}"[:200],
            variables={},
            header_variables=header or {},
            button_variables=buttons or {},
            header_media_id=media[role],
            crm_target=CrmTarget.NONE,
        )
        if lead_ai:
            # The popup's "Lead AI" box: both sides follow the same script.
            # C44b: popup community → LeadAiCampaign.community (round 19).
            playbook = mark_lead_ai(campaign, lead_ai_playbook, community=community)
        queued.append({"campaign": campaign, "role": role})

    queue(
        built["tenant"],
        tenant_template,
        tenant_header_variables,
        tenant_button_variables,
        "tenant",
    )
    queue(
        built["owner"],
        owner_template,
        owner_header_variables,
        owner_button_variables,
        "owner",
    )
    for item in queued:
        run_campaign.delay(item["campaign"].pk)

    return {
        "campaigns": [
            {
                "campaign_id": item["campaign"].pk,
                "name": item["campaign"].name,
                "queued": item["campaign"].total,
                "template": item["campaign"].template.name,
                "role": item["role"],
            }
            for item in queued
        ],
        "queued": sum(item["campaign"].total for item in queued),
        "skipped": built["skipped"],
        "skipped_count": len(built["skipped"]),
        "from_number": number.phone_number,
        "cap": PER_NUMBER_CAP,
        "lead_ai": bool(lead_ai),
        "playbook": playbook,
    }


def post_deal_timeline(recipient, conversation) -> None:
    """Put the template we just sent on the deal, in the live-chat line format.

    The mirror copies later replies. This covers the outbound itself, which
    can be saved before the mirror task is able to see the row.
    """
    from apps.crmlink import client as bitrix
    from apps.crmlink.models import Mirror
    from apps.crmlink.tasks import _line_with_role

    deal_id = int(recipient.crm_deal_id or 0)
    if deal_id <= 0 or not bitrix.configured():
        return
    message = conversation.messages.order_by("-id").first()
    if message is None:
        return
    if Mirror.objects.filter(message_id=message.pk, entity_type="deal", entity_id=deal_id).exists():
        return
    try:
        comment_id = bitrix.add_comment("deal", deal_id, _line_with_role(message, recipient.crm_role))
    except bitrix.BitrixError as exc:
        logger.warning("Could not post renewal message on deal %s: %s", deal_id, exc)
        return
    Mirror.objects.get_or_create(
        message_id=message.pk,
        entity_type="deal",
        entity_id=deal_id,
        defaults={"comment_id": comment_id if isinstance(comment_id, int) else None},
    )
