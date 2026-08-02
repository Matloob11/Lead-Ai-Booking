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
        "bitrix_user_id": agent.bitrix_user_id,
        "display_name": agent.display_name or agent.get_full_name() or agent.username,
        "avatar_url": agent.avatar_url,
        # One flag for the panel; where the right came from is not its concern.
        "is_wa_admin": agent.has_admin_rights,
        "numbers": [serialize_number(n) for n in agent.visible_numbers],
        # What the gateway will forward, so the panel hides buttons that could
        # only ever fail rather than showing an agent a dead control.
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
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(_serialize(request.user))
