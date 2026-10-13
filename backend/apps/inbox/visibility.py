"""Who may open which Official WhatsApp thread.

Ownership is ``assigned_agent``. Covering a number is not a roster of every
chat on it: a backup on the same line, or a Bitrix portal admin, must not see
a colleague's threads. Panel admins (``is_wa_admin``) still see every chat so
they can move work.
"""

from django.db.models import Q

from apps.catalog.models import NumberAssignment, WabaNumber


def sees_all_inbox_chats(user):
    return bool(getattr(user, "is_wa_admin", False) or getattr(user, "is_superuser", False))


def held_numbers(user):
    """Numbers this person is actually assigned to — not the admin dump."""
    if not getattr(user, "can_official_api", True):
        return WabaNumber.objects.none()
    return WabaNumber.objects.filter(
        is_active=True,
        assignments__agent=user,
        assignments__is_active=True,
    ).distinct()


def visible_conversation_q(user, held=None):
    if sees_all_inbox_chats(user):
        return Q(number__in=user.visible_numbers) | Q(assigned_agent=user)
    if held is None:
        held = held_numbers(user)
    return Q(assigned_agent=user) | Q(assigned_agent__isnull=True, number__in=held)


def primary_agent_for(number):
    row = (
        NumberAssignment.objects.filter(
            number=number,
            is_active=True,
            role=NumberAssignment.Role.PRIMARY,
        )
        .select_related("agent")
        .first()
    )
    if row:
        return row.agent
    row = (
        NumberAssignment.objects.filter(number=number, is_active=True)
        .select_related("agent")
        .first()
    )
    return row.agent if row else None


def claim_unassigned(conversation):
    """First inbound on a number belongs to that number's primary agent."""
    if conversation.assigned_agent_id:
        return conversation
    owner = primary_agent_for(conversation.number)
    if owner is None:
        return conversation
    conversation.assigned_agent = owner
    conversation.save(update_fields=["assigned_agent"])
    return conversation
