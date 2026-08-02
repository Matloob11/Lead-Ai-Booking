from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("bitrix/", views.bitrix_login, name="bitrix-login"),
    path("me/", views.me, name="me"),
]
