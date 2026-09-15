import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.inbox.models import Conversation
from apps.inbox.serializers import serialize_number

from .models import NumberAssignment, WabaNumber, WaTemplate, WaTemplateHide


def _require_admin(request):
    """Returns an error response, or None if the caller may administer."""
    if not request.user.has_admin_rights:
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)
    return None


def _covered_waba_ids(user):
    return set(
        user.visible_numbers.exclude(waba_business_id="").values_list(
            "waba_business_id", flat=True
        )
    )


def _meta_error_detail(exc):
    """The sentence Meta (or the gateway wrapping Meta) actually said."""
    from apps.gateway.client import describe_alots_failure

    return describe_alots_failure(str(exc), getattr(exc, "payload", None))


def serialize_template(template):
    return {
        "id": template.pk,
        # Which business account it lives on. Several numbers share one WABA, so
        # this is what the screen matches a template back to a number by — an
        # agent covering four numbers otherwise sees one undifferentiated list
        # and cannot tell which of them a template can actually be sent from.
        "waba_business_id": template.waba_business_id,
        "name": template.name,
        "language": template.language,
        "category": template.category,
        "status": template.status,
        "body_text": template.body_text,
        "footer_text": template.footer_text,
        "header": template.header,
        "buttons": template.buttons,
        "variable_count": template.variable_count,
        "requires_header_media": template.requires_header_media,
        "components": template.components,
    }


def serialize_number_with_agents(number, template_counts=None, chat_counts=None):
    data = serialize_number(number)
    # ``active_assignments`` when the caller prefetched it, so a page of twenty
    # numbers is one query rather than twenty. Filtering the relation here
    # instead would go back to the database for every row.
    roster = getattr(number, "active_assignments", None)
    if roster is None:
        roster = number.assignments.filter(is_active=True).select_related("agent")

    data["agents"] = [
        {
            "agent_id": a.agent_id,
            "display_name": a.agent.display_name or a.agent.get_username(),
            "community": a.agent.community or "",
            "role": a.role,
        }
        for a in roster
    ]
    # A number with no approved templates cannot reopen a closed window, so it
    # can only ever reply to customers who wrote first. That is a property of
    # the number an admin has to know before handing it to an agent, and it is
    # invisible everywhere else.
    if template_counts is not None:
        data["template_count"] = template_counts.get(number.waba_business_id, 0)
    if chat_counts is not None:
        data["conversation_count"] = chat_counts.get(number.pk, 0)
    return data


def serialize_agent_row(agent):
    linked_count = agent.openwa_assignments.filter(is_active=True).count()
    return {
        "id": agent.pk,
        "display_name": agent.display_name or agent.get_username(),
        "community": agent.community or "",
        "bitrix_user_id": agent.bitrix_user_id,
        "avatar_url": agent.avatar_url,
        "is_wa_admin": agent.has_admin_rights,
        "is_manual_admin": agent.is_wa_admin,
        "is_bitrix_admin": agent.is_bitrix_admin,
        "can_official_api": bool(agent.can_official_api),
        "can_linked_devices": bool(agent.can_linked_devices),
        "is_active": agent.is_active,
        "last_seen_at": agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        "linked_session_count": linked_count,
        "numbers": [
            {"id": a.number_id, "phone_number": a.number.phone_number, "role": a.role}
            for a in agent.number_assignments.filter(is_active=True).select_related("number")
        ],
    }


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _parse_number_credentials(data):
    """Normalize the fields an admin types from webbox (OTP or QR)."""
    phone_number = _digits(data.get("phone_number", ""))
    phone_number_id = str(data.get("phone_number_id", "")).strip()
    waba_business_id = str(data.get("waba_business_id", "")).strip()
    label = str(data.get("label", "")).strip()[:255]
    community = str(data.get("community", "")).strip()[:120]
    display_name = str(data.get("display_name", "")).strip()[:255]
    return phone_number, phone_number_id, waba_business_id, label, community, display_name


def _hamming(a: str, b: str) -> int:
    if len(a) != len(b):
        return 99
    return sum(1 for x, y in zip(a, b) if x != y)


