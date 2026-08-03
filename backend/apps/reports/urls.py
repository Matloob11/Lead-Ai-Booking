from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("summary/", views.summary, name="summary"),
    path("agents/", views.agents, name="agents"),
    path("numbers/", views.numbers, name="numbers"),
    path("failures/", views.failures, name="failures"),
    path("templates/", views.templates, name="templates"),
]
