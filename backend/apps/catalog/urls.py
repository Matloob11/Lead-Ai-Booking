from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("numbers/", views.number_list, name="number-list"),
    path("numbers/<int:pk>/templates/", views.number_templates, name="number-templates"),
    path("templates/all/", views.all_templates, name="template-all"),
    path("templates/create/", views.create_template, name="template-create"),
    path("numbers/<int:pk>/", views.update_number, name="number-update"),
    path("numbers/<int:pk>/agents/", views.number_agents, name="number-agents"),
    path("sync/", views.sync_now, name="sync-now"),
    path("agents/", views.agent_list, name="agent-list"),
    path("agents/<int:pk>/admin/", views.set_agent_admin, name="agent-admin"),
]
