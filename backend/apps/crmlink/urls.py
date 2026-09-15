from django.urls import path

from . import views

app_name = "crmlink"

urlpatterns = [
    # Where a WhatsApp number lives in the CRM — lead, contact, Owner Data.
    path("whereis/", views.whereis, name="whereis"),
    # Make the record this number has not got yet — a lead, or an Owner Data
    # item — and copy the conversation into its timeline.
    path("create/", views.create, name="create"),
]
