"""Leads-list bulk send: HMAC, {{1}}=name, CRM lead id never becomes a Meta var."""

from django.test import SimpleTestCase, override_settings

from apps.campaigns.crm_leads import (
    CrmLeadSendError,
    build_recipients,
    campaign_playbook,
    crm_entity,
    lead_display_name,
    mark_lead_ai,
    verify_signed_request,
)
from apps.campaigns.services import _lead_timeline_comment, _meta_body_vars


class FakeTemplate:
    def __init__(self, n):
        self.variable_count = n


class LeadDisplayNameTests(SimpleTestCase):
    def test_untitled_phone_and_missed_call_become_there(self):
        self.assertEqual(lead_display_name({"name": "Untitled"}), "there")
        self.assertEqual(lead_display_name({"title": "Unentitled"}), "there")
        self.assertEqual(lead_display_name({}), "")
        self.assertEqual(lead_display_name({"name": "971501234567"}), "there")
        self.assertEqual(lead_display_name({"name": "+971 50 123 4567"}), "there")
        self.assertEqual(lead_display_name({"name": "Missed Call from 0501234567"}), "there")
        self.assertEqual(lead_display_name({"title": "Missed Call | 971501112233"}), "there")

    def test_plain_name_stays_whole(self):
        self.assertEqual(lead_display_name({"name": "Sara Khan"}), "Sara Khan")

    def test_name_field_is_the_first_word(self):
        self.assertEqual(
            lead_display_name({"first_name": "Ali", "last_name": "Hassan"}),
            "Ali",
        )
        self.assertEqual(
            lead_display_name({
                "first_name": "Mohammed Ali",
                "name": "Bayut WhatsApp | Mohammed Ali",
                "title": "Bayut WhatsApp | Mohammed Ali",
            }),
            "Ali",
        )

    def test_portal_title_uses_the_part_after_the_last_pipe(self):
        self.assertEqual(
            lead_display_name({
                "name": "Bayut WhatsApp | Md Sumon",
                "title": "Bayut WhatsApp | Md Sumon",
            }),
            "Sumon",
        )
        self.assertEqual(
            lead_display_name({"title": "Portal | Bayut WhatsApp | Aisha Noor"}),
            "Aisha Noor",
        )

    def test_honorific_is_skipped_when_a_name_follows(self):
        self.assertEqual(lead_display_name({"first_name": "Md Sumon"}), "Sumon")
        self.assertEqual(lead_display_name({"first_name": "Mr. Ali Hassan"}), "Ali")
        self.assertEqual(lead_display_name({"first_name": "Engr. Ahmed"}), "Ahmed")
        self.assertEqual(lead_display_name({"name": "Dr. Aisha Noor"}), "Aisha")
        self.assertEqual(lead_display_name({"first_name": "Mohammed"}), "Mohammed")
        self.assertEqual(lead_display_name({"first_name": "Miss"}), "Miss")

    def test_phone_in_the_name_field_falls_through_to_the_title(self):
        self.assertEqual(
            lead_display_name({
                "first_name": "971501234567",
                "title": "Property Finder | Sara Khan",
            }),
            "Sara Khan",
        )

    def test_deal_contact_name_is_kept_when_it_is_not_the_title(self):
        self.assertEqual(
            lead_display_name({
                "name": "Ali Hassan",
                "title": "Apartment in Marina",
            }),
            "Ali Hassan",
        )


