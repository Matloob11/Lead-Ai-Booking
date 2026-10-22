from django.urls import path

from . import bitrix_views, media_views, views

app_name = "leadai"

urlpatterns = [
    path("chats/", views.chat_list, name="chat-list"),
    path("chats/<int:pk>/", views.chat_detail, name="chat-detail"),
    path("chats/<int:pk>/move-to-inbox/", views.chat_move_to_inbox, name="chat-move-to-inbox"),
    path("chats/<int:pk>/pause-ai/", views.chat_pause_ai, name="chat-pause-ai"),
    path("chats/<int:pk>/resume-ai/", views.chat_resume_ai, name="chat-resume-ai"),
    # The co-pilot (assistant/copilot.py): the agent's question as a draft, the draft used, the draft dropped.
    path("chats/<int:pk>/draft/ask/", views.chat_draft_ask, name="chat-draft-ask"),
    path("chats/<int:pk>/draft/used/", views.chat_draft_used, name="chat-draft-used"),
    path("chats/<int:pk>/draft/dismiss/", views.chat_draft_dismiss, name="chat-draft-dismiss"),
    path("chats/<int:pk>/appointment/cancel/", views.appointment_cancel, name="appointment-cancel"),
    # The agent desk (batch 2e): I'll call, and the counts on Needs a person and Today.
    path("chats/<int:pk>/appointment/take/", views.appointment_take, name="appointment-take"),
    path("desk/", views.desk_counts, name="desk-counts"),
    # The handover desk (handover_desk.py): the responsible's own chats, and their Done.
    path("desk/mine/", views.desk_mine, name="desk-mine"),
    path("chats/<int:pk>/desk/done/", views.desk_done, name="desk-done"),
    path("settings/", views.assistant_settings, name="settings"),
    # The daily digests (assistant/digest.py) for the Reports dialog: the stored days and today so far.
    path("digests/", views.digests, name="digests"),
    # The community packs (assistant/communities.py): the list for the panel; edited in Django admin for now.
    path("communities/", views.communities, name="communities"),
    path("communities/new/", views.community_create, name="community-create"),
    path("communities/<int:pk>/", views.community_detail, name="community-detail"),
    # The shops playbook's media library (board T30).
    path("shop-media/", media_views.library, name="shop-media"),
    path("shop-media/reorder/", media_views.reorder, name="shop-media-reorder"),
    path("shop-media/<int:pk>/", media_views.item, name="shop-media-item"),
    path("shop-media/<int:pk>/replace/", media_views.replace, name="shop-media-replace"),
    path("shop-media/<int:pk>/file/", media_views.file, name="shop-media-file"),
    # The studio and one-bedroom photo sets (batch 2e slice E, board T96): read only.
    path("unit-media/", media_views.unit_library, name="unit-media"),
    path("unit-media/<int:pk>/file/", media_views.unit_file, name="unit-media-file"),
    # A person's Bot Status in Bitrix (board T52, C12): signed, no session.
    path("bitrix/bot-status/", bitrix_views.bot_status, name="bitrix-bot-status"),
    # An Availability card added or changed in Bitrix (Cursor's C46 webhook): signed, no session; the card is read again.
    path("inventory/bitrix/", bitrix_views.inventory_event, name="inventory-bitrix"),
    # A lead created in Bitrix (Cursor's C67 webhook, round 22): signed, no session; the new-lead greet follows.
    path("bitrix/new-lead/", bitrix_views.new_lead, name="bitrix-new-lead"),
]