def _local_number_conflict(phone_number, phone_number_id, waba_business_id):
    """
    Exact or near-miss against the local catalogue. Near-miss (1 digit off on
    Phone Number ID with the same Business ID) is the usual webbox typo.
    """
    by_pnid = WabaNumber.objects.filter(phone_number_id=phone_number_id).first()
    if by_pnid:
        return {
            "ok": False,
            "allow_force": False,
            "already_exists": True,
            "detail": (
                f"Already on this panel as {by_pnid.phone_number} "
                f"({by_pnid.label or by_pnid.title}). "
                "Open Numbers Management — do not add it again."
            ),
            "phone_number": by_pnid.phone_number,
            "phone_number_id": by_pnid.phone_number_id,
            "waba_business_id": by_pnid.waba_business_id,
        }

    by_phone = WabaNumber.objects.filter(phone_number=phone_number).first()
    if by_phone:
        return {
            "ok": False,
            "allow_force": False,
            "already_exists": True,
            "detail": (
                f"Phone {phone_number} is already on this panel as "
                f"{by_phone.label or by_phone.title} "
                f"(Phone Number ID {by_phone.phone_number_id}, "
                f"Business ID {by_phone.waba_business_id})."
            ),
            "phone_number": by_phone.phone_number,
            "phone_number_id": by_phone.phone_number_id,
            "waba_business_id": by_phone.waba_business_id,
        }

    if waba_business_id and phone_number_id:
        for row in WabaNumber.objects.filter(waba_business_id=waba_business_id):
            if _hamming(phone_number_id, row.phone_number_id) == 1:
                return {
                    "ok": False,
                    "allow_force": False,
                    "already_exists": True,
                    "detail": (
                        f"Phone Number ID looks mistyped. This Business ID is "
                        f"already on the panel as {row.phone_number} "
                        f"({row.label or row.title}) with Phone Number ID "
                        f"{row.phone_number_id}. Use that exact ID — do not add again."
                    ),
                    "phone_number": row.phone_number,
                    "phone_number_id": row.phone_number_id,
                    "waba_business_id": row.waba_business_id,
                }

    return None


def _match_alots_channel(phone_number, phone_number_id, waba_business_id):
    """
    Look up the channel on alots. Primary key is phone_number_id; also detects
    swapped Business/Phone Number IDs. When the channel is not on this gateway
    (common for a second webbox / BSP), returns allow_force so the admin can
    still save a manual row.
    """
    from apps.gateway.client import AlotsClient, AlotsError

    conflict = _local_number_conflict(phone_number, phone_number_id, waba_business_id)
    if conflict:
        return None, conflict

    try:
        channels = AlotsClient().list_channels()
    except AlotsError as exc:
        return None, {
            "ok": False,
            "allow_force": True,
            "detail": f"Gateway error: {exc}. You can still Save anyway as a manual number.",
        }
    except Exception as exc:  # noqa: BLE001
        return None, {
            "ok": False,
            "allow_force": True,
            "detail": f"Could not reach gateway: {exc}. You can still Save anyway.",
        }

    wanted_id = str(phone_number_id).strip()
    wanted_waba = str(waba_business_id).strip()

    match = next(
        (c for c in channels if str(c.get("phoneNumberId") or "") == wanted_id),
        None,
    )

    # Common webbox mix-up: Business ID and Phone Number ID typed in each other's boxes.
    if not match:
        swapped = next(
            (
                c
                for c in channels
                if str(c.get("phoneNumberId") or "") == wanted_waba
                and str(c.get("wabaBusinessId") or "") == wanted_id
            ),
            None,
        )
        if swapped:
            return None, {
                "ok": False,
                "allow_force": False,
                "detail": (
                    "IDs look swapped. Put "
                    f"{swapped.get('wabaBusinessId')} in Business ID and "
                    f"{swapped.get('phoneNumberId')} in Phone Number ID."
                ),
                "phone_number": _digits(
                    swapped.get("wabaNumber") or swapped.get("phoneNumber") or ""
                ),
                "phone_number_id": str(swapped.get("phoneNumberId") or ""),
                "waba_business_id": str(swapped.get("wabaBusinessId") or ""),
            }

    if not match:
        by_phone = next(
            (
                c
                for c in channels
                if _digits(c.get("wabaNumber") or c.get("phoneNumber") or "") == phone_number
            ),
            None,
        )
        if by_phone:
            return None, {
                "ok": False,
                "allow_force": False,
                "detail": (
                    f"Gateway has {phone_number} as Phone Number ID "
                    f"{by_phone.get('phoneNumberId')} / Business ID "
                    f"{by_phone.get('wabaBusinessId')}. Use those values."
                ),
                "phone_number": phone_number,
                "phone_number_id": str(by_phone.get("phoneNumberId") or ""),
                "waba_business_id": str(by_phone.get("wabaBusinessId") or ""),
            }
        return None, {
            "ok": False,
            "allow_force": True,
            "detail": (
                "No channel on this gateway (alots) matches this Phone Number ID. "
                "If the number lives on another webbox/BSP, use Save anyway."
            ),
        }

    channel_phone = _digits(match.get("wabaNumber") or match.get("phoneNumber") or "")
    channel_waba = str(match.get("wabaBusinessId") or "").strip()
    verified = (
        match.get("verifiedName")
        or match.get("verified_name")
        or match.get("displayName")
        or match.get("name")
        or ""
    )

    if phone_number and channel_phone and phone_number != channel_phone:
        return None, {
            "ok": False,
            "allow_force": False,
            "detail": (
                f"Phone Number ID belongs to {channel_phone or 'another number'}, "
                f"not {phone_number}."
            ),
            "verified_name": verified,
        }

    if waba_business_id and channel_waba and waba_business_id != channel_waba:
        return None, {
            "ok": False,
            "allow_force": False,
            "detail": (
                f"Business ID does not match the gateway channel "
                f"(expected {channel_waba})."
            ),
            "verified_name": verified,
        }

    return match, {
        "ok": True,
        "allow_force": False,
        "detail": "Connected — channel found on the gateway.",
        "verified_name": verified or "",
        "phone_number": channel_phone or phone_number,
        "phone_number_id": wanted_id,
        "waba_business_id": channel_waba or waba_business_id,
    }


