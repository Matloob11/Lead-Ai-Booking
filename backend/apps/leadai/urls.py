from django.urls import path

from . import views

app_name = "leadai"

urlpatterns = [
    path("chats/", views.chat_list, name="chat-list"),
    path("chats/<int:pk>/", views.chat_detail, name="chat-detail"),
    path("chats/<int:pk>/move-to-inbox/", views.chat_move_to_inbox, name="chat-move-to-inbox"),
    path("chats/<int:pk>/pause-ai/", views.chat_pause_ai, name="chat-pause-ai"),
    path("chats/<int:pk>/resume-ai/", views.chat_resume_ai, name="chat-resume-ai"),
    path("chats/<int:pk>/appointment/cancel/", views.appointment_cancel, name="appointment-cancel"),
    path("settings/", views.assistant_settings, name="settings"),
]
