from django.urls import path

from . import bulk_views, crm_media, rotate_views, views

urlpatterns = [
    path("", views.campaign_list, name="campaign-list"),
    path("preview/", views.campaign_preview, name="campaign-preview"),
    path("rotate/pool/", rotate_views.rotate_pool, name="campaign-rotate-pool"),
    path("rotate/history/", rotate_views.rotate_history, name="campaign-rotate-history"),
    path("rotate/start/", rotate_views.rotate_start, name="campaign-rotate-start"),
    path("rotate/<int:pk>/", rotate_views.rotate_detail, name="campaign-rotate-detail"),
    path("rotate/<int:pk>/failed.csv", rotate_views.rotate_failed, name="campaign-rotate-failed"),
    path("rotate/<int:pk>/resend/", rotate_views.rotate_resend, name="campaign-rotate-resend"),
    # Excel batches — one sheet across many numbers. Own module, own screen.
    path("bulk/", bulk_views.batch_list, name="campaign-batch-list"),
    path("bulk/inspect/", bulk_views.batch_inspect, name="campaign-batch-inspect"),
    path("bulk/preview/", bulk_views.batch_preview, name="campaign-batch-preview"),
    path("bulk/<int:pk>/", bulk_views.batch_detail, name="campaign-batch-detail"),
    path("bulk/<int:pk>/cancel/", bulk_views.batch_cancel, name="campaign-batch-cancel"),
    path("crm-leads/context/", views.crm_leads_context, name="campaign-crm-leads-context"),
    path("crm-leads/busy/", views.crm_leads_busy, name="campaign-crm-leads-busy"),
    path("crm-leads/send/", views.crm_leads_send, name="campaign-crm-leads-send"),
    # Header image / video / document for any CRM popup. Raw bytes, HMAC, no session.
    path("crm-header-media/", crm_media.crm_header_media, name="campaign-crm-header-media"),
    path("crm-renewals/context/", views.crm_renewals_context, name="campaign-crm-renewals-context"),
    path("crm-renewals/send/", views.crm_renewals_send, name="campaign-crm-renewals-send"),
    path("<int:pk>/resend-skipped/", views.campaign_resend_skipped, name="campaign-resend-skipped"),
    path("<int:pk>/", views.campaign_detail, name="campaign-detail"),
]
