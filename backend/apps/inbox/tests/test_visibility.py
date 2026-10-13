from types import SimpleNamespace

from django.db.models import Q

from apps.inbox.visibility import sees_all_inbox_chats, visible_conversation_q


def test_bitrix_admin_is_not_a_roster_dump():
    user = SimpleNamespace(is_wa_admin=False, is_superuser=False, is_bitrix_admin=True)
    assert sees_all_inbox_chats(user) is False


def test_panel_admin_still_sees_every_chat():
    user = SimpleNamespace(is_wa_admin=True, is_superuser=False)
    assert sees_all_inbox_chats(user) is True


def test_agent_only_sees_own_and_unassigned_on_held_numbers():
    user = SimpleNamespace(is_wa_admin=False, is_superuser=False)
    held = [11, 12]
    q = visible_conversation_q(user, held=held)
    expected = Q(assigned_agent=user) | Q(assigned_agent__isnull=True, number__in=held)
    assert q == expected
