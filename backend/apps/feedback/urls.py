from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("<int:pk>/solve/", views.report_solve, name="solve"),
    path("<int:pk>/files/<int:file_id>/", views.report_file, name="file"),
]
