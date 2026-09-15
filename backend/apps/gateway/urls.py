from django.urls import path

from . import views

app_name = "gateway"

urlpatterns = [
    path("webhook/alots/", views.alots_webhook, name="alots-webhook"),
    path("inspector/events/", views.inspector_webhook_events, name="inspector-events"),
]
