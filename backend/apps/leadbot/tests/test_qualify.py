from apps.leadbot.qualify import decide


def test_client_handover():
    out = decide({"for_self_or_client": "client"})
    assert out["stop"] is True
    assert out["status_id"] == "12"


def test_opt_out_junk():
    out = decide({"not_interested": True})
    assert out["status_id"] == "JUNK"
    assert out["stop"] is True


def test_viewing_qualifies():
    out = decide(
        {},
        confirmed={"viewing_time": "tomorrow 5pm", "for_self_or_client": "myself", "move_in_date": "1 Oct"},
    )
    assert out["qualified"] is True
    assert out["status_id"] == "12"


def test_incomplete_keeps_going():
    out = decide({}, confirmed={"for_self_or_client": "myself"})
    assert out["stop"] is False


def test_human_request():
    out = decide({"handover_to_human": True})
    assert out["status_id"] == "UC_MJDO60"
