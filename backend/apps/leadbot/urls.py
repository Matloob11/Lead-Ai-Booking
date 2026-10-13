from django.urls import path

from . import views

app_name = "leadbot"

urlpatterns = [
    path("outreach/", views.outreach, name="outreach"),
    path("board/", views.board, name="board"),
]
