"""Live updates pushed to the panel over WebSocket.

Everyone assigned to a number sees the same stream — chats are not hidden behind
ownership — so the channel group is keyed on the number, not the agent.

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


def publish_to_agent(agent_id, event, data):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group_for_agent(agent_id), {"type": "inbox.event", "event": event, "data": data}
        )
    except Exception:  # noqa: BLE001 - a dead socket must not fail the caller
        logger.exception("Failed to publish %s to agent %s", event, agent_id)


def publish(conversation, event, data):
    layer = get_channel_layer()
    if layer is None:
        return

    message = {
        "type": "inbox.event",
        "event": event,
        "data": {**data, "number_id": conversation.number_id},
    }
    try:
        async_to_sync(layer.group_send)(group_for_number(conversation.number_id), message)
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
