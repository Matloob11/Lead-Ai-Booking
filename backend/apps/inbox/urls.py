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
    path("messages/<int:pk>/retry/", views.retry, name="retry"),
    path("start/", views.start, name="start"),
    path("media/upload/", views.media_upload, name="media-upload"),
    path("media/<int:pk>/", views.media_download, name="media-download"),
]