@api_view(["GET", "POST"])
def number_list(request):
    # Admins get the assignment roster with each number, since that is the
    # screen they manage it from; agents just get their own numbers.
    if request.method == "POST":
        return _create_number_response(request)

    if request.user.has_admin_rights:
        numbers = WabaNumber.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                "assignments",
                queryset=NumberAssignment.objects.filter(is_active=True).select_related("agent"),
                to_attr="active_assignments",
            )
        )

        # Counted once for the whole page rather than per row: templates belong
        # to a WABA and several numbers share one.
        template_counts = dict(
            WaTemplateHide.visible(
            WaTemplate.objects.filter(status=WaTemplate.Status.APPROVED)
            )
            .values_list("waba_business_id")
            .annotate(n=Count("pk"))
        )
        chat_counts = dict(
            Conversation.objects.values_list("number_id").annotate(n=Count("pk"))
        )
        return Response(
            [serialize_number_with_agents(n, template_counts, chat_counts) for n in numbers]
        )
    return Response([serialize_number(n) for n in request.user.visible_numbers])


@api_view(["POST"])
def test_number(request):
    """Probe alots for a Phone Number ID before the admin saves a manual row."""
    denied = _require_admin(request)
    if denied:
        return denied

    phone_number, phone_number_id, waba_business_id, _, _, _ = _parse_number_credentials(
        request.data
    )
    if not phone_number_id:
        return Response(
            {"ok": False, "detail": "Phone Number ID is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not phone_number:
        return Response(
            {"ok": False, "detail": "Phone number is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not waba_business_id:
        return Response(
            {"ok": False, "detail": "Business ID is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    _, result = _match_alots_channel(phone_number, phone_number_id, waba_business_id)
    # Always 200 with ok true/false — the panel shows Connected/Failed from the body.
    return Response(result)


def _create_number_response(request):
    """Save a manually typed Official API number (webbox OTP or QR credentials)."""
    denied = _require_admin(request)
    if denied:
        return denied

    phone_number, phone_number_id, waba_business_id, label, community, display_name = (
        _parse_number_credentials(request.data)
    )
    if not phone_number_id:
        return Response(
            {"detail": "Phone Number ID is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not phone_number:
        return Response({"detail": "Phone number is required"}, status=status.HTTP_400_BAD_REQUEST)
    if not waba_business_id:
        return Response({"detail": "Business ID is required"}, status=status.HTTP_400_BAD_REQUEST)

    if WabaNumber.objects.filter(phone_number_id=phone_number_id).exists():
        return Response(
            {"detail": "A number with this Phone Number ID already exists"},
            status=status.HTTP_409_CONFLICT,
        )
    if WabaNumber.objects.filter(phone_number=phone_number).exists():
        return Response(
            {"detail": "A number with this phone already exists"},
            status=status.HTTP_409_CONFLICT,
        )

    force = bool(request.data.get("force"))
    match, probe = _match_alots_channel(phone_number, phone_number_id, waba_business_id)
    if not probe.get("ok") and not (force and probe.get("allow_force")):
        return Response(
            {"detail": probe.get("detail") or "Connection test failed"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Prefer gateway values when they filled gaps (verified name / canonical phone).
    final_phone = _digits(probe.get("phone_number") or phone_number)
    final_waba = str(probe.get("waba_business_id") or waba_business_id).strip()
    verified = str(probe.get("verified_name") or "").strip()

    account_username = str(request.data.get("account_username") or "").strip()[:32]
    number = WabaNumber.objects.create(
        phone_number=final_phone,
        phone_number_id=phone_number_id,
        waba_business_id=final_waba,
        label=label,
        community=community,
        account_username=account_username,
        display_name=display_name or verified,
        source=WabaNumber.Source.MANUAL,
        is_active=True,
        synced_at=timezone.now() if match is not None else None,
    )
    return Response(serialize_number_with_agents(number), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def number_templates(request, pk):
    # Scoped to visible_numbers so an agent cannot read another team's templates
    # by guessing an id.
    number = get_object_or_404(request.user.visible_numbers, pk=pk)

    templates = WaTemplateHide.visible(
        WaTemplate.objects.filter(waba_business_id=number.waba_business_id)
    )
    if request.GET.get("all") != "1":
        templates = templates.filter(status=WaTemplate.Status.APPROVED)

    search = request.GET.get("q", "").strip()
    if search:
        templates = templates.filter(name__icontains=search)

    return Response([serialize_template(t) for t in templates])


@api_view(["GET"])
def agent_list(request):
    """Everyone who has signed into the panel, for the assignment screen.

    Agents appear here only after their first sign-in — identity comes from
    Bitrix, so there is nobody to list until they have opened the panel once.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    agents = (
        get_user_model()
        .objects.filter(is_active=True)
        .prefetch_related("number_assignments__number")
        .order_by("display_name", "username")
    )
    return Response([serialize_agent_row(a) for a in agents])


@api_view(["PUT", "POST"])
@transaction.atomic
def number_agents(request, pk):
    """Set exactly who works a number.

    Replaces the roster rather than adding to it, so the screen can send the
    checkbox state it has and not reason about what changed. Removals are
    deactivated rather than deleted — the history of who held a number matters
    when a conversation is later questioned.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    number = get_object_or_404(WabaNumber, pk=pk)
    entries = request.data.get("agents", [])
    if not isinstance(entries, list):
        return Response({"detail": "agents must be a list"}, status=status.HTTP_400_BAD_REQUEST)

    wanted = {}
    for entry in entries:
        agent_id = entry.get("agent_id") if isinstance(entry, dict) else entry
        if agent_id is None:
            continue
        role = entry.get("role", NumberAssignment.Role.PRIMARY) if isinstance(entry, dict) else NumberAssignment.Role.PRIMARY
        wanted[int(agent_id)] = role

    known = set(get_user_model().objects.filter(pk__in=wanted).values_list("pk", flat=True))
    missing = set(wanted) - known
    if missing:
        return Response(
            {"detail": f"Unknown agent ids: {sorted(missing)}"}, status=status.HTTP_400_BAD_REQUEST
        )

    number.assignments.filter(is_active=True).exclude(agent_id__in=wanted).update(is_active=False)

    for agent_id, role in wanted.items():
        NumberAssignment.objects.update_or_create(
            number=number,
            agent_id=agent_id,
            defaults={"role": role, "is_active": True, "created_by": request.user},
        )

    community_by_agent = {}
    for entry in entries:
        if not isinstance(entry, dict) or "community" not in entry:
            continue
        try:
            aid = int(entry.get("agent_id"))
        except (TypeError, ValueError):
            continue
        if aid in known:
            community_by_agent[aid] = str(entry.get("community") or "").strip()[:120]

    if community_by_agent:
        Agent = get_user_model()
        for agent in Agent.objects.filter(pk__in=community_by_agent):
            next_value = community_by_agent[agent.pk]
            if agent.community != next_value:
                agent.community = next_value
                agent.save(update_fields=["community"])

    number.refresh_from_db()
    return Response(serialize_number_with_agents(number))


@api_view(["PATCH", "POST"])
def update_number(request, pk):
    """Rename a number.

    The gateway's channel API returns no name at all, so without this the panel
    can only show digits. Admins normally set it to whoever works the number.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    number = get_object_or_404(WabaNumber, pk=pk)
    fields = []

    if "label" in request.data:
        number.label = str(request.data["label"]).strip()[:255]
        fields.append("label")
    if "community" in request.data:
        number.community = str(request.data["community"]).strip()[:120]
        fields.append("community")
    if "account_username" in request.data:
        number.account_username = str(request.data["account_username"]).strip()[:32]
        fields.append("account_username")
    if fields:
        number.save(update_fields=fields)

    return Response(serialize_number_with_agents(number))


@api_view(["POST"])
def sync_now(request):
    """Pull templates (and optionally channels) from the gateway on demand.

    A schedule already refreshes both, but whoever has just had a template
    approved should not have to wait for the next run to use it — and that is
    usually the agent who asked for it, not an admin.

    Templates are therefore open to any signed-in agent. It reads from the
    gateway and writes only into our own copy: nothing is created, nothing is
    sent, and a template an agent may not use is one they already cannot see,
    because every list on this screen is scoped to their own numbers.

    Channels stay admin-only. That one rewrites the number catalogue this whole
    panel is addressed by, and it is not a refresh anybody needs mid-shift.
    """
    from .tasks import sync_numbers, sync_templates_detail

    what = request.data.get("what", "templates")
    if what in ("numbers", "all"):
        denied = _require_admin(request)
        if denied:
            return denied
    try:
        result = {}
        if what in ("numbers", "all"):
            result["numbers"] = sync_numbers()
        if what in ("templates", "all"):
            total, failures = sync_templates_detail()
            result["templates"] = total
            result["wabas_failed"] = len(failures)
            result["failures"] = failures[:8]
    except Exception as exc:  # noqa: BLE001 - surface the gateway's complaint
        return Response({"detail": f"Sync failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({"status": "ok", **result})


@api_view(["POST"])
def set_agent_admin(request, pk):
    """Update Panel Admin and/or Official / Linked product access for an agent."""
    denied = _require_admin(request)
    if denied:
        return denied

    agent = get_object_or_404(get_user_model(), pk=pk)
    updates = []

    if "is_wa_admin" in request.data:
        if agent.pk == request.user.pk:
            # Removing your own last admin right locks everyone out of this screen.
            return Response(
                {"detail": "You cannot change your own admin rights"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        agent.is_wa_admin = bool(request.data.get("is_wa_admin"))
        updates.append("is_wa_admin")

    if "can_official_api" in request.data:
        agent.can_official_api = bool(request.data.get("can_official_api"))
        updates.append("can_official_api")

    if "can_linked_devices" in request.data:
        agent.can_linked_devices = bool(request.data.get("can_linked_devices"))
        updates.append("can_linked_devices")

    if "community" in request.data:
        agent.community = str(request.data.get("community") or "").strip()[:120]
        updates.append("community")

    if not updates:
        return Response(
            {"detail": "No fields to update"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    agent.save(update_fields=updates)
    return Response(serialize_agent_row(agent))


@api_view(["GET"])
def all_templates(request):
    """List all templates (approved, pending, rejected) for the agent's WABAs."""
    waba_ids = list(
        request.user.visible_numbers.exclude(waba_business_id="")
        .values_list("waba_business_id", flat=True)
        .distinct()
    )

    templates = WaTemplateHide.visible(
        WaTemplate.objects.filter(waba_business_id__in=waba_ids)
    )

    wanted_status = request.GET.get("status", "").strip().upper()
    if wanted_status and wanted_status in WaTemplate.Status.values:
        templates = templates.filter(status=wanted_status)

    search = request.GET.get("q", "").strip()
    if search:
        templates = templates.filter(name__icontains=search)

    return Response([serialize_template(t) for t in templates])


#: {{1}}, {{2}} … as Meta writes them, in the order they must be exampled.
VARIABLE_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def _variable_numbers(text):
    """The distinct placeholders in a piece of template text, in order."""
    seen = []
    for found in VARIABLE_RE.findall(text or ""):
        if found not in seen:
            seen.append(found)
    return seen


def _examples_for(text, supplied):
    """One example value per placeholder, in Meta's order.

    Meta rejects a template carrying {{1}} with no example for it — the review
    is a person reading the finished sentence, and "Hello {{1}}" is not one. The
    submission used to leave the whole `example` block out, so every template
    with a variable in it came back refused and the panel reported Meta's
    complaint as though the wording were at fault.

    A placeholder the composer left blank still gets something, because a
    missing entry fails the same way an absent block does.
    """
    values = supplied if isinstance(supplied, dict) else {}
    out = []
    for number in _variable_numbers(text):
        value = str(values.get(number) or values.get(int(number)) or "").strip()
        out.append(value or f"Sample {number}")
    return out


def _button_components(raw):
    """Meta's BUTTONS block from what the composer sent.

    Accepts the old shape — a list of strings, or one comma-separated string —
    because that is what the panel sent before it could describe anything but a
    quick reply, and a saved draft should not stop working.
    """
    if isinstance(raw, str):
        raw = [b.strip() for b in raw.split(",") if b.strip()]
    if not isinstance(raw, list):
        return []

    buttons = []
    # Three is Meta's limit for quick replies, and the limit this panel offers
    # for anything — a longer list is refused by Meta rather than truncated by
    # us, which reads as the template being wrong.
    for entry in raw[:3]:
        if isinstance(entry, str):
            text = entry.strip()
            if text:
                buttons.append({"type": "QUICK_REPLY", "text": text[:25]})
            continue
        if not isinstance(entry, dict):
            continue

        text = str(entry.get("text", "")).strip()[:25]
        if not text:
            continue

        kind = str(entry.get("type", "QUICK_REPLY")).strip().upper()

        if kind == "URL":
            url = str(entry.get("url", "")).strip()
            if not url:
                continue
            button = {"type": "URL", "text": text, "url": url}
            # A URL ending in a placeholder is how a template links to one
            # customer's own page, and Meta wants the finished link as proof.
            if VARIABLE_RE.search(url):
                sample = str(entry.get("example", "")).strip()
                button["example"] = [sample or VARIABLE_RE.sub("sample", url)]
            buttons.append(button)
        elif kind == "PHONE_NUMBER":
            phone = str(entry.get("phone_number", "")).strip()
            if not phone:
                continue
            buttons.append({"type": "PHONE_NUMBER", "text": text, "phone_number": phone})
        else:
            buttons.append({"type": "QUICK_REPLY", "text": text})

    return buttons


def _parse_template_form(data):
    """Validate composer input and build Meta's submission payload."""
    raw_name = str(data.get("name", "")).strip()
    clean_name = re.sub(r"[^\w]+", "_", raw_name.lower()).strip("_")
    if not clean_name:
        return None, "Template name is required."

    category = str(data.get("category", "MARKETING")).strip().upper()
    if category not in {"MARKETING", "UTILITY", "AUTHENTICATION"}:
        category = "MARKETING"

    language = str(data.get("language", "en")).strip() or "en"
    body_text = str(data.get("body_text", "")).strip()
    if not body_text:
        return None, "Body text is required."

    header_text = str(data.get("header_text", "")).strip()
    footer_text = str(data.get("footer_text", "")).strip()
    body_examples = data.get("body_examples", {})
    header_examples = data.get("header_examples", {})

    if len(header_text) > 60:
        return None, "Header text must be 60 characters or fewer."
    if len(footer_text) > 60:
        return None, "Footer text must be 60 characters or fewer."
    if len(body_text) > 1024:
        return None, "Body text must be 1024 characters or fewer."

    body_holes = _variable_numbers(body_text)
    if body_holes:
        expected = [str(i) for i in range(1, len(body_holes) + 1)]
        if body_holes != expected:
            return None, (
                "Placeholders must be {{1}}, {{2}}, … in order with no gaps "
                f"(found {', '.join('{{' + n + '}}' for n in body_holes)})."
            )
        stripped = body_text.strip()
        if stripped.startswith("{{") or stripped.endswith("}}"):
            return None, (
                "Body text cannot start or end with a variable — add words "
                "before {{1}} and after the last placeholder."
            )

    components = []
    if header_text:
        header = {"type": "HEADER", "format": "TEXT", "text": header_text}
        samples = _examples_for(header_text, header_examples)
        if samples:
            header["example"] = {"header_text": samples[:1]}
        components.append(header)

    body = {"type": "BODY", "text": body_text}
    samples = _examples_for(body_text, body_examples)
    if samples:
        body["example"] = {"body_text": [samples]}
    components.append(body)

    if footer_text:
        components.append({"type": "FOOTER", "text": footer_text})

    buttons = _button_components(data.get("buttons", []))
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})

    payload = {
        "name": clean_name,
        "category": category,
        "language": language,
        "components": components,
    }
    parsed = {
        "clean_name": clean_name,
        "category": category,
        "language": language,
        "components": components,
        "payload": payload,
    }
    return parsed, None


def _save_meta_template(waba_id, parsed, meta_res):
    initial_status = str(meta_res.get("status") or WaTemplate.Status.PENDING).upper()
    if initial_status not in WaTemplate.Status.values:
        initial_status = WaTemplate.Status.PENDING

    WaTemplateHide.unhide_name(waba_id, parsed["clean_name"])

    template, _ = WaTemplate.objects.update_or_create(
        waba_business_id=waba_id,
        name=parsed["clean_name"],
        language=parsed["language"],
        defaults={
            "meta_template_id": str(meta_res.get("id", "")),
            "category": parsed["category"],
            "status": initial_status,
            "components": parsed["components"],
            "synced_at": timezone.now(),
        },
    )
    return template


def _admin_waba_targets(*, number_ids=None, all_numbers=False):
    """Distinct WABA ids an admin wants, with the phone labels on each."""
    qs = WabaNumber.objects.filter(is_active=True).exclude(waba_business_id="")
    if all_numbers:
        pass
    elif number_ids:
        qs = qs.filter(pk__in=number_ids)
    else:
        return {}

    grouped: dict[str, list[str]] = {}
    for number in qs.order_by("phone_number"):
        label = number.phone_number or number.label or str(number.pk)
        grouped.setdefault(number.waba_business_id, [])
        if label not in grouped[number.waba_business_id]:
            grouped[number.waba_business_id].append(label)
    return grouped


def _template_on_waba(waba_id, name, language):
    return WaTemplate.objects.filter(
        waba_business_id=waba_id,
        name=name,
        language=language,
    ).first()


def _submit_template_to_waba(waba_id, parsed):
    """POST one template to Meta and mirror locally. Returns (template, error, skipped)."""
    from apps.gateway.client import AlotsClient, AlotsError

    existing = _template_on_waba(waba_id, parsed["clean_name"], parsed["language"])
    if existing:
        return existing, None, True

    try:
        meta_res = AlotsClient().create_template(waba_id, parsed["payload"]) or {}
    except AlotsError as exc:
        detail = _meta_error_detail(exc)
        if "already" in detail.lower() or "exist" in detail.lower():
            template, _ = WaTemplate.objects.update_or_create(
                waba_business_id=waba_id,
                name=parsed["clean_name"],
                language=parsed["language"],
                defaults={
                    "category": parsed["category"],
                    "status": WaTemplate.Status.PENDING,
                    "components": parsed["components"],
                    "synced_at": timezone.now(),
                },
            )
            return template, None, True
        return None, detail, False

    return _save_meta_template(waba_id, parsed, meta_res), None, False


def _bulk_template_results(parsed, targets):
    """Submit one template to many WABAs. Parallel — sequential Meta calls hang the UI."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from django.db import close_old_connections

    items = sorted(targets.items())

    def one(waba_id: str, phones: list[str]) -> dict:
        close_old_connections()
        try:
            template, err, skipped = _submit_template_to_waba(waba_id, parsed)
            if err:
                return {
                    "waba_business_id": waba_id,
                    "phones": phones,
                    "status": "failed",
                    "detail": err,
                }
            return {
                "waba_business_id": waba_id,
                "phones": phones,
                "status": "skipped" if skipped else "created",
                "template": serialize_template(template),
            }
        finally:
            close_old_connections()

    if len(items) <= 1:
        return [one(waba_id, phones) for waba_id, phones in items]

    rows: list[dict] = []
    workers = min(6, len(items))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, waba_id, phones) for waba_id, phones in items]
        for fut in as_completed(futures):
            rows.append(fut.result())
    # Stable order for the admin summary.
    order = {waba_id: i for i, (waba_id, _) in enumerate(items)}
    rows.sort(key=lambda r: order.get(r.get("waba_business_id"), 0))
    return rows


def _summarize_bulk(rows):
    created = sum(1 for r in rows if r["status"] == "created")
    skipped = sum(1 for r in rows if r["status"] == "skipped")
    failed = sum(1 for r in rows if r["status"] == "failed")
    return {"created": created, "skipped": skipped, "failed": failed, "results": rows}


@api_view(["POST"])
def create_template(request):
    """Create a new message template and submit to Meta for approval."""
    covered = _covered_waba_ids(request.user)

    waba_id = str(request.data.get("waba_business_id", "")).strip()
    if waba_id and waba_id not in covered:
        return Response(
            {"detail": "That WhatsApp Business account is not one of yours."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not waba_id:
        waba_id = next(iter(sorted(covered)), "")

    if not waba_id:
        return Response(
            {"detail": "No WhatsApp Business account found for your profile."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    parsed, err = _parse_template_form(request.data)
    if err:
        return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

    template, detail, _skipped = _submit_template_to_waba(waba_id, parsed)
    if detail:
        return Response(
            {"detail": f"Meta template submission failed: {detail}"},
            status=status.HTTP_400_BAD_REQUEST,
    )
    return Response(serialize_template(template), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def create_template_bulk(request):
    """Admin: submit the same new template to every selected Official number."""
    denied = _require_admin(request)
    if denied:
        return denied

    parsed, err = _parse_template_form(request.data)
    if err:
        return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

    all_numbers = bool(request.data.get("all_numbers"))
    raw_ids = request.data.get("number_ids") or request.data.get("numbers") or []
    number_ids = []
    if isinstance(raw_ids, list):
        number_ids = [int(x) for x in raw_ids if str(x).strip().isdigit()]
    elif str(raw_ids).strip().isdigit():
        number_ids = [int(raw_ids)]

    targets = _admin_waba_targets(number_ids=number_ids, all_numbers=all_numbers)
    if not targets:
        return Response(
            {"detail": "Pick at least one Official number, or choose All numbers."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rows = _bulk_template_results(parsed, targets)
    summary = _summarize_bulk(rows)
    code = status.HTTP_201_CREATED if summary["created"] else status.HTTP_200_OK
    return Response(summary, status=code)


@api_view(["POST"])
def deploy_template(request, pk):
    """Admin: copy an existing template definition to numbers that do not have it."""
    denied = _require_admin(request)
    if denied:
        return denied

    source = get_object_or_404(WaTemplate, pk=pk)
    parsed = {
        "clean_name": source.name,
        "category": source.category or "MARKETING",
        "language": source.language or "en",
        "components": source.components or [],
        "payload": {
            "name": source.name,
            "category": source.category or "MARKETING",
            "language": source.language or "en",
            "components": source.components or [],
        },
    }
    if not parsed["components"]:
        return Response(
            {"detail": "This template has no stored components to copy."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    all_numbers = bool(request.data.get("all_numbers", True))
    raw_ids = request.data.get("number_ids") or []
    number_ids = [int(x) for x in raw_ids if str(x).strip().isdigit()] if isinstance(raw_ids, list) else []

    targets = _admin_waba_targets(number_ids=number_ids, all_numbers=all_numbers)
    # Only WABAs that do not already carry this name+language.
    targets = {
        waba: phones
        for waba, phones in targets.items()
        if waba != source.waba_business_id and not _template_on_waba(waba, source.name, source.language)
    }
    if not targets:
        return Response(
            {
                "detail": "Every selected number already has this template.",
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
            }
        )

    rows = _bulk_template_results(parsed, targets)
    return Response(_summarize_bulk(rows))


@api_view(["DELETE"])
def delete_template(request, pk):
    """Hide a template from this panel. Meta is not changed."""
    template = get_object_or_404(WaTemplate, pk=pk)
    if template.waba_business_id not in _covered_waba_ids(request.user):
        return Response(
            {"detail": "That WhatsApp Business account is not one of yours."},
            status=status.HTTP_403_FORBIDDEN,
        )

    WaTemplateHide.hide_from_panel(
        template.waba_business_id,
        template.name,
        agent=request.user,
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def suggest_utility_templates(request):
    """1–3 UTILITY rewrites of the agent's typed draft, without submitting to Meta.

    Same audience as create: any signed-in agent. The call is a rewrite, not
    a send, and nothing is stored. Payload includes source, ai_configured,
    and ai_error so the panel can say when the model was skipped.
    """
    from .utility_rewrite import rewrite_as_utility

    body_text = str(request.data.get("body_text", "")).strip()
    if not body_text:
        return Response(
            {"detail": "Write the template body first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    result = rewrite_as_utility(
        body=body_text,
        name=str(request.data.get("name", "")).strip(),
        header=str(request.data.get("header_text", "")).strip(),
        footer=str(request.data.get("footer_text", "")).strip(),
        language=str(request.data.get("language", "en")).strip() or "en",
        category=str(request.data.get("category", "")).strip(),
    )
    return Response(result)
