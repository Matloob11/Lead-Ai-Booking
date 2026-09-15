from types import SimpleNamespace

from apps.inbox.serializers import _album_count, _contact_cards, _pinned_preview


def test_contact_cards_from_meta_blob():
    message = SimpleNamespace(
        kind="contacts",
        payload={
            "contacts": [
                {
                    "name": {"formatted_name": "Sara Ali"},
                    "phones": [{"phone": "+971509998877"}],
                }
            ]
        },
    )
    assert _contact_cards(message) == [{"name": "Sara Ali", "phones": ["+971509998877"]}]


def test_album_count_from_list():
    message = SimpleNamespace(kind="album", payload={"album": [{}, {}]})
    assert _album_count(message) == 2


def test_pinned_preview_uses_payload_text_without_lookup():
    message = SimpleNamespace(
        kind="pinned_message",
        payload={"pinned_message": {"type": "text", "text": {"body": "See you at 4"}}},
    )
    assert _pinned_preview(message)["body"] == "See you at 4"
