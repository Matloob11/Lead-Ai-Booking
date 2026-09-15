from apps.catalog.views import _button_components, _examples_for, _meta_error_detail
from apps.gateway.client import AlotsError


def test_meta_error_prefers_nested_message():
    exc = AlotsError("HTTP 400", payload={"error": {"message": "Button text is too long"}})
    assert _meta_error_detail(exc) == "Button text is too long"


def test_meta_error_prefers_user_msg_over_generic_invalid_parameter():
    exc = AlotsError(
        "HTTP 400",
        payload={
            "error": {
                "message": "Invalid parameter",
                "error_user_title": "Account restricted",
                "error_user_msg": "This WhatsApp Business account is restricted from creating a new template",
            }
        },
    )
    assert "restricted" in _meta_error_detail(exc).lower()


def test_meta_error_falls_back_to_detail():
    exc = AlotsError("HTTP 400", payload={"detail": "Not allowed"})
    assert _meta_error_detail(exc) == "Not allowed"


def test_examples_follow_placeholder_order():
    assert _examples_for("Hello {{2}} and {{1}}", {"1": "Ahmed", "2": "Dubai"}) == [
        "Dubai",
        "Ahmed",
    ]


def test_blank_example_gets_a_sample():
    assert _examples_for("Hi {{1}}", {}) == ["Sample 1"]


def test_url_button_carries_example_when_url_has_placeholder():
    buttons = _button_components(
        [{"type": "URL", "text": "View", "url": "https://a7.ae/{{1}}", "example": "https://a7.ae/plot"}]
    )
    assert buttons[0]["type"] == "URL"
    assert buttons[0]["example"] == ["https://a7.ae/plot"]


def test_parse_template_form_builds_payload():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {
            "name": "viewing_offer",
            "category": "UTILITY",
            "language": "en",
            "body_text": "Hello {{1}} from {{2}}",
            "body_examples": {"1": "Ahmed", "2": "Sneha"},
        }
    )
    assert err is None
    assert parsed["clean_name"] == "viewing_offer"
    assert parsed["payload"]["components"][0]["type"] == "BODY"


def test_parse_rejects_body_ending_with_variable():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {
            "name": "bad_end",
            "body_text": "Hello from {{1}}",
            "body_examples": {"1": "A7"},
        }
    )
    assert parsed is None
    assert "start or end" in err.lower()


def test_parse_rejects_footer_over_60():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {
            "name": "long_footer",
            "body_text": "Hello there",
            "footer_text": "x" * 61,
        }
    )
    assert parsed is None
    assert "60" in err
