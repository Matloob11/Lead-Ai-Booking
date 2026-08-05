from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok", "service": "a7-whatsapp-inbox"})


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/gateway/", include("apps.gateway.urls")),
    path("api/reports/", include("apps.reports.urls")),
    path("api/catalog/", include("apps.catalog.urls")),
    path("api/inbox/", include("apps.inbox.urls")),
    path("api/crm/", include("apps.crmlink.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    # The same app under the name it actually has. /api/auth/ came first and the
    # panel's sign-in path is wired to it, so it stays; everything added since
    # is addressed as /api/accounts/, which is where callers look for it.
    path("api/accounts/", include("apps.accounts.urls", namespace="accounts-api")),
]
