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
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)
Agent = get_user_model()


def _serialize(agent):
    return {
        "id": agent.pk,
        "bitrix_user_id": agent.bitrix_user_id,
        "display_name": agent.display_name or agent.get_full_name() or agent.username,
        "avatar_url": agent.avatar_url,
        "is_wa_admin": agent.is_wa_admin,
        "numbers": [
            {"id": n.pk, "phone_number": n.phone_number, "display_name": n.display_name}
            for n in agent.visible_numbers
        ],
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
    agent.last_seen_at = timezone.now()
    agent.save(update_fields=["display_name", "bitrix_portal", "avatar_url", "last_seen_at"])

    login(request, agent, backend="django.contrib.auth.backends.ModelBackend")
    return Response({**_serialize(agent), "created": created})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(_serialize(request.user))
