from django.urls import path

from . import views

app_name = "inbox"

urlpatterns = [
    path("conversations/", views.conversation_list, name="conversation-list"),
    path("conversations/<int:pk>/messages/", views.message_list, name="message-list"),
    path("conversations/<int:pk>/send/", views.send, name="send"),
    path("conversations/<int:pk>/send-template/", views.send_template, name="send-template"),
    path("conversations/<int:pk>/assign/", views.assign, name="assign"),
    path("conversations/<int:pk>/read/", views.mark_read, name="mark-read"),
    path("conversations/<int:pk>/contact/", views.contact_detail, name="contact-detail"),
    path("conversations/<int:pk>/typing/", views.typing, name="typing"),
    path("conversations/<int:pk>/flags/", views.set_flags, name="set-flags"),
    path("labels/", views.label_list, name="label-list"),
    path("labels/<int:pk>/", views.label_delete, name="label-delete"),
    path("quick-replies/", views.quick_reply_list, name="quick-reply-list"),
    path("quick-replies/<int:pk>/", views.quick_reply_delete, name="quick-reply-delete"),
    path("conversations/<int:pk>/send-buttons/", views.send_buttons, name="send-buttons"),
    path("conversations/<int:pk>/send-location/", views.send_location, name="send-location"),
    path("conversations/<int:pk>/export/", views.export, name="export"),
    path("messages/<int:pk>/forward/", views.forward, name="forward"),
    path("messages/<int:pk>/star/", views.star, name="star"),
    path("starred/", views.starred, name="starred"),
    path("conversations/<int:pk>/reminders/", views.reminders, name="conversation-reminders"),
    path("reminders/", views.reminders, name="reminder-list"),
    path("reminders/<int:pk>/", views.reminder_detail, name="reminder-detail"),
    path("search/", views.search, name="search"),
    path("messages/<int:pk>/retry/", views.retry, name="retry"),
    path("start/", views.start, name="start"),
    path("shared-assets/", views.shared_asset_list, name="shared-asset-list"),
    path("shared-assets/<int:pk>/", views.shared_asset_delete, name="shared-asset-delete"),
    path(
        "shared-assets/<int:pk>/file/",
        views.shared_asset_download,
        name="shared-asset-download",
    ),
    path("media/upload/", views.media_upload, name="media-upload"),
    path("media/<int:pk>/", views.media_download, name="media-download"),
]
