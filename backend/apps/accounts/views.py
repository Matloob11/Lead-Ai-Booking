"""Sign-in by way of Bitrix24.

Agents never hold a password here. Bitrix posts a short-lived ``AUTH_ID`` into
the placement iframe; we spend it once against the portal's own REST API, and
whoever it identifies is the agent for that browser session. Because the token
is verified against Bitrix rather than merely decoded, a forged post cannot
mint a session.
"""

import logging

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)
Agent = get_user_model()


def _serialize(agent):
    from apps.inbox.serializers import serialize_number

    return {
        "id": agent.pk,
        "username": agent.username,
        "email": agent.email or "",
        "bitrix_user_id": agent.bitrix_user_id or "",
        "display_name": agent.display_name or agent.get_full_name() or agent.username,
        "avatar_url": agent.avatar_url,
        "is_wa_admin": agent.has_admin_rights,
        "role": "Administrator" if agent.has_admin_rights else "Agent",
        "numbers": [serialize_number(n) for n in agent.visible_numbers],
        "capabilities": {
            "read_receipts": settings.GATEWAY_SUPPORTS_READ_RECEIPTS,
            "typing_indicator": settings.GATEWAY_SUPPORTS_TYPING,
            "send_reactions": settings.GATEWAY_SUPPORTS_REACTIONS,
            "contact_cards": settings.GATEWAY_SUPPORTS_CONTACT_CARDS,
            "reply_quote": True,
            "location": True,
            "interactive": True,
        },
    }


def _fetch_bitrix_user(domain, auth_id):
    url = f"https://{domain}/rest/user.current.json"
    with httpx.Client(timeout=15) as client:
        response = client.get(url, params={"auth": auth_id})
    if response.status_code != 200:
        raise ValueError(f"Bitrix rejected the token (HTTP {response.status_code})")
    body = response.json()
    if "result" not in body:
        raise ValueError(body.get("error_description") or "Bitrix returned no user")
    return body["result"]


def _is_portal_admin(domain, auth_id):
    """Ask the portal whether this user administers it.

    A failure here is treated as "not an admin" rather than an error: the token
    is already proven, and losing the panel's admin screens is a far better
    outcome than refusing an agent their inbox.
    """
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(f"https://{domain}/rest/user.admin.json", params={"auth": auth_id})
        return bool(response.json().get("result"))
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.info("Could not read portal admin status: %s", exc)
        return False


# The very first call from the panel has no csrftoken cookie yet, so CSRF is
# waived here. The protection that matters is stronger: the AUTH_ID is spent
# against the portal's own REST API, and only the configured portal is accepted.
@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def bitrix_login(request):
    auth_id = request.data.get("AUTH_ID") or request.data.get("auth_id")
    domain = request.data.get("DOMAIN") or request.data.get("domain")

    if not auth_id or not domain:
        return Response({"detail": "AUTH_ID and DOMAIN are required"}, status=status.HTTP_400_BAD_REQUEST)

    # Only the configured portal may mint sessions here.
    expected = settings.BITRIX_PORTAL_URL.split("//")[-1].rstrip("/")
    if domain.rstrip("/") != expected:
        logger.warning("Login attempt from unexpected portal %s", domain)
        return Response({"detail": "Unknown Bitrix portal"}, status=status.HTTP_403_FORBIDDEN)

    try:
        profile = _fetch_bitrix_user(domain, auth_id)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Bitrix token verification failed: %s", exc)
        return Response({"detail": "Bitrix authentication failed"}, status=status.HTTP_401_UNAUTHORIZED)

    bitrix_id = str(profile.get("ID", "")).strip()
    if not bitrix_id:
        return Response({"detail": "Bitrix returned no user id"}, status=status.HTTP_401_UNAUTHORIZED)

    full_name = " ".join(filter(None, [profile.get("NAME", ""), profile.get("LAST_NAME", "")])).strip()

    agent, created = Agent.objects.get_or_create(
        bitrix_user_id=bitrix_id,
        defaults={
            "username": f"bitrix_{bitrix_id}",
            "email": profile.get("EMAIL") or "",
            "first_name": profile.get("NAME", "")[:150],
            "last_name": profile.get("LAST_NAME", "")[:150],
            "display_name": full_name,
            # A new agent starts with no numbers and no admin rights; an admin
            # grants both from the panel.
            "is_wa_admin": False,
        },
    )

    agent.display_name = full_name or agent.display_name
    agent.bitrix_portal = domain
    agent.avatar_url = profile.get("PERSONAL_PHOTO") or agent.avatar_url
    agent.is_bitrix_admin = _is_portal_admin(domain, auth_id)
    agent.last_seen_at = timezone.now()
    agent.save(
        update_fields=["display_name", "bitrix_portal", "avatar_url", "is_bitrix_admin", "last_seen_at"]
    )

    login(request, agent, backend="django.contrib.auth.backends.ModelBackend")
    return Response({**_serialize(agent), "created": created})


