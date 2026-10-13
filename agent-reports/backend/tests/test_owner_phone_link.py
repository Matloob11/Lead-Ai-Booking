from app.bitrix.owner_phone_link import normalize_uae, phone_from_item


def test_normalize_uae():
    assert normalize_uae(506252693) == "+971506252693"
    assert normalize_uae("0506252693") == "+971506252693"
    assert normalize_uae("+971506252693") == "+971506252693"
    assert normalize_uae(0) == ""
    assert normalize_uae(None) == ""


def test_phone_from_item_prefers_primary():
    raw, phone = phone_from_item(
        {
            "ufCrm5_1768317611513": 506252693,
            "ufCrm5_1769416533028": 501111111,
        }
    )
    assert raw == 506252693
    assert phone == "+971506252693"


def test_phone_from_item_falls_back_to_secondary():
    raw, phone = phone_from_item(
        {
            "ufCrm5_1768317611513": 0,
            "ufCrm5_1769416533028": 501111111,
        }
    )
    assert phone == "+971501111111"
