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
            # Ends in words on purpose: a body ending in a variable is refused
            # (test_parse_rejects_body_ending_with_variable), and this one
            # used to end in {{2}} and fail for that reason alone.
            "body_text": "Hello {{1}} from {{2}} at A7",
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


def test_parse_text_header_stays_on_the_gateway():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {
            "name": "viewing",
            "body_text": "Hello there",
            "header_text": "Hi {{1}}",
            "header_examples": {"1": "Ali"},
        }
    )
    assert err is None
    header = parsed["payload"]["components"][0]
    assert header["format"] == "TEXT"
    assert header["example"] == {"header_text": ["Ali"]}
    assert parsed["via_graph"] is False


def test_parse_media_header_needs_the_sample_handle():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {"name": "brochure", "body_text": "Hello there", "header_format": "IMAGE"}
    )
    assert parsed is None
    assert "upload the image" in err.lower()


def test_parse_media_header_builds_the_handle_component_and_routes_to_graph():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {
            "name": "brochure",
            "body_text": "Hello there",
            "header_format": "document",
            "header_handle": "4::YXBwbGljYXRpb24vcGRm:ARZ",
            # Typed before the kind was switched — must not leak into a media header.
            "header_text": "x" * 80,
        }
    )
    assert err is None
    assert parsed["payload"]["components"][0] == {
        "type": "HEADER",
        "format": "DOCUMENT",
        "example": {"header_handle": ["4::YXBwbGljYXRpb24vcGRm:ARZ"]},
    }
    assert parsed["payload"]["components"][1]["type"] == "BODY"
    # No route named: an alots-minted handle, submitted through the gateway.
    assert parsed["via_graph"] is False


def test_graph_minted_handle_routes_the_create_to_graph():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {
            "name": "brochure",
            "body_text": "Hello there",
            "header_format": "IMAGE",
            "header_handle": "4::aW1hZ2UvanBlZw==:ARZ",
            "header_handle_via": "graph",
        }
    )
    assert err is None
    assert parsed["via_graph"] is True


def test_parse_rejects_a_header_kind_meta_does_not_have():
    from apps.catalog.views import _parse_template_form

    parsed, err = _parse_template_form(
        {"name": "x", "body_text": "Hello there", "header_format": "AUDIO"}
    )
    assert parsed is None
    assert "text, an image, a video or a document" in err


def test_duplicate_detection_does_not_match_does_not_exist():
    from apps.catalog.views import _looks_like_duplicate

    assert _looks_like_duplicate("Template with name villa_nova2 already exists in language en")
    assert _looks_like_duplicate("A template with this name exists on this account")
    assert not _looks_like_duplicate(
        "Unsupported post request. Object with ID '2273706523459001' does not exist, "
        "cannot be loaded due to missing permissions, or does not support this operation"
    )
    assert not _looks_like_duplicate("Invalid WhatsApp configuration.")


def test_sample_sniffing_matches_the_claimed_kind():
    from apps.catalog.views import _sample_matches

    assert _sample_matches(b"\xff\xd8\xff\xe0" + b"\x00" * 12, "IMAGE")
    assert _sample_matches(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "IMAGE")
    assert _sample_matches(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "DOCUMENT")
    assert _sample_matches(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00", "VIDEO")
    assert not _sample_matches(b"<html><body>", "IMAGE")
    assert not _sample_matches(b"%PDF-1.7\n", "IMAGE")


def test_sync_error_quotes_the_gateway_sentence():
    from apps.catalog.tasks import UNREACHABLE_WABA_TEMPLATES, _sync_error_text

    assert _sync_error_text(AlotsError("Invalid WhatsApp configuration.")) == (
        "Invalid WhatsApp configuration."
    )
    assert _sync_error_text(
        AlotsError("GET /v23.0/123/message_templates -> HTTP 500: Invalid WhatsApp configuration.")
    ) == "Invalid WhatsApp configuration."
    assert _sync_error_text(AlotsError("GET /v23.0/123/message_templates -> HTTP 500")) == (
        "GET /v23.0/123/message_templates -> HTTP 500"
    )
    assert _sync_error_text(AlotsError("")) == UNREACHABLE_WABA_TEMPLATES
    assert len(_sync_error_text(AlotsError("x" * 900))) == 300
