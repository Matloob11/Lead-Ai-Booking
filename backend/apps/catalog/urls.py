from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("numbers/", views.number_list, name="number-list"),
    path("numbers/<int:pk>/templates/", views.number_templates, name="number-templates"),
]
