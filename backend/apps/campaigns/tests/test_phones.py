from apps.campaigns.phones import (
    SpreadsheetFormatError,
    normalize_phone,
    normalize_spreadsheet_header,
    parse_campaign_spreadsheet,
    parse_recipients_csv,
    parse_recipients_text,
)


def test_normalize_uae_local():
    assert normalize_phone("0501234567") == "971501234567"
    assert normalize_phone("+971 50 123 4567") == "971501234567"
    assert normalize_phone("971501234567") == "971501234567"


def test_parse_text_lines():
    rows = parse_recipients_text("971501111111\n0502223333, Aftab\n# skip\nbad")
    phones = {r["phone"] for r in rows}
    assert "971501111111" in phones
    assert "971502223333" in phones
    aftab = next(r for r in rows if r["phone"] == "971502223333")
    assert "Aftab" in aftab["name"]


def test_parse_csv_header():
    raw = b"Name,Phone\nAli,971509998887\nSara,0501112233\n"
    rows = parse_recipients_csv(raw)
    assert len(rows) == 2
    assert rows[0]["phone"] == "971509998887"
    assert rows[1]["phone"] == "971501112233"


def test_spreadsheet_header_normalization():
    assert normalize_spreadsheet_header("{{ 1 }}") == "{{1}}"
    assert normalize_spreadsheet_header("number") == "Number"
    assert normalize_spreadsheet_header("{{2}}") == "{{2}}"


def test_campaign_spreadsheet_maps_columns_by_header_name():
    raw = (
        "{{1}},Number,{{4}},{{3}},{{2}}\n"
        "Mehwish,971522303941,1,Mudon Al Ranim 1,Sneha\n"
        "Anna,+971509998887,2,Mudon Al Ranim 1,Sneha\n"
    ).encode()
    rows, _warnings = parse_campaign_spreadsheet(raw, body_var_count=4)
    assert len(rows) == 2
    assert rows[0]["phone"] == "971522303941"
    assert rows[0]["name"] == "Mehwish"
    assert rows[0]["variables"] == {
        "1": "Mehwish",
        "2": "Sneha",
        "3": "Mudon Al Ranim 1",
        "4": "1",
    }


def test_campaign_spreadsheet_rejects_missing_number_column():
    raw = b"{{1}},{{2}}\nAli,Sneha\n"
    try:
        parse_campaign_spreadsheet(raw, body_var_count=2)
    except SpreadsheetFormatError as exc:
        assert "Number" in str(exc)
    else:
        raise AssertionError("expected SpreadsheetFormatError")


def test_campaign_spreadsheet_rejects_missing_template_column():
    raw = b"{{1}},Number,{{2}}\nAli,971501234567,Sneha\n"
    try:
        parse_campaign_spreadsheet(raw, body_var_count=3)
    except SpreadsheetFormatError as exc:
        assert "{{3}}" in str(exc)
    else:
        raise AssertionError("expected SpreadsheetFormatError")
