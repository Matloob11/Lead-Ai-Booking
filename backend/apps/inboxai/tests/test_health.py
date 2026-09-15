from apps.inboxai.health_rules import coerce_result, looks_like_clean_reason


def test_false_red_reason_becomes_green():
    result = coerce_result(
        {"category": "red", "confidence": 0.9, "reason": "Normal clean conversation with no integrity risk"}
    )
    assert result["category"] == "green"


def test_real_red_stays_red():
    result = coerce_result(
        {
            "category": "red",
            "reason": "Agent asked the client to send commission to a personal account",
        }
    )
    assert result["category"] == "red"


def test_unknown_colour_falls_back_to_green():
    result = coerce_result({"category": "purple", "reason": "whatever"})
    assert result["category"] == "green"


def test_pink_and_white_pass_through():
    assert coerce_result({"category": "pink", "reason": "Client abusive"})["category"] == "pink"
    assert coerce_result({"category": "white", "reason": "Closing discussed"})["category"] == "white"
    assert coerce_result({"category": "yellow", "reason": "Budget too low"})["category"] == "yellow"


def test_clean_reason_helper():
    assert looks_like_clean_reason("This is a normal chat with no problems")
    assert not looks_like_clean_reason("Deal moving outside the company")
    assert not looks_like_clean_reason("")
