from apps.gateway.parse import (
    PLACEHOLDER_BODY,
    customer_wa_id,
    digits,
    is_group_recipient,
    is_our_sender,
    iter_message_blobs,
)


class _Number:
    phone_number = "971559668904"
    phone_number_id = "111111111111111"


def test_digits_strips_plus_and_spaces():
    assert digits("+971 55 966 8904") == "971559668904"


def test_is_our_sender_matches_display_and_msisdn():
    number = _Number()
    metadata = {"display_phone_number": "971559668904", "phone_number_id": number.phone_number_id}
    assert is_our_sender(number, "971559668904", metadata)
    assert not is_our_sender(number, "971509034652", metadata)


def test_group_jids_are_skipped():
    assert is_group_recipient("120363@g.us")
    assert not is_group_recipient("971509034652")


def test_iter_includes_echo_arrays_as_outbound():
    value = {
        "messages": [{"id": "in1", "from": "97150"}],
        "smb_message_echoes": [{"id": "out1", "from": "97155", "to": "97150"}],
        "statuses": [{"id": "out1", "status": "sent"}],
    }
    blobs = list(iter_message_blobs(value))
    assert blobs[0][1] is False
    assert blobs[1][0]["id"] == "out1"
    assert blobs[1][1] is True


def test_outbound_customer_comes_from_to_not_from():
    number = _Number()
    metadata = {"display_phone_number": number.phone_number}
    blob = {"from": number.phone_number, "to": "971509034652", "id": "wamid.x"}
    assert customer_wa_id(blob, number, metadata, {}, outbound=True) == "971509034652"
    assert customer_wa_id(blob, number, metadata, {}, outbound=False) == "971559668904"


def test_placeholder_is_english():
    assert PLACEHOLDER_BODY == "Sent from WhatsApp"


def test_live_chat_wamid_picks_the_matching_row():
    from apps.gateway.parse import preview_for_wamid

    rows = [
        {"messageId": "wamid.a", "messageType": "text", "messageText": "first"},
        {"messageId": "wamid.b", "messageType": "image", "messageText": "villa"},
    ]
    assert preview_for_wamid(rows, "wamid.b") == ("villa", "image")
    assert preview_for_wamid(rows, "wamid.missing") == ("", "")
    assert preview_for_wamid(
        [{"messageId": "wamid.c", "messageType": "document", "messageText": ""}],
        "wamid.c",
    ) == ("[document]", "document")


def test_extract_graph_text_and_nested_messages():
    from apps.gateway.parse import extract_graph_message_text

    assert extract_graph_message_text({"type": "text", "text": {"body": "hello"}}) == ("hello", "text")
    assert extract_graph_message_text({"messages": [{"text": {"body": "nested"}}]})[0] == "nested"
    assert extract_graph_message_text({"type": "image", "image": {"caption": "villa"}}) == ("villa", "image")


def test_alots_flat_outbound_normalizes_to_echo_with_body():
    from apps.gateway.parse import iso_to_unix, is_alots_flat_outbound, normalize_webhook_payload

    flat = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "918691012428",
        "type": "text",
        "text": {"preview_url": False, "body": "Hello"},
        "id": "wamid.ABC",
        "from": "15559560222",
        "phone_number_id": "1125019977360712",
        "waba_business_id": "866093279133906",
        "datetime": "2026-08-25T06:15:30.7187042+00:00",
        "sendername": "DemoWBX",
    }
    assert is_alots_flat_outbound(flat)
    assert iso_to_unix(flat["datetime"]).isdigit()

    wrapped = normalize_webhook_payload(flat)
    value = wrapped["entry"][0]["changes"][0]["value"]
    assert value["metadata"]["phone_number_id"] == "1125019977360712"
    echo = value["smb_message_echoes"][0]
    assert echo["text"]["body"] == "Hello"
    assert echo["to"] == "918691012428"
    assert echo["timestamp"]

    blobs = list(iter_message_blobs(value))
    assert len(blobs) == 1 and blobs[0][1] is True
    assert blobs[0][0]["id"] == "wamid.ABC"


def test_alots_flat_outbound_without_phone_number_id():
    """Phone-app path: body present, phone_number_id missing, to has +."""
    from apps.gateway.parse import is_alots_flat_outbound, normalize_webhook_payload

    flat = {
        "to": "+971585810347",
        "from": "971559430556",
        "type": "text",
        "text": {"body": "Hi sir good morning", "preview_url": False},
        "id": "wamid.NO_PNID",
        "datetime": "2026-08-25T06:50:19.8397573+00:00",
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
    }
    assert is_alots_flat_outbound(flat)
    wrapped = normalize_webhook_payload(flat)
    value = wrapped["entry"][0]["changes"][0]["value"]
    assert value["metadata"]["phone_number_id"] == ""
    assert value["metadata"]["display_phone_number"] == "971559430556"
    echo = value["smb_message_echoes"][0]
    assert echo["to"] == "971585810347"
    assert echo["text"]["body"] == "Hi sir good morning"


def test_alots_coexistence_flat_without_id():
    """Alots coexistence sample: to + text.body, no wamid / from."""
    from apps.gateway.parse import is_alots_flat_outbound, normalize_webhook_payload

    flat = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919428587817",
        "type": "text",
        "text": {"preview_url": False, "body": "Hello"},
        "phone_number_id": "1266282383224189",
    }
    assert is_alots_flat_outbound(flat)
    wrapped = normalize_webhook_payload(flat)
    value = wrapped["entry"][0]["changes"][0]["value"]
    assert value["metadata"]["phone_number_id"] == "1266282383224189"
    echo = value["smb_message_echoes"][0]
    assert echo["text"]["body"] == "Hello"
    assert echo["to"] == "919428587817"
    assert not echo.get("id")


def test_alots_coexistence_bare_messages_fragment():
    """Inbound-shaped messages[] with from_user_id, no entry wrapper."""
    from apps.gateway.parse import normalize_webhook_payload, iter_message_blobs

    payload = {
        "messages": [
            {
                "from": "919428587817",
                "from_user_id": "IN.883250621329146",
                "id": "wamid.SAMPLE",
                "timestamp": "1787639208",
                "text": {"body": "How are you"},
                "type": "text",
            }
        ],
        "metadata": {
            "phone_number_id": "1339159432604269",
            "display_phone_number": "971559791401",
        },
    }
    wrapped = normalize_webhook_payload(payload)
    value = wrapped["entry"][0]["changes"][0]["value"]
    assert value["metadata"]["phone_number_id"] == "1339159432604269"
    blobs = list(iter_message_blobs(value))
    assert len(blobs) == 1 and blobs[0][1] is False
    assert blobs[0][0]["text"]["body"] == "How are you"
    assert blobs[0][0]["from_user_id"] == "IN.883250621329146"


def test_meta_envelope_unchanged_by_normalize():
    from apps.gateway.parse import normalize_webhook_payload

    payload = {"entry": [{"changes": [{"value": {"messages": [{"id": "1"}]}}]}]}
    assert normalize_webhook_payload(payload) is payload

