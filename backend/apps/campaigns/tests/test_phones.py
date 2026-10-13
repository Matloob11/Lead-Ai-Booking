from apps.campaigns.phones import normalize_phone, parse_recipients_csv, parse_recipients_text


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
