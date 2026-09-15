from apps.inboxai.eligibility import (
    desk_covers,
    is_ai_outbound_payload,
    last_ours_is_human,
    reply_language,
    should_skip_inbound_kind,
    stack_context,
)


def test_desk_all_covers_everything():
    assert desk_covers(scope="all", is_selected=False, has_human_outbound=True)


def test_desk_new_skips_chats_a_human_already_answered():
    assert desk_covers(scope="new", is_selected=False, has_human_outbound=False)
    assert not desk_covers(scope="new", is_selected=False, has_human_outbound=True)


def test_desk_selected_only_picked_chats():
    assert desk_covers(scope="selected", is_selected=True, has_human_outbound=True)
    assert not desk_covers(scope="selected", is_selected=False, has_human_outbound=False)


def test_desk_off_covers_nothing():
    assert not desk_covers(scope="off", is_selected=True, has_human_outbound=False)


def test_ai_payload_is_not_human_takeover():
    assert is_ai_outbound_payload({"source": "ai_desk"})
    assert not last_ours_is_human({"sent_by_id": 1, "payload": {"source": "ai_desk"}})
    assert last_ours_is_human({"sent_by_id": 1, "payload": {}})
    assert not last_ours_is_human(None)


def test_reactions_are_skipped():
    assert should_skip_inbound_kind("reaction")
    assert not should_skip_inbound_kind("text")


def test_arabic_inbound_keeps_that_language():
    note = reply_language("السلام عليكم")
    assert "Arabic" in note
    assert "English" in reply_language("Hello")


def test_context_stacks_global_then_chat():
    stacked = stack_context("Be brief.", "This buyer wants a 2BR in JVC.")
    assert stacked.startswith("GLOBAL INSTRUCTIONS:")
    assert "THIS CHAT:" in stacked
    assert "JVC" in stacked
