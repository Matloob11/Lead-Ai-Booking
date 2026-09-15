from apps.gateway.ingest import describe, stored_body


def test_button_reply_stored_in_body():
    message = {
        "type": "button",
        "button": {"text": "Yes, still available"},
    }
    preview = describe(message)
    assert preview == "Yes, still available"
    assert stored_body("button", preview, "") == "Yes, still available"


def test_interactive_button_reply_stored_in_body():
    message = {
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"title": "Book viewing"}},
    }
    preview = describe(message)
    assert preview == "Book viewing"
    assert stored_body("interactive", preview, "") == "Book viewing"


def test_contacts_name_and_phone_stored_in_body():
    message = {
        "type": "contacts",
        "contacts": [
            {
                "name": {"formatted_name": "Ahmed Khan", "first_name": "Ahmed"},
                "phones": [{"phone": "+971501234567", "wa_id": "971501234567"}],
            }
        ],
    }
    preview = describe(message)
    assert preview == "Ahmed Khan +971501234567"
    assert stored_body("contacts", preview, "") == "Ahmed Khan +971501234567"


def test_album_count_preview():
    message = {"type": "album", "album": [{}, {}, {}]}
    preview = describe(message)
    assert preview == "3 photos"
    assert stored_body("album", preview, "") == "3 photos"
