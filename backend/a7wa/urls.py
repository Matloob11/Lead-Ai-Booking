from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok", "service": "a7-whatsapp-inbox"})


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/gateway/", include("apps.gateway.urls")),
    path("api/catalog/", include("apps.catalog.urls")),
    path("api/inbox/", include("apps.inbox.urls")),
    path("api/auth/", include("apps.accounts.urls")),
]
