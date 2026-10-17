from django.urls import path

from . import bitrix_views, media_views, views

app_name = "leadai"

urlpatterns = [
    path("chats/", views.chat_list, name="chat-list"),
    path("chats/<int:pk>/", views.chat_detail, name="chat-detail"),
    path("chats/<int:pk>/move-to-inbox/", views.chat_move_to_inbox, name="chat-move-to-inbox"),
    path("chats/<int:pk>/pause-ai/", views.chat_pause_ai, name="chat-pause-ai"),
    path("chats/<int:pk>/resume-ai/", views.chat_resume_ai, name="chat-resume-ai"),
    path("chats/<int:pk>/appointment/cancel/", views.appointment_cancel, name="appointment-cancel"),
    path("settings/", views.assistant_settings, name="settings"),
    # The shops playbook's media library (board T30).
    path("shop-media/", media_views.library, name="shop-media"),
    path("shop-media/reorder/", media_views.reorder, name="shop-media-reorder"),
    path("shop-media/<int:pk>/", media_views.item, name="shop-media-item"),
    path("shop-media/<int:pk>/replace/", media_views.replace, name="shop-media-replace"),
    path("shop-media/<int:pk>/file/", media_views.file, name="shop-media-file"),
    # The studio and one-bedroom photo sets (batch 2e slice E, board T96): read only.
    path("unit-media/", media_views.unit_library, name="unit-media"),
    path("unit-media/<int:pk>/file/", media_views.unit_file, name="unit-media-file"),
    # A person's Bot Status in Bitrix (board T52, C12): signed, no session.
    path("bitrix/bot-status/", bitrix_views.bot_status, name="bitrix-bot-status"),
]