class BuildRecipientsTests(SimpleTestCase):
    def test_fills_name_as_one_and_keeps_extra(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(2),
            leads=[{"id": 11, "phone": "+971 50 123 4567", "name": "Sara"}],
            extra_body={"2": "Dubai", "crm_lead_id": "99"},
        )
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["crm_lead_id"], 11)
        self.assertEqual(rows[0]["phone"], "971501234567")
        self.assertEqual(rows[0]["variables"]["1"], "Sara")
        self.assertEqual(rows[0]["variables"]["2"], "Dubai")
        self.assertNotIn("crm_lead_id", rows[0]["variables"])

    def test_untitled_becomes_there(self):
        rows, _skipped = build_recipients(
            template=FakeTemplate(1),
            leads=[{"id": 4, "phone": "971509998887", "name": "Untitled"}],
            extra_body={},
        )
        self.assertEqual(rows[0]["variables"]["1"], "there")
        self.assertEqual(rows[0]["name"], "there")

    def test_portal_title_is_the_greeting_on_the_recipient(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(1),
            leads=[{
                "id": 17,
                "phone": "971509998887",
                "name": "Bayut WhatsApp | Md Sumon",
                "title": "Bayut WhatsApp | Md Sumon",
            }],
            extra_body={},
        )
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["name"], "Sumon")
        self.assertEqual(rows[0]["variables"]["1"], "Sumon")

    def test_mapped_name_uses_the_first_word_not_the_portal_title(self):
        rows, _skipped = build_recipients(
            template=FakeTemplate(1),
            leads=[{
                "id": 11,
                "phone": "971501111111",
                "name": "Bayut WhatsApp | Md Sumon",
                "title": "Bayut WhatsApp | Md Sumon",
                "first_name": "Md Sumon",
                "details": {"name": "Bayut WhatsApp | Md Sumon"},
            }],
            extra_body={},
            field_map={"1": "name"},
        )
        self.assertEqual(rows[0]["name"], "Sumon")
        self.assertEqual(rows[0]["variables"]["1"], "Sumon")

    def test_skips_no_phone_and_duplicates(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(0),
            leads=[
                {"id": 1, "phone": "", "name": "A"},
                {"id": 2, "phone": "971501111111", "name": "B"},
                {"id": 3, "phone": "971501111111", "name": "C"},
            ],
            extra_body={},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(skipped), 2)

    def test_missing_extra_var_raises(self):
        with self.assertRaises(CrmLeadSendError):
            build_recipients(
                template=FakeTemplate(3),
                leads=[{"id": 1, "phone": "971501234567", "name": "Sara"}],
                extra_body={"2": "only two"},
            )

    def test_none_usable_raises(self):
        with self.assertRaises(CrmLeadSendError):
            build_recipients(template=FakeTemplate(0), leads=[{"id": 1}], extra_body={})

    def test_owner_data_keeps_card_id_not_lead_id(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(1),
            leads=[{"id": 1030633, "phone": "971504000866", "name": "WhatsApp"}],
            extra_body={},
            entity="owner_data",
        )
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["owner_data_id"], 1030633)
        self.assertNotIn("crm_lead_id", rows[0])
        self.assertEqual(rows[0]["variables"]["1"], "WhatsApp")


    def test_deal_links_deal_id_not_lead_id(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(1),
            leads=[{"id": 501, "phone": "+971 50 111 2222", "name": "Ali Hassan"}],
            extra_body={},
            entity="deal",
        )
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["crm_deal_id"], 501)
        self.assertNotIn("crm_lead_id", rows[0])
        self.assertNotIn("owner_data_id", rows[0])
        self.assertEqual(rows[0]["variables"]["1"], "Ali Hassan")

    def test_contact_links_no_crm_id(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(0),
            leads=[{"id": 77, "phone": "971509998888", "first_name": "Sara", "last_name": "Khan"}],
            extra_body={},
            entity="contact",
        )
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["name"], "Sara")
        self.assertNotIn("crm_lead_id", rows[0])
        self.assertNotIn("crm_deal_id", rows[0])
        self.assertNotIn("owner_data_id", rows[0])

    def test_entity_parsing(self):
        self.assertEqual(crm_entity("deal"), "deal")
        self.assertEqual(crm_entity("contact"), "contact")
        self.assertEqual(crm_entity("DYNAMIC_1042"), "owner_data")
        self.assertEqual(crm_entity("something-else"), "lead")

    def test_field_map_is_per_lead_and_blank_is_question_mark(self):
        rows, skipped = build_recipients(
            template=FakeTemplate(2),
            leads=[
                {
                    "id": 11,
                    "phone": "971501111111",
                    "name": "Sara",
                    "details": {"name": "Sara", "community": "International City"},
                },
                {
                    "id": 12,
                    "phone": "971502222222",
                    "name": "Ali",
                    "details": {"name": "Ali", "community": ""},
                },
            ],
            extra_body={"1": "ignored", "2": "also ignored"},
            field_map={"1": "name", "2": "community"},
        )
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["variables"], {"1": "Sara", "2": "International City"})
        self.assertEqual(rows[1]["variables"], {"1": "Ali", "2": "?"})

    def test_typed_value_overrides_the_dropdown(self):
        rows, _skipped = build_recipients(
            template=FakeTemplate(1),
            leads=[{"id": 11, "phone": "971501111111", "name": "Sara", "details": {"name": "Sara"}}],
            extra_body={"1": "Hello"},
            field_map={"2": "community"},
        )
        self.assertEqual(rows[0]["variables"]["1"], "Hello")

    def test_entity_noun_in_errors(self):
        with self.assertRaises(CrmLeadSendError) as ctx:
            build_recipients(
                template=FakeTemplate(0),
                leads=[{"id": 1, "phone": "12"}],
                extra_body={},
                entity="contact",
            )
        self.assertIn("contacts", str(ctx.exception))


