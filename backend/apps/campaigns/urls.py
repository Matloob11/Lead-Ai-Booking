from django.urls import path

from . import views

urlpatterns = [
    path("", views.campaign_list, name="campaign-list"),
    path("preview/", views.campaign_preview, name="campaign-preview"),
    path("<int:pk>/resend-skipped/", views.campaign_resend_skipped, name="campaign-resend-skipped"),
    path("<int:pk>/", views.campaign_detail, name="campaign-detail"),
]
