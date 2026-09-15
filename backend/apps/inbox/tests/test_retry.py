from unittest.mock import Mock, patch

from apps.inbox.models import Message
from apps.inbox.services import SendBlocked, retry_message


def _failed(**kwargs):
    msg = Mock()
    msg.status = Message.Status.FAILED
    msg.direction = Message.Direction.OUTBOUND
    msg.kind = Message.Kind.TEXT
    msg.payload = {}
    msg.body = ""
    msg.template = None
    msg.media = None
    msg.conversation = Mock()
    for key, value in kwargs.items():
        setattr(msg, key, value)
    return msg


def test_retry_location_resends_pin():
    msg = _failed(
        kind=Message.Kind.LOCATION,
        payload={"location": {"latitude": 25.2, "longitude": 55.27, "name": "Marina", "address": "Dubai"}},
    )
    with patch("apps.inbox.services.send_location", return_value="sent") as send:
        assert retry_message(msg, Mock()) == "sent"
        send.assert_called_once()
        args, kwargs = send.call_args
        assert args[2] == 25.2
        assert args[3] == 55.27
        assert kwargs["name"] == "Marina"


def test_retry_interactive_rebuilds_buttons():
    msg = _failed(
        kind=Message.Kind.INTERACTIVE,
        body="Pick one",
        payload={
            "interactive": {
                "type": "button",
                "body": {"text": "Pick one"},
                "header": {"type": "text", "text": "Hi"},
                "footer": {"text": "Thanks"},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "yes", "title": "Yes"}},
                        {"type": "reply", "reply": {"id": "no", "title": "No"}},
                    ]
                },
            }
        },
    )
    with patch("apps.inbox.services.send_buttons", return_value="sent") as send:
        assert retry_message(msg, Mock()) == "sent"
        send.assert_called_once()
        args, kwargs = send.call_args
        assert args[2] == "Pick one"
        assert args[3] == [{"id": "yes", "title": "Yes"}, {"id": "no", "title": "No"}]
        assert kwargs["header"] == "Hi"
        assert kwargs["footer"] == "Thanks"


def test_retry_location_without_coords_is_blocked():
    msg = _failed(kind=Message.Kind.LOCATION, payload={"location": {}})
    try:
        retry_message(msg, Mock())
    except SendBlocked as exc:
        assert "coordinates" in str(exc).lower()
    else:
        raise AssertionError("expected SendBlocked")