class MetaVarsTests(SimpleTestCase):
    def test_drops_non_digit_keys(self):
        out = _meta_body_vars({"1": "Sara", "crm_lead_id": "88", "x": "no"})
        self.assertEqual(out, {"1": "Sara"})


class HmacTests(SimpleTestCase):
    @override_settings(CRM_LEAD_WA_SECRET="unit-test-secret")
    def test_accepts_matching_signature(self):
        import hashlib
        import hmac
        import time

        ts = str(int(time.time()))
        body = b'{"bitrix_user_id":"12"}'
        sig = hmac.new(
            b"unit-test-secret",
            f"{ts}.".encode("ascii") + body,
            hashlib.sha256,
        ).hexdigest()
        verify_signed_request(timestamp=ts, signature=sig, body=body)

    @override_settings(CRM_LEAD_WA_SECRET="unit-test-secret")
    def test_rejects_bad_signature(self):
        import time

        with self.assertRaises(CrmLeadSendError):
            verify_signed_request(
                timestamp=str(int(time.time())),
                signature="deadbeef",
                body=b"{}",
            )

    @override_settings(CRM_LEAD_WA_SECRET="")
    def test_empty_secret_refuses(self):
        with self.assertRaises(CrmLeadSendError):
            verify_signed_request(timestamp="1", signature="ab", body=b"{}")


class PlaybookTests(SimpleTestCase):
    def test_only_the_two_scripts(self):
        self.assertEqual(campaign_playbook("ic_shops"), "ic_shops")
        self.assertEqual(campaign_playbook(" General "), "general")
        self.assertEqual(campaign_playbook("IC_SHOPS"), "ic_shops")
        self.assertEqual(campaign_playbook("shops"), "general")
        self.assertEqual(campaign_playbook(None), "general")

    def test_forwards_the_script_when_the_lane_accepts_it(self):
        seen = {}

        def fake(campaign, playbook="general"):
            seen["playbook"] = playbook
            return campaign

        with self._patch(fake):
            self.assertEqual(mark_lead_ai("camp", "ic_shops"), "ic_shops")
        self.assertEqual(seen["playbook"], "ic_shops")

    def test_older_lane_still_marks_the_campaign(self):
        seen = {}

        def fake(campaign):
            seen["campaign"] = campaign
            return campaign

        with self._patch(fake):
            self.assertEqual(mark_lead_ai("camp", "nope"), "general")
        self.assertEqual(seen["campaign"], "camp")

    def _patch(self, fake):
        from unittest.mock import patch

        return patch("apps.leadai.lane.mark_campaign", fake)


class TimelineCommentTests(SimpleTestCase):
    def test_fills_body_placeholders(self):
        class Number:
            phone_number = "971500000001"

        class Template:
            name = "hello"
            body_text = "Hi {{1}}, see you in {{2}}."

        class Campaign:
            name = "CRM Leads · hello"
            template = Template()
            number = Number()

        class Recipient:
            phone = "971509998887"

        text = _lead_timeline_comment(Campaign(), Recipient(), {"1": "Sara", "2": "Dubai"})
        self.assertIn("Hi Sara, see you in Dubai.", text)
        self.assertIn("Template: hello", text)
        self.assertIn("+971509998887", text)
