from apps.inbox.services import (
    format_recipient_for_gateway,
    recipient_digits,
    recipient_mismatch_detail,
)


def test_format_recipient_adds_plus():
    assert format_recipient_for_gateway("971559298388") == "+971559298388"
    assert format_recipient_for_gateway("+971 55 929 8388") == "+971559298388"
    assert format_recipient_for_gateway("") == ""


def test_mismatch_detects_india_prefix_mangle():
    detail = recipient_mismatch_detail(
        "971559298388",
        {"contacts": [{"input": "+91971559298388", "wa_id": "91971559298388"}]},
    )
    assert detail
    assert "91" in detail
    assert "971559298388" in detail


def test_mismatch_none_when_wa_id_matches():
    assert (
        recipient_mismatch_detail(
            "971526698576",
            {"contacts": [{"input": "971526698576", "wa_id": "971526698576"}]},
        )
        is None
    )


def test_recipient_digits_strips_noise():
    assert recipient_digits("+971-55-9298388") == "971559298388"
