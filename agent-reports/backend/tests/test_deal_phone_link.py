from app.bitrix.deal_phone_link import phone_from_deal


def test_phone_from_deal_tenant_first():
    raw, phone = phone_from_deal(
        {
            "UF_CRM_1734263575786": "971524244416",
            "UF_CRM_1735377605713": "971506457466",
        }
    )
    assert raw == "971524244416"
    assert phone == "+971524244416"


def test_phone_from_deal_owner_fallback():
    _raw, phone = phone_from_deal(
        {
            "UF_CRM_1734263575786": "",
            "UF_CRM_1735377605713": "0506252693",
        }
    )
    assert phone == "+971506252693"
