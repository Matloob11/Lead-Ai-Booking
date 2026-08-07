from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("bitrix/", views.bitrix_login, name="bitrix-login"),
    path("me/", views.me, name="me"),
    # Asked by nginx before it proxies /qr/ — see admin_gate.
    path("gate/", views.admin_gate, name="admin-gate"),
    # Asked by nginx before it proxies OpenWA (port 2786) — see openwa_gate.
    path("openwa-gate/", views.openwa_gate, name="openwa-gate"),
    path("openwa-credentials/", views.openwa_credentials, name="openwa-credentials"),
    # The linked-phone roster, admin only. Same shape as the number roster:
    # read the list, PUT the state you want.
    path("openwa-sessions/", views.openwa_sessions, name="openwa-sessions"),
    path(
        "openwa-sessions/<str:session_id>/agents/",
        views.openwa_session_agents,
        name="openwa-session-agents",
    ),
    # Called by the OpenWA gateway, not by a browser: authenticated by a shared
    # secret header rather than a session (see the view).
    path("device-alert/", views.device_disconnected_alert, name="device-alert"),
    path("access-request/", views.access_request, name="access-request"),
    path("access-requests/", views.access_request_list, name="access-request-list"),
    path(
        "access-requests/<int:pk>/resolve/",
        views.access_request_resolve,
        name="access-request-resolve",
    ),
]
