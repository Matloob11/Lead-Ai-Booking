from django.urls import path

from . import purge, views

app_name = "catalog"

urlpatterns = [
    path("numbers/", views.number_list, name="number-list"),
    path("numbers/test/", views.test_number, name="number-test"),
    path("numbers/<int:pk>/templates/", views.number_templates, name="number-templates"),
    path("templates/all/", views.all_templates, name="template-all"),
    path("templates/create/", views.create_template, name="template-create"),
    path("templates/create-bulk/", views.create_template_bulk, name="template-create-bulk"),
    path("templates/header-media/", views.template_header_media, name="template-header-media"),
    path("templates/<int:pk>/deploy/", views.deploy_template, name="template-deploy"),
    path("templates/<int:pk>/purge-meta/", purge.purge_template_meta, name="template-purge-meta"),
    path("templates/<int:pk>/", views.delete_template, name="template-delete"),
    path("templates/utility-suggestions/", views.suggest_utility_templates, name="template-utility-suggestions"),
    path("numbers/<int:pk>/", views.update_number, name="number-update"),
    path("numbers/<int:pk>/agents/", views.number_agents, name="number-agents"),
    path("sync/", views.sync_now, name="sync-now"),
    path("agents/", views.agent_list, name="agent-list"),
    path("agents/<int:pk>/admin/", views.set_agent_admin, name="agent-admin"),
]
