"""Excel batches: sheet inspection, column mapping, row parsing — no database."""

import pytest

from apps.campaigns.bulk import (
    BulkError,
    column_letter,
    inspect_sheet,
    load_sheet,
    normalize_mapping,
    parse_mapped_rows,
)


class FakeTemplate:
    def __init__(self, variable_count):
        self.variable_count = variable_count


SHEET = (
    "Owner Name,Mobile,Community,Notes\n"
    "Sara Khan,0501234567,Damac Hills,\n"
    "Ali Hassan,+971 55 222 3333,Arabian Ranches,call later\n"
    ",,,\n"
    "Bad Row,not a phone,Villanova,\n"
    "Sara Again,971501234567,Damac Hills,dup\n"
    "No Community,971559999999,,\n"
).encode("utf-8")


def test_column_letters_follow_the_sheet():
    assert [column_letter(i) for i in (0, 1, 25, 26, 27, 51, 52)] == ["A", "B", "Z", "AA", "AB", "AZ", "BA"]


def test_inspect_names_columns_and_guesses_phone_and_name():
    result = inspect_sheet(SHEET, "owners.csv")
    assert result["has_header"] is True
    # Six lines under the header, one of them blank.
    assert result["rows"] == 5
    headers = [c["header"] for c in result["columns"]]
    assert headers == ["Owner Name", "Mobile", "Community", "Notes"]
    assert result["guesses"] == {"phone": 1, "name": 0}
    mobile = result["columns"][1]
    assert mobile["letter"] == "B"
    assert mobile["phone_like"] == 4
    assert mobile["samples"][0] == "0501234567"


def test_sheet_without_header_row_is_lettered():
    header, data, has_header = load_sheet(b"971501234567,Sara\n971502222222,Ali\n", "list.csv")
    assert has_header is False
    assert header == ["Column A", "Column B"]
    assert len(data) == 2


def test_mapping_needs_every_placeholder():
    with pytest.raises(BulkError) as raised:
        normalize_mapping({"phone": 1, "vars": {"1": {"column": 0}}}, FakeTemplate(2))
    assert "{{2}}" in str(raised.value)

    clean = normalize_mapping(
        {"phone": "1", "name": "", "vars": {"1": {"column": "0"}, "2": {"value": " Fozia "}}},
        FakeTemplate(2),
    )
    assert clean == {"phone": 1, "name": None, "vars": {"1": {"column": 0}, "2": {"value": "Fozia"}}}


def test_mapping_without_phone_is_refused():
    with pytest.raises(BulkError):
        normalize_mapping({"vars": {}}, FakeTemplate(0))


def test_rows_follow_the_mapping_and_report_what_was_dropped():
    recipients, stats, warnings = parse_mapped_rows(
        SHEET,
        "owners.csv",
        mapping={"phone": 1, "name": 0, "vars": {"1": {"column": 0}, "2": {"column": 2}}},
        template=FakeTemplate(2),
    )
    assert [r["phone"] for r in recipients] == ["971501234567", "971552223333"]
    assert recipients[0] == {
        "phone": "971501234567",
        "name": "Sara Khan",
        "variables": {"1": "Sara Khan", "2": "Damac Hills"},
    }
    assert stats == {"rows": 5, "valid": 2, "invalid_phone": 1, "duplicate": 1, "empty_value": 1}
    # Sheet row numbers, blank row included, so the agent can find them.
    assert warnings == [
        "Row 5: no valid phone number.",
        "Row 6: +971501234567 appears again — skipped.",
        "Row 7: {{2}} is empty.",
    ]


def test_fixed_value_fills_every_row_and_name_falls_back_to_first_variable():
    recipients, stats, _ = parse_mapped_rows(
        SHEET,
        "owners.csv",
        mapping={"phone": 1, "vars": {"1": {"column": 0}, "2": {"value": "Dubai"}}},
        template=FakeTemplate(2),
    )
    assert stats["valid"] == 3
    assert all(r["variables"]["2"] == "Dubai" for r in recipients)
    assert recipients[2]["name"] == "No Community"


def test_template_without_variables_only_needs_the_phone():
    recipients, stats, _ = parse_mapped_rows(
        SHEET, "owners.csv", mapping={"phone": 1}, template=FakeTemplate(0)
    )
    assert stats["valid"] == 3
    assert recipients[0]["variables"] == {}
    assert recipients[0]["name"] == ""


def test_unusable_sheet_says_why():
    with pytest.raises(BulkError) as raised:
        parse_mapped_rows(
            b"Name,Phone\nSara,abc\n", "x.csv", mapping={"phone": 1}, template=FakeTemplate(0)
        )
    assert "Row 2: no valid phone number." in str(raised.value)