# Hands the panel its csrftoken cookie; every later POST depends on it.
@ensure_csrf_cookie
@api_view(["GET", "POST", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    if request.method in ["POST", "PATCH"]:
        display_name = str(request.data.get("display_name", "")).strip()
        if display_name:
            request.user.display_name = display_name[:150]
            request.user.save(update_fields=["display_name"])
    return Response(_serialize(request.user))


# Access requests
# ---------------------------------------------------------------------------


def _serialize_request(access_request):
    agent = access_request.agent
    return {
        "id": access_request.pk,
        "agent": {
            "id": agent.pk,
            "display_name": agent.display_name or agent.get_username(),
            "bitrix_user_id": agent.bitrix_user_id or "",
        },
        "message": access_request.message,
        "status": access_request.status,
        "created_at": access_request.created_at.isoformat(),
    }


def _require_admin(request):
    if not request.user.has_admin_rights:
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)
    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def access_request(request):
    """Ask an admin for a number to work.

    Any signed-in agent may send one — the people who need it are exactly the
    ones with nothing assigned, so this cannot be gated on having a number.

    Sending again while a request is still open edits that request rather than
    filing another: pressing the button twice should not put the same person in
    an admin's list twice, and a second attempt usually means they thought of a
    better way to say it.
    """
    from .models import AccessRequest

    message = str(request.data.get("message", "")).strip()[:2000]
    # An empty request tells the admin nothing about who is asking or what for,
    # and they cannot come back and ask — the sender is waiting on them.
    if not message:
        return Response(
            {"detail": "Say which number you need, or who you work with."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    existing = AccessRequest.objects.filter(
        agent=request.user, status=AccessRequest.Status.PENDING
    ).first()

    if existing:
        if message and message != existing.message:
            existing.message = message
            existing.save(update_fields=["message"])
        created = existing
    else:
        created = AccessRequest.objects.create(agent=request.user, message=message)

    payload = _serialize_request(created)

    from apps.inbox.events import publish_to_admins

    publish_to_admins("access.requested", {"request": payload})

    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def access_request_list(request):
    """Everyone waiting to be given a number. Admins only.

    Open requests only, newest first — that is the queue, and it is what the
    badge counts. ?all=1 adds the ones already dealt with, for an admin who
    wants the history; ?status= picks one state outright.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    from .models import AccessRequest

    queryset = AccessRequest.objects.select_related("agent")
    wanted = request.GET.get("status", "")
    if wanted in AccessRequest.Status.values:
        queryset = queryset.filter(status=wanted)
    elif request.GET.get("all") != "1":
        queryset = queryset.filter(status=AccessRequest.Status.PENDING)

    return Response([_serialize_request(r) for r in queryset[:200]])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def access_request_resolve(request, pk):
    """Mark a request as dealt with. Admins only.

    Deliberately grants nothing: access is the number assignment, made on the
    Numbers screen. This only clears the request from the queue, so resolving
    one by mistake costs a click rather than someone's access.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    from .models import AccessRequest

    try:
        found = AccessRequest.objects.get(pk=pk)
    except AccessRequest.DoesNotExist:
        return Response({"detail": "No such request"}, status=status.HTTP_404_NOT_FOUND)

    if found.status != AccessRequest.Status.RESOLVED:
        found.resolve(request.user)

    return Response({"ok": True})
