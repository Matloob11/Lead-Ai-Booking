"""Renewals split: owner-only when the number matches, 300 cap, {{1}} like Leads."""

from django.test import SimpleTestCase

from apps.campaigns.renewals import RenewalSendError, build_renewal_messages, classify_deals


class FakeTemplate:
    def __init__(self, n):
        self.variable_count = n
        self.requires_header_media = False


class ClassifyTests(SimpleTestCase):
    def test_same_uae_number_is_owner_only(self):
        classified = classify_deals(
            [
                {
                    "id": 39079,
                    "tenant_phone": "0501111111",
                    "tenant_name": "Sara Tenant",
                    "owner_phone": "+971 50 111 1111",
                    "owner_name": "Ali Owner",
                }
            ]
        )
        self.assertEqual(classified["tenant_messages"], 0)
        self.assertEqual(classified["owner_messages"], 1)
        self.assertEqual(classified["owners"][0]["phone"], "971501111111")
        self.assertEqual(classified["rows"][0]["tenant_state"], "same")
        self.assertEqual(classified["rows"][0]["owner_state"], "send")
        self.assertTrue(any("Same number" in row["reason"] for row in classified["skipped"]))

    def test_different_numbers_keep_both_sides(self):
        classified = classify_deals(
            [
                {
                    "id": 12,
                    "tenant_phone": "971501111111",
                    "tenant_name": "Sara",
                    "owner_phone": "971502222222",
                    "owner_name": "Ali",
                }
            ]
        )
        self.assertEqual(classified["tenant_messages"], 1)
        self.assertEqual(classified["owner_messages"], 1)

    def test_missing_side_is_skipped(self):
        classified = classify_deals(
            [{"id": 3, "tenant_phone": "971501234567", "tenant_name": "Sara", "owner_phone": "", "owner_name": ""}]
        )
        self.assertEqual(classified["tenant_messages"], 1)
        self.assertEqual(classified["owner_messages"], 0)
        self.assertEqual(classified["rows"][0]["owner_state"], "missing")

    def test_duplicate_phone_inside_one_side(self):
        classified = classify_deals(
            [
                {"id": 1, "tenant_phone": "971501111111", "tenant_name": "A", "owner_phone": "", "owner_name": ""},
                {"id": 2, "tenant_phone": "971501111111", "tenant_name": "B", "owner_phone": "", "owner_name": ""},
            ]
        )
        self.assertEqual(classified["tenant_messages"], 1)
        self.assertEqual(classified["rows"][1]["tenant_state"], "duplicate")

    def test_deal_title_is_not_a_person_name(self):
        classified = classify_deals(
            [
                {
                    "id": 9,
                    "tenant_phone": "",
                    "tenant_name": "",
                    "owner_phone": "971503333333",
                    "owner_name": "Deal #39079",
                }
            ]
        )
        self.assertEqual(classified["owners"][0]["name"], "")
        self.assertEqual(classified["rows"][0]["owner_name"], "Customer")


class BuildTests(SimpleTestCase):
    def test_blank_placeholder_uses_each_name(self):
        built = build_renewal_messages(
            deals=[
                {
                    "id": 11,
                    "tenant_phone": "971501111111",
                    "tenant_name": "Sara",
                    "owner_phone": "971502222222",
                    "owner_name": "Ali",
                }
            ],
            tenant_template=FakeTemplate(1),
            owner_template=FakeTemplate(1),
            tenant_extra={},
            owner_extra={},
        )
        self.assertEqual(built["tenant"][0]["variables"]["1"], "Sara")
        self.assertEqual(built["tenant"][0]["crm_deal_id"], 11)
        self.assertEqual(built["tenant"][0]["crm_role"], "tenant")
        self.assertNotIn("crm_lead_id", built["tenant"][0])
        self.assertEqual(built["owner"][0]["variables"]["1"], "Ali")
        self.assertEqual(built["owner"][0]["crm_role"], "owner")

    def test_typed_placeholder_goes_to_everyone(self):
        built = build_renewal_messages(
            deals=[
                {
                    "id": 11,
                    "tenant_phone": "971501111111",
                    "tenant_name": "Sara",
                    "owner_phone": "971502222222",
                    "owner_name": "Ali",
                }
            ],
            tenant_template=FakeTemplate(1),
            owner_template=FakeTemplate(1),
            tenant_extra={"1": "Team"},
            owner_extra={"1": "Landlord"},
        )
        self.assertEqual(built["tenant"][0]["variables"]["1"], "Team")
        self.assertEqual(built["owner"][0]["variables"]["1"], "Landlord")

    def test_generic_owner_name_becomes_customer(self):
        built = build_renewal_messages(
            deals=[
                {
                    "id": 4,
                    "tenant_phone": "",
                    "tenant_name": "",
                    "owner_phone": "971509998887",
                    "owner_name": "Untitled",
                }
            ],
            tenant_template=None,
            owner_template=FakeTemplate(1),
            tenant_extra={},
            owner_extra={},
        )
        self.assertEqual(built["tenant"], [])
        self.assertEqual(built["owner"][0]["variables"]["1"], "Customer")

    def test_over_cap_asks_for_more_numbers(self):
        deals = [
            {
                "id": index,
                "tenant_phone": f"9715{index:08d}",
                "tenant_name": "T",
                "owner_phone": "",
                "owner_name": "",
            }
            for index in range(1, 302)
        ]
        with self.assertRaises(RenewalSendError) as caught:
            build_renewal_messages(
                deals=deals,
                tenant_template=FakeTemplate(0),
                owner_template=None,
                tenant_extra={},
                owner_extra={},
            )
        self.assertIn("More numbers required", str(caught.exception))
        self.assertIn("301", str(caught.exception))

    def test_three_hundred_is_allowed(self):
        deals = [
            {
                "id": index,
                "tenant_phone": f"9715{index:08d}",
                "tenant_name": "T",
                "owner_phone": "",
                "owner_name": "",
            }
            for index in range(1, 301)
        ]
        built = build_renewal_messages(
            deals=deals,
            tenant_template=FakeTemplate(0),
            owner_template=None,
            tenant_extra={},
            owner_extra={},
        )
        self.assertEqual(built["total"], 300)

    def test_none_usable_raises(self):
        with self.assertRaises(RenewalSendError):
            build_renewal_messages(
                deals=[{"id": 1, "tenant_phone": "", "owner_phone": "", "tenant_name": "", "owner_name": ""}],
                tenant_template=None,
                owner_template=None,
                tenant_extra={},
                owner_extra={},
            )
