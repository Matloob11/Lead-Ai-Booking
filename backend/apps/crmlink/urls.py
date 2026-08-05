from django.urls import path

from . import views

app_name = "crmlink"

urlpatterns = [
    # Where a WhatsApp number lives in the CRM — lead, contact, Owner Data.
    path("whereis/", views.whereis, name="whereis"),
]
