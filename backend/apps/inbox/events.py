"""Live updates pushed to the panel over WebSocket.

Panel admins still subscribe to the number group. Agents only hear the
channel keyed on themselves; ``publish`` always fans out there as well.

Payloads carry the whole object rather than an id. A pushed message should be
renderable on arrival; making the panel fetch what we already have in hand adds
a round trip to the one path where latency is visible.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def group_for_number(number_id):
    return f"wa.number.{number_id}"


def group_for_agent(agent_id):
    """A channel for things meant for one person, like their own reminders."""
    return f"wa.agent.{agent_id}"


ADMIN_GROUP = "wa.admins"


def group_for_admins():
    """Everyone administering the panel, whichever numbers they happen to hold.

    Number groups cannot carry this: an access request belongs to no number,
    and the agent making it has none.
    """
    return ADMIN_GROUP


def _send(group, event, data):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group, {"type": "inbox.event", "event": event, "data": data}
        )
    except Exception:  # noqa: BLE001 - a dead socket must not fail the caller
        logger.exception("Failed to publish %s to %s", event, group)


def publish_to_agent(agent_id, event, data):
    _send(group_for_agent(agent_id), event, data)


def publish_to_admins(event, data):
    _send(ADMIN_GROUP, event, data)


def publish(conversation, event, data):
    layer = get_channel_layer()
    if layer is None:
        return

    # A chat in the Lead AI screen is heard there, under "leadai.<event>"; the
    # main inbox does not listen for those, so it never shows the chat. Routing
    # must never stop a live event, so any failure keeps the plain name. The
    # agents with Lead AI access hear those events on the desk's own group.
    extra_groups, scoped_groups, scoped_data, resync_groups = [], [], None, []
    try:
        from apps.leadai.lane import desk_groups_for, event_name, ping_groups, trim_for_desk

        event = event_name(conversation, event)
        # The desk, and the chat's Bitrix responsible on the handover desk: in full, or trimmed to the chat and the
        # customer when they have the chat through the desk alone (apps/leadai/handover_desk.py).
        extra_groups, scoped_groups = desk_groups_for(event, conversation)
        if scoped_groups:
            scoped_data = trim_for_desk({**data, "number_id": conversation.number_id})
        # The agents granted a Lead AI list the chat is not in now: an id-only resync (apps/leadai/access.py).
        resync_groups = ping_groups(event, conversation)
    except Exception:  # noqa: BLE001
        logger.exception("Lead AI routing failed for conversation %s", getattr(conversation, "pk", None))
    message = {
        "type": "inbox.event",
        "event": event,
        "data": {**data, "number_id": conversation.number_id},
    }
    try:
        async_to_sync(layer.group_send)(group_for_number(conversation.number_id), message)
        # A transferred chat's owner may not be subscribed to the number group.
        agent_id = getattr(conversation, "assigned_agent_id", None)
        if agent_id:
            async_to_sync(layer.group_send)(group_for_agent(agent_id), message)
        for group in extra_groups:
            async_to_sync(layer.group_send)(group, message)
        for group in scoped_groups:
            async_to_sync(layer.group_send)(group, {**message, "data": scoped_data})
        for group in resync_groups:
            async_to_sync(layer.group_send)(
                group, {"type": "inbox.event", "event": "leadai.access.resync", "data": {"id": conversation.pk, "number_id": conversation.number_id}}
            )
    except Exception:  # noqa: BLE001 - a dead socket must not fail the write path
        logger.exception("Failed to publish %s for conversation %s", event, conversation.pk)


def publish_message(message):
    """A message arrived or was sent. Carries the message and its conversation."""
    from .serializers import serialize_conversation, serialize_message

    conversation = message.conversation
    publish(
        conversation,
        "message.new",
        {
            "message": serialize_message(message),
            "conversation": serialize_conversation(conversation),
        },
    )
    if not message.mirrored_from_id:
        from .transfer import mirror_to_peer

        mirror_to_peer(message)


def publish_status(message):
    """A delivery receipt moved a message forward, or it failed."""
    from .serializers import serialize_message

    publish(
        message.conversation,
        "message.status",
        {"message": serialize_message(message)},
    )


def publish_conversation(conversation, event="conversation.updated"):
    from .serializers import serialize_conversation

    publish(conversation, event, {"conversation": serialize_conversation(conversation)})
