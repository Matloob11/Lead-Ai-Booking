from django.urls import path

from . import views

app_name = "gateway"

urlpatterns = [
    path("webhook/alots/", views.alots_webhook, name="alots-webhook"),
]
