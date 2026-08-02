"""Live updates pushed to the panel over WebSocket.

Everyone assigned to a number sees the same stream — chats are not hidden behind
ownership — so the channel group is keyed on the number, not the agent.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def group_for_number(number_id):
    return f"wa.number.{number_id}"


def publish(conversation, event, data):
    layer = get_channel_layer()
    if layer is None:
        return

    message = {"type": "inbox.event", "event": event, "data": {**data, "number_id": conversation.number_id}}
    try:
        async_to_sync(layer.group_send)(group_for_number(conversation.number_id), message)
    except Exception:  # noqa: BLE001 - a dead socket must not fail the write path
        logger.exception("Failed to publish %s for conversation %s", event, conversation.pk)
