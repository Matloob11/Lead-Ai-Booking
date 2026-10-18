"""The locked aldardso rotation: 34 numbers, 300 each, approved copies only."""

from apps.catalog.models import NumberAssignment, WaTemplate, WabaNumber
from apps.inbox.send_health import with_send_health

from .bulk import DEFAULT_PER_NUMBER

TEMPLATE_NAME = "aldardso"
TEMPLATE_LANGUAGE = "en"
NAME_PREFIX = "Rotate · aldardso"

# Order is the send order. The eight 971581058719–726 stay in the list and
# are used only after Meta marks aldardso APPROVED on them.
POOL = [
    "447576534429",
    "447723011791",
    "447723185014",
    "447723185187",
    "447723186020",
    "447723351149",
    "447723374770",
    "447723448895",
    "447723458662",
    "447723474991",
    "447723495849",
    "447723504881",
    "447723545003",
    "447782639429",
    "447828569383",
    "447830355926",
    "447846870802",
    "447846888462",
    "447882968294",
    "447476994353",
    "971524077268",
    "971524473103",
    "971524492026",
    "971555306149",
    "971555497521",
    "971555689029",
    "971581058719",
    "971581058720",
    "971581058721",
    "971581058722",
    "971581058723",
    "971581058724",
    "971581058725",
    "971581058726",
]


def pool_snapshot() -> list[dict]:
    """Every locked number, whether it can send aldardso right now."""
    numbers = {
        number.phone_number: number
        for number in with_send_health(
            WabaNumber.objects.filter(is_active=True, phone_number__in=POOL)
        )
    }
    wabas = {number.waba_business_id for number in numbers.values()}
    templates = {
        template.waba_business_id: template
        for template in WaTemplate.objects.filter(
            name=TEMPLATE_NAME, language=TEMPLATE_LANGUAGE, waba_business_id__in=wabas
        )
    }
    agents: dict[int, str] = {}
    for row in NumberAssignment.objects.filter(
        number__in=list(numbers.values()), is_active=True
    ).select_related("agent"):
        agents.setdefault(row.number_id, row.agent.display_name or str(row.agent))

    rows = []
    for phone in POOL:
        number = numbers.get(phone)
        if number is None:
            rows.append(
                {
                    "id": None,
                    "phone": phone,
                    "label": "",
                    "agent": "",
                    "template_status": "MISSING",
                    "can_send": False,
                    "reason": "This number is not active on the panel.",
                }
            )
            continue
        template = templates.get(number.waba_business_id)
        status = template.status if template else "MISSING"
        reason = ""
        can_send = False
        if getattr(number, "_send_blocked", False):
            reason = "The provider banned this number recently."
        elif template is None:
            reason = "aldardso is not on this number."
        elif template.status != WaTemplate.Status.APPROVED:
            reason = f"aldardso is {template.status}."
        else:
            can_send = True
        rows.append(
            {
                "id": number.pk,
                "phone": number.phone_number,
                "label": number.title,
                "agent": agents.get(number.pk, ""),
                "template_status": status,
                "template_id": template.pk if template else None,
                "can_send": can_send,
                "reason": reason,
            }
        )
    return rows


def plan_pool(recipients: list[dict], number_ids=None) -> dict:
    """300 rows per approved number, in the locked order.

    ``number_ids`` limits the send to numbers that accepted the header picture.
    Pending numbers, and numbers left out of that set, are skipped.
    """
    allowed = None
    if number_ids is not None:
        allowed = set()
        for raw in number_ids:
            try:
                allowed.add(int(raw))
            except (TypeError, ValueError):
                continue
    lanes = []
    skipped = []
    cursor = 0
    cap = DEFAULT_PER_NUMBER
    for row in pool_snapshot():
        base = {
            "number_id": row["id"],
            "phone": row["phone"],
            "label": row["label"],
        }
        if not row["can_send"]:
            skipped.append({**base, "reason": row["reason"]})
            continue
        if allowed is not None and row["id"] not in allowed:
            skipped.append({**base, "reason": "The header picture could not be uploaded to this number."})
            continue
        take = recipients[cursor : cursor + cap]
        lanes.append(
            {
                **base,
                "template_id": row["template_id"],
                "language": TEMPLATE_LANGUAGE,
                "count": len(take),
                "first_row": cursor + 1 if take else 0,
                "last_row": cursor + len(take),
            }
        )
        cursor += len(take)
    return {
        "cap": cap,
        "lanes": lanes,
        "skipped_numbers": skipped,
        "assigned": cursor,
        "leftover": max(0, len(recipients) - cursor),
    }


def seed_template() -> WaTemplate | None:
    """Any approved aldardso, so the batch knows the name and the header type."""
    return (
        WaTemplate.objects.filter(
            name=TEMPLATE_NAME,
            language=TEMPLATE_LANGUAGE,
            status=WaTemplate.Status.APPROVED,
        )
        .order_by("id")
        .first()
    )
