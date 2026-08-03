from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("bitrix/", views.bitrix_login, name="bitrix-login"),
    path("me/", views.me, name="me"),
    path("access-request/", views.access_request, name="access-request"),
    path("access-requests/", views.access_request_list, name="access-request-list"),
    path(
        "access-requests/<int:pk>/resolve/",
        views.access_request_resolve,
        name="access-request-resolve",
    ),
]
