from django.urls import path

from . import views

app_name = "inboxai"

urlpatterns = [
    path("desk/", views.desk, name="desk"),
    path("conversations/<int:pk>/cover/", views.conversation_cover, name="cover"),
    path("candidates/", views.candidates, name="candidates"),
    path("health/summary/", views.health_summary, name="health-summary"),
    path("health/list/", views.health_list, name="health-list"),
    path("health/allow-green/", views.health_allow_green, name="health-allow-green"),
    path("health/reclassify-false-red/", views.health_reclassify_false_red, name="health-reclassify"),
    path("health/analyse/", views.health_analyse, name="health-analyse"),
]
