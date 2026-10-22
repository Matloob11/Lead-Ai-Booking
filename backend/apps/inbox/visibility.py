"""Who may open which Official WhatsApp thread.

Ownership is ``assigned_agent``. Covering a number is not a roster of every
chat on it: a backup on the same line, or a Bitrix portal admin, must not see
a colleague's threads. Panel admins (``is_wa_admin``) still see every chat so
they can move work.

One exception, for the Lead AI screen only (apps/leadai/lane.py, Q37): an
agent with Lead AI access (``can_lead_ai``) also opens every chat on that
screen, whatever its number. The main inbox list leaves those chats out.

A second, narrower one (apps/leadai/handover_desk.py, 2026-10-22): the Bitrix
responsible of a lead whose Lead AI chat was handed to a person opens that chat,
and only that chat, on their own "My handovers" screen.
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
    visible = Q(assigned_agent=user) | Q(assigned_agent__isnull=True, number__in=held)
    # The Lead AI desk: every Lead AI chat for an agent with Lead AI access (None for anyone else).
    from apps.leadai.lane import desk_q

    desk = desk_q(user)
    if desk is not None:
        visible |= desk
    # The handover desk (apps/leadai/handover_desk.py): the Lead AI chats handed to a person whose Bitrix responsible
    # this agent is, and nothing else of the Lead AI screen (None for an agent who cannot have a desk).
    from apps.leadai.handover_desk import mine_q

    mine = mine_q(user)
    if mine is not None:
        visible |= mine
    # staff_only is a rotate-campaign thread. The assignee of that number must
    # not see it, including when the chat is still unclaimed.
    return visible & ~Q(staff_only=True)


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
