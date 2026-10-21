"""Batch 2e, board T95 (spec §5, brief Part 15): a studio or one-bedroom chat's own Bitrix lead fields, through the Lead
fields tool (C6) and never a REST update, behind RES_FIELDS_LIVE (assistant/crm_fields.residential_writes; C38's field
map, C39's new fields).

- A. what a turn writes, from the chat's facts and the track and unit code decided (spec §5's table), in the customers'
  own words: Rent/Sale, Client Type, Bedrooms, Purpose and Budget only while the lead's are empty; C39's own fields
  when they change; the e-mail; nothing on any other track, nor with the flag off;
- B. the body: every code and id on the tool's allow-list (ALLOWED, held to the PHP itself), text stays text, the
  e-mail is a key of its own, and crm_fields.refusal reads a body as the tool does;
- C. the write (tasks.write_crm_fields): the lead's own value stays, and when it says otherwise than the customer its
  timeline says so, once; a Client Type never goes over a Rent/Sale (a7_rent_sale.php); an e-mail only to a lead with
  none;
- D. a turn end to end (engine._apply): the rows beside the turn's Bot Status, never twice, none for a shop customer,
  and a broker's Purpose Broker never lost to a Purpose of ours;
- E. the eval mirrors it (leadai_eval: run.crm, crm_ok, the shops-crm-* scenarios), and fails without the guards.

Each test fails without the rule it proves (the scratchpad's crm2e/guards_off.py). The fakes are test_assistant's and
test_crm_writes'; the shops chat is test_shops_playbook's (lead 555, Monday 12 October 2026, 14:00 Dubai).
"""

import re
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.leadai.assistant import crm_fields, tracks
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiCrmField, LeadAiTurn
from apps.leadai.tests.test_crm_writes import IDLE_LEAD, CrmWritesBase, FakeBitrix
from apps.leadai.tests.test_eval_command import MODEL, RIGHT
from apps.leadai.tests.test_residential_turns import res_answer
from apps.leadai.tests.test_shops_playbook import shop_answer
from apps.leadai.tests.test_who_the_customer_is import NotAShopBase

F = crm_fields
EMPTY_ONLY = {"only_if_empty": True}
RENT, SALE = tracks.RENT, tracks.SALE
PHP = Path(__file__).resolve().parents[4] / "ops" / "bitrix-aws" / "a7_leadai_fields.php"

# A studio seeker who told us everything, as the model records it (RES_SCHEMA's keys; 2d's shops schema has some).
RENTER = {
    "customer_name": "Ahmed",
    "for_client": False,
    "move_in": "next month",
    "occupancy": "family",
    "balcony": "yes",
    "clusters": ["Spain", "France"],
    "full_name": "ahmed khan",
    "email": "Ahmed.Khan@Gmail.com",
    "budget_aed": 32000.0,
    "budget_basis": "per_year",
}
# A one-bedroom buyer through Q1-Q5 (brief Part 5B): for myself, a mortgage, in three months, a tenanted unit, investment.
BUYER = {
    "for_client": False,
    "payment": "mortgage",
    "buy_timeline": "within 3 months",
    "occupancy_status": "tenanted",
    "purpose": "investment",
    "balcony": "either",
    "budget_aed": 500000.0,
    "budget_basis": "total",
}


def fields_of(writes) -> dict:
    return {field: value for field, value, _ in writes}


def rows_for(writes, lead_id=555) -> list:
    """The rows crm_fields.queue would make of these writes (unsaved), as body_for reads them."""
    return [LeadAiCrmField(lead_id=lead_id, field=field, value=str(value)[:255], payload=payload or {}) for field, value, payload in writes]


# A. What a turn writes --------------------------------------------------------------------------------------------------


class ResidentialWritesTests(SimpleTestCase):
    def test_a_studio_to_rent_spec_table(self):
        writes = F.residential_writes(RENTER, RENT, tracks.STUDIO)
        self.assertEqual(
            writes,
            [
                (F.FIELD_RENT_SALE, 2443, EMPTY_ONLY),
                (F.FIELD_CLIENT_TYPE, 1220, EMPTY_ONLY),
                (F.FIELD_BEDROOMS, 26, EMPTY_ONLY),
                (F.FIELD_PURPOSE, 805, EMPTY_ONLY),
                (F.FIELD_BUDGET, 32000, EMPTY_ONLY),
                (F.FIELD_CLUSTERS, "Spain, France", {}),
                (F.FIELD_BALCONY, 2501, {}),
                (F.FIELD_TIMELINE, "next month", {}),
                (F.FIELD_FULL_NAME, "Ahmed Khan", {}),
                (F.FIELD_OCCUPANCY, 2510, {}),
                (F.EMAIL, "ahmed.khan@gmail.com", {}),
            ],
        )

    def test_a_one_bedroom_to_buy_spec_table(self):
        got = fields_of(F.residential_writes(BUYER, SALE, tracks.ONE_BR))
        self.assertEqual(
            got,
            {
                F.FIELD_RENT_SALE: 2444, F.FIELD_CLIENT_TYPE: 972, F.FIELD_BEDROOMS: 27, F.FIELD_PURPOSE: 804, F.FIELD_BUDGET: 500000,
                F.FIELD_BALCONY: 2503, F.FIELD_TIMELINE: "within 3 months", F.FIELD_VACANT_RENTED: 2505, F.FIELD_PAYMENT: 2508,
            },
        )
        # The buyer's "my family" is no field of a sale (the brief's sales fields): Occupancy is the rent flow's.
        self.assertNotIn(F.FIELD_OCCUPANCY, fields_of(F.residential_writes({**BUYER, "occupancy": "family"}, SALE, tracks.ONE_BR)))

    def test_only_the_rent_and_sale_tracks_write_them(self):
        # A shop, a bigger home or another area, a chat whose need nobody knows yet, and a buyer while the sale flow is not
        # live (tracks.SALE_LIVE: other) write none: 2d's fields and Bot Status only.
        for track in (tracks.SHOP, tracks.OTHER, tracks.UNKNOWN, "anything"):
            with self.subTest(track=track):
                self.assertEqual(F.residential_writes(RENTER, track, tracks.STUDIO), [])
        # "We are a family of five, looking for a 2 bedroom flat to rent": the other track, and never Bedrooms 2 B/R (28),
        # which the tool refuses, and the whole batch with it.
        decision = tracks.decide(words=["We are a family of five, looking for a 2 bedroom flat to rent"])
        self.assertEqual((decision.track, decision.unit), (tracks.OTHER, tracks.TWO_PLUS))
        self.assertEqual(F.residential_writes({"for_client": False}, decision.track, decision.unit), [])
        self.assertNotIn(tracks.TWO_PLUS, F.BEDROOMS_IDS)

    def test_nothing_while_the_flag_is_off(self):
        with patch.object(F, "RES_FIELDS_LIVE", False):
            self.assertEqual(F.residential_writes(RENTER, RENT, tracks.STUDIO), [])
            self.assertEqual(F.residential_writes(BUYER, SALE, tracks.ONE_BR), [])

    def test_purpose_for_myself_on_rent_only(self):
        # "It's for myself" (rent): I want for myself, while the lead's Purpose is empty.
        self.assertEqual(F.purpose_of({"for_client": False}, RENT), F.PURPOSE_MYSELF)
        self.assertIsNone(F.purpose_of({}, RENT))  # not said yet
        # "I am looking for my client" (an agent): Broker is theirs (turn_writes), never a Purpose of ours.
        self.assertIsNone(F.purpose_of({"for_client": True}, RENT))
        self.assertIsNone(F.purpose_of({"for_client": True, "purpose": "investment"}, SALE))

    def test_a_buyers_for_myself_waits_for_their_use(self):
        # Q1 "for myself" comes before Q5 "investment or own use?": 805 written then would keep 804 out for good (only while
        # empty). A buyer's Purpose comes from their purpose alone.
        self.assertIsNone(F.purpose_of({"for_client": False}, SALE))
        self.assertNotIn(F.FIELD_PURPOSE, fields_of(F.residential_writes({"for_client": False}, SALE, tracks.STUDIO)))
        self.assertEqual(F.purpose_of({"for_client": False, "purpose": "investment"}, SALE), F.PURPOSE_INVESTOR)
        self.assertEqual(F.purpose_of({"purpose": "personal"}, SALE), F.PURPOSE_MYSELF)

    def test_a_field_the_turn_writes_already_is_left_to_it(self):
        # A broker's turn: turn_writes gives Purpose Broker (2467); a Purpose of ours in the same batch would replace it.
        broker = [(F.FIELD_PURPOSE, F.PURPOSE_BROKER, {}), (F.FIELD_BOT_STATUS, F.STATUS_BROKER, {})]
        writes = F.residential_writes({"for_client": False}, RENT, tracks.STUDIO, besides=broker)
        self.assertNotIn(F.FIELD_PURPOSE, fields_of(writes))
        self.assertIn(F.FIELD_RENT_SALE, fields_of(writes))

    def test_budget(self):
        rent = lambda **facts: F.budget_of(facts, RENT)  # noqa: E731
        self.assertEqual(rent(budget_aed=32000.0, budget_basis="per_year"), 32000)
        # "My budget is 2500 per month": the lead's Budget is yearly, as every rent here is.
        self.assertEqual(rent(budget_aed=2500.0, budget_basis="per_month"), 30000)
        self.assertEqual(rent(budget_aed=30000.0), 30000)
        self.assertIsNone(rent(budget_aed=2500.0))  # a monthly figure said with no basis: not guessed
        self.assertIsNone(rent(budget_aed=2500.0, budget_basis="per_year"))  # no yearly rent in International City
        self.assertIsNone(rent(budget_aed=330000.0, budget_basis="total"))
        self.assertEqual(F.budget_of({"budget_aed": 340000.0, "budget_basis": "total"}, SALE), 340000)
        self.assertEqual(F.budget_of({"budget_aed": 340000.0}, SALE), 340000)
        self.assertIsNone(F.budget_of({"budget_aed": 3000.0, "budget_basis": "per_month"}, SALE))
        for odd in (True, "32000", None, 500.0, 2e9):
            with self.subTest(odd=odd):
                self.assertIsNone(F.budget_of({"budget_aed": odd}, SALE))

    def test_occupancy_and_never_bachelor(self):
        # "I am bachelor, working in Dubai": 2d's shops schema could record it; the brief screens nobody (rule 7).
        occupancy = lambda value: fields_of(F.residential_writes({"occupancy": value}, RENT, tracks.STUDIO)).get(F.FIELD_OCCUPANCY)  # noqa: E731
        self.assertIsNone(occupancy("bachelor"))
        self.assertEqual(
            [occupancy(value) for value in ("myself", "family", "company_staff", "Company staff", "company", "sharing")],
            [2509, 2510, 2511, 2511, 2511, 2512],
        )

    def test_payment_and_vacant_or_rented_are_a_buyers(self):
        # A renter's "I will pay cash" (the cheques' question) and a vacant flat: no buyer's field on a rental lead.
        got = fields_of(F.residential_writes({"payment": "cash", "occupancy_status": "vacant"}, RENT, tracks.STUDIO))
        self.assertNotIn(F.FIELD_PAYMENT, got)
        self.assertNotIn(F.FIELD_VACANT_RENTED, got)
        got = fields_of(F.residential_writes({"payment": "cash", "occupancy_status": "either"}, SALE, tracks.STUDIO))
        self.assertEqual((got[F.FIELD_PAYMENT], got[F.FIELD_VACANT_RENTED]), (2507, 2506))
        self.assertNotIn(F.FIELD_PAYMENT, fields_of(F.residential_writes({"payment": "cheques"}, SALE, tracks.STUDIO)))

    def test_the_timeline_is_the_move_in_on_rent_and_the_buying_timeline_on_sale(self):
        facts = {"move_in": "in 2 months", "buy_timeline": "next year"}
        self.assertEqual(fields_of(F.residential_writes(facts, RENT, tracks.STUDIO))[F.FIELD_TIMELINE], "in 2 months")
        self.assertEqual(fields_of(F.residential_writes(facts, SALE, tracks.STUDIO))[F.FIELD_TIMELINE], "next year")
        # "I plan to buy in 2027": a timeline of digits is still a timeline (body_for keeps it text: B).
        self.assertEqual(fields_of(F.residential_writes({"buy_timeline": "2027"}, SALE, tracks.STUDIO))[F.FIELD_TIMELINE], "2027")
        self.assertEqual(F.timeline_text({"move_in": "<b>asap</b>"}, RENT), "‹b›asap‹/b›")  # markup is no markup

    def test_clusters(self):
        text = F.clusters_text
        self.assertEqual(text({"clusters": ["Spain", "spain cluster", "Dubai Marina"]}), "Spain")
        self.assertEqual(text({"clusters": "England, France"}), "England, France")
        self.assertEqual(text({"clusters": [], "cluster_flexible": True}), "Any (flexible)")
        self.assertEqual(text({"clusters": ["Morocco"], "cluster_flexible": True}), "Morocco (flexible)")
        self.assertEqual(text({"community": "Spain Cluster"}), "Spain")
        # "I need room / 1bhk Englund x cluster" (launch chat 49): their own words, read by code, when the facts name no cluster.
        self.assertEqual(text({"community": "England"}, "I need room\n1bhk Englund x cluster"), "England")
        # The CRM review of batch 2e: the model's facts.clusters is the source; words fill in only when it names none, and
        # never our office's cluster nor one they turn down.
        self.assertEqual(text({"clusters": ["Persia"]}, "actually Persia cluster is better"), "Persia")
        self.assertEqual(text({"clusters": ["Spain"]}, "Ok see you at the Russia cluster office at 5"), "Spain")
        self.assertEqual(text({}, "Ok see you at the Russia cluster office at 5"), "")
        self.assertEqual(text({}, "I dont want China cluster"), "")
        self.assertEqual(text({}, "Not Spain cluster, I want England cluster"), "England")
        # "I am from China, I need a studio": a nationality is never a cluster, in their words or the model's community.
        self.assertEqual(text({"community": "China"}, "I am from China, I need a studio"), "")
        self.assertEqual(text({"community": "International City"}), "")
        self.assertEqual(text({}), "")

    def test_full_name(self):
        name = F.full_name
        self.assertEqual(name("ahmed khan"), "Ahmed Khan")
        self.assertEqual(name("Mohammed Al-Hashimi"), "Mohammed Al-Hashimi")
        self.assertEqual(name("Md Sumon"), "Md Sumon")
        self.assertEqual(name("محمد علي"), "محمد علي")
        self.assertEqual(name("Rahul Kumar Sharma"), "Rahul Kumar Sharma")
        # A first name alone is no full name (brief Part 5, step 5: first and last name), nor anything else here.
        for value in (
            "Ahmed", "Ahmed K", "Ahmed Khan 0501234567", "Ahmed <b>Khan</b>", "Bayut WhatsApp", "Sales Manager", "ahmed@x.com khan",
            "A" * 41 + " " + "B" * 40, "", None,
        ):
            with self.subTest(value=value):
                self.assertEqual(name(value), "")

    def test_email(self):
        self.assertEqual(F.email_of("Ahmed.Khan@Gmail.com"), "ahmed.khan@gmail.com")
        self.assertEqual(F.email_of(" ahmed_k+flat@mail.example.ae "), "ahmed_k+flat@mail.example.ae")
        # What customers type that the tool's FILTER_VALIDATE_EMAIL refuses, and the whole batch with it.
        for value in (
            "ahmed..khan@gmail.com", "ahmed@gmail..com", ".ahmed@gmail.com", "ahmed.@gmail.com", "ahmed khan@gmail.com",
            "ahmed@gmail", "ahmed@gmail,com", "أحمد@example.com", "ahmed@-gmail.com", "ahmed@gmail.c", "", None,
        ):
            with self.subTest(value=value):
                self.assertEqual(F.email_of(value), "")


# B. The body ------------------------------------------------------------------------------------------------------------


class BodyTests(SimpleTestCase):
    def test_every_value_a_turn_can_write_is_on_c39s_allow_list(self):
        # Every unit, every enum value, both tracks: the body the tool gets is one it takes (no 400 refusing Bot Status).
        enums = {
            "balcony": [*F.BALCONY_IDS, True, False], "occupancy": list(F.OCCUPANCY_IDS), "occupancy_status": list(F.VACANT_RENTED_IDS),
            "payment": list(F.PAYMENT_IDS), "purpose": list(F.PURPOSE_IDS),
        }
        for track in (RENT, SALE):
            for unit in (tracks.STUDIO, tracks.ONE_BR, ""):
                for key, values in enums.items():
                    for value in values:
                        writes = F.residential_writes({**RENTER, **BUYER, key: value}, track, unit)
                        body = F.body_for(rows_for(writes))
                        with self.subTest(track=track, unit=unit, key=key, value=value):
                            self.assertEqual(F.refusal(body), "")
                            for code, written in body["fields"].items():
                                rule = F.ALLOWED[code]
                                self.assertTrue(rule == F.TEXT and isinstance(written, str) or rule == F.NUMBER or written in rule)

    def test_the_c39_proofs_body(self):
        # Board C39's proof (lead 79752): the clusters, balcony, full name, Rent/Sale, Bedrooms, Client Type and the e-mail.
        writes = F.residential_writes(
            {"clusters": ["England", "France"], "balcony": "either", "full_name": "Ada Test", "email": "c39-proof@example.com"},
            RENT, tracks.STUDIO,
        )
        self.assertEqual(
            F.body_for(rows_for(writes)),
            {
                "lead_id": 555,
                "fields": {
                    F.FIELD_RENT_SALE: 2443, F.FIELD_CLIENT_TYPE: 1220, F.FIELD_BEDROOMS: 26, F.FIELD_CLUSTERS: "England, France",
                    F.FIELD_BALCONY: 2503, F.FIELD_FULL_NAME: "Ada Test",
                },
                "email": "c39-proof@example.com",
                "only_if_empty": [F.FIELD_RENT_SALE, F.FIELD_CLIENT_TYPE, F.FIELD_BEDROOMS],
            },
        )

    def test_text_stays_text(self):
        # "I plan to buy in 2027": the tool refuses a number in a text field ("Bad field value"), and the whole batch.
        rows = rows_for([(F.FIELD_TIMELINE, "2027", {}), (F.FIELD_ACTIVITY, "24", {}), (F.FIELD_BUDGET, 340000, {}), (F.FIELD_RENT_SALE, 2444, {})])
        body = F.body_for(rows)
        self.assertEqual(body["fields"], {F.FIELD_TIMELINE: "2027", F.FIELD_ACTIVITY: "24", F.FIELD_BUDGET: 340000, F.FIELD_RENT_SALE: 2444})
        self.assertEqual(F.refusal(body), "")
        self.assertEqual(F.TEXT_FIELDS, {F.FIELD_ACTIVITY, F.FIELD_CLUSTERS, F.FIELD_TIMELINE, F.FIELD_FULL_NAME, F.FIELD_AI_SCORE_WHY})

    def test_the_email_is_a_key_of_its_own(self):
        body = F.body_for(rows_for([(F.EMAIL, "ahmed.khan@gmail.com", {})]))
        self.assertEqual(body, {"lead_id": 555, "email": "ahmed.khan@gmail.com"})

    def test_what_the_tool_refuses(self):
        refusal = F.refusal
        self.assertEqual(refusal({"lead_id": 1, "fields": {F.FIELD_BOT_STATUS: 2476}}), "")
        self.assertIn("unknown field", refusal({"lead_id": 1, "fields": {"UF_CRM_A7_NOT_A_FIELD": "x"}}))
        self.assertIn("not one of its values", refusal({"fields": {F.FIELD_BEDROOMS: 28}}))  # 2 B/R
        self.assertIn("not one of its values", refusal({"fields": {F.FIELD_PURPOSE: 806}}))  # "I'm Agent"
        self.assertIn("not text", refusal({"fields": {F.FIELD_TIMELINE: 2027}}))
        self.assertIn("not a number", refusal({"fields": {F.FIELD_BUDGET: "about 30k"}}))
        self.assertIn("unknown field (only_if_empty)", refusal({"fields": {}, "only_if_empty": ["UF_X"]}))
        self.assertIn("email", refusal({"email": "ahmed..khan@gmail.com"}))
        self.assertEqual(refusal({"fields": {F.FIELD_BUDGET: "35000.5"}, "email": "a@b.co"}), "")

    @skipUnless(PHP.exists(), "the Bitrix tool's source is not in this checkout (a server image)")
    def test_allowed_is_the_tools_own_allow_list(self):
        source = PHP.read_text(encoding="utf-8")
        block = source.split("function a7_leadai_fields_allow(): array", 1)[1].split("];", 1)[0]
        php = {}
        for code, rule in re.findall(r"'(UF_[A-Z0-9_]+)'\s*=>\s*(\[[^\]]*\]|'[a-z_]+')", block):
            php[code] = rule.strip("'") if rule.startswith("'") else frozenset(int(pk) for pk in re.findall(r"(\d+)\s*=>\s*true", rule))
        self.assertEqual(php, dict(F.ALLOWED))
        self.assertIn("$in['email']", source)  # the e-mail is a key of the body, not a field


# C. The write ----------------------------------------------------------------------------------------------------------


SALE_LEAD = {**IDLE_LEAD, F.FIELD_RENT_SALE: "2444", F.FIELD_CLIENT_TYPE: "972", F.FIELD_BEDROOMS: "27"}


class WriteTests(CrmWritesBase):
    def rent_studio(self, facts=None):
        return self.queue(F.residential_writes(facts or {"for_client": False}, RENT, tracks.STUDIO))

    def test_an_empty_lead_takes_them(self):
        posted, _ = self.write(self.rent_studio())
        self.assertEqual(
            posted,
            [{
                "lead_id": 555,
                "fields": {F.FIELD_RENT_SALE: 2443, F.FIELD_CLIENT_TYPE: 1220, F.FIELD_BEDROOMS: 26, F.FIELD_PURPOSE: 805},
                "only_if_empty": [F.FIELD_RENT_SALE, F.FIELD_CLIENT_TYPE, F.FIELD_BEDROOMS, F.FIELD_PURPOSE],
            }],
        )

    def test_a_sale_lead_keeps_its_values_and_its_timeline_says_what_the_customer_wants(self):
        # "Actually I want to rent a studio" on a Property Finder sale lead (Sale, Buyer, 1 B/R): the agent's or the
        # portal's values stay (only while empty), and the lead's timeline tells the agent.
        posted, _ = self.write(self.rent_studio(), FakeBitrix(SALE_LEAD))
        self.assertEqual(
            posted,
            [{
                "lead_id": 555,
                "fields": {F.FIELD_PURPOSE: 805},
                "only_if_empty": [F.FIELD_PURPOSE],
                "comment": "The customer wants to rent a studio, but the lead says Rent/Sale: Sale, Client Type: Buyer, "
                "Bedrooms: 1 B/R; these were left as they are.",
            }],
        )
        for field in (F.FIELD_RENT_SALE, F.FIELD_CLIENT_TYPE, F.FIELD_BEDROOMS):
            row = self.row(field)
            self.assertEqual((bool(row.sent_at), row.error), (True, F.HELD_OTHER))

    def test_a_switch_from_rent_to_sale_is_noted(self):
        # The customer first wanted to rent (written: the lead was empty), then says "I want to buy it instead".
        self.write(self.rent_studio())
        ours = {**IDLE_LEAD, F.FIELD_RENT_SALE: "2443", F.FIELD_CLIENT_TYPE: "1220", F.FIELD_BEDROOMS: "26", F.FIELD_PURPOSE: "805"}
        posted, _ = self.write(self.queue(F.residential_writes({"for_client": False}, SALE, tracks.STUDIO)), FakeBitrix(ours))
        self.assertEqual(
            [body.get("comment") for body in posted],
            ["The customer wants to buy, but the lead says Rent/Sale: Rent, Client Type: Tenant; these were left as they are."],
        )
        # A unit switch alone: "a one-bedroom is better".
        posted, _ = self.write(self.queue(F.residential_writes({}, SALE, tracks.ONE_BR)), FakeBitrix({**ours, F.FIELD_RENT_SALE: "2444"}))
        self.assertEqual(
            [body.get("comment") for body in posted],
            ["The customer wants a one-bedroom, but the lead says Bedrooms: 0 B/R (studio); it was left as it is."],
        )

    def test_rent_and_sale_holds_both_and_the_same_value_says_nothing(self):
        both = {**IDLE_LEAD, F.FIELD_RENT_SALE: "2445", F.FIELD_CLIENT_TYPE: "1220", F.FIELD_BEDROOMS: "26", F.FIELD_PURPOSE: "805"}
        posted, _ = self.write(self.rent_studio(), FakeBitrix(both))
        self.assertEqual(posted, [])  # everything held, nothing to say
        self.assertEqual(self.row(F.FIELD_RENT_SALE).error, F.HELD_ALREADY)

    def test_a_client_type_never_goes_over_a_rent_sale(self):
        # A lead an agent marked Rent with no Client Type: a Client Type written alone makes a7_rent_sale.php derive Rent/Sale
        # again (Tenant gives Rent, or "Rent & Sale" beside a sale offering), over the agent's choice. It waits.
        lead = {**IDLE_LEAD, F.FIELD_RENT_SALE: "2443", F.FIELD_CLIENT_TYPE: ""}
        posted, _ = self.write(self.rent_studio(), FakeBitrix(lead))
        self.assertNotIn(F.FIELD_CLIENT_TYPE, posted[0]["fields"])
        self.assertEqual(self.row(F.FIELD_CLIENT_TYPE).error, F.HELD_FOR_RENT_SALE)
        self.assertNotIn("comment", posted[0])

    def test_the_note_is_said_once(self):
        # A retry after an answer lost on the way back (the rows were posted once): never a second note.
        ids = self.rent_studio()
        LeadAiCrmField.objects.filter(pk__in=ids).update(attempts=1)
        posted, _ = self.write(ids, FakeBitrix(SALE_LEAD))
        self.assertTrue(all("comment" not in body for body in posted))

    def test_an_email_goes_only_to_a_lead_without_one(self):
        writes = [(F.EMAIL, "ahmed.khan@gmail.com", {})]
        posted, _ = self.write(self.queue(writes), FakeBitrix({**IDLE_LEAD, "HAS_EMAIL": "N"}))
        self.assertEqual(posted, [{"lead_id": 555, "email": "ahmed.khan@gmail.com"}])
        LeadAiCrmField.objects.all().delete()
        with_one = {**IDLE_LEAD, "HAS_EMAIL": "Y", "EMAIL": [{"ID": "9", "VALUE_TYPE": "WORK", "VALUE": "old@mail.com", "TYPE_ID": "EMAIL"}]}
        posted, _ = self.write(self.queue(writes), FakeBitrix(with_one))
        self.assertEqual(posted, [])
        self.assertEqual(self.row(F.EMAIL).error, F.HELD_ALREADY)

    def test_what_holds_and_differs(self):
        rent = LeadAiCrmField(field=F.FIELD_RENT_SALE, value="2443", payload=EMPTY_ONLY)
        client = LeadAiCrmField(field=F.FIELD_CLIENT_TYPE, value="1220", payload=EMPTY_ONLY)
        self.assertTrue(F.holds({F.FIELD_RENT_SALE: "2444"}, rent))
        self.assertFalse(F.holds({F.FIELD_RENT_SALE: ""}, rent))
        self.assertTrue(F.holds({F.FIELD_RENT_SALE: "2443", F.FIELD_CLIENT_TYPE: ""}, client))
        self.assertFalse(F.holds({F.FIELD_RENT_SALE: "", F.FIELD_CLIENT_TYPE: ""}, client))
        # An unread lead holds nothing we know of, and so its Client Type waits for a read (the CRM review of batch 2e: posted
        # unread, a7_rent_sale.php derived Rent/Sale from it over an agent's value).
        self.assertFalse(F.holds(None, client))
        self.assertTrue(F.waits_for_read(None, client))
        self.assertFalse(F.waits_for_read(None, rent))
        self.assertEqual(F.differences({F.FIELD_RENT_SALE: ["2444"]}, [rent]), [rent])
        self.assertEqual(F.differences({F.FIELD_RENT_SALE: "2443"}, [rent]), [])
        self.assertEqual(F.differences({F.FIELD_RENT_SALE: "2445"}, [rent]), [])
        self.assertEqual(F.differences(None, [rent]), [])
        self.assertEqual(F.difference_note({F.FIELD_RENT_SALE: "9999"}, [rent]), "The customer wants to rent, but the lead says Rent/Sale: another value; it was left as it is.")


# D. A turn end to end --------------------------------------------------------------------------------------------------


class TurnTests(NotAShopBase):
    def test_a_studio_seekers_turn_queues_its_fields_beside_its_bot_status(self):
        # A question in it, so the rent flow's model answers (a plain first burst gets code's opener, which reads no facts).
        message = self.inbound("I need a studio in Spain cluster for myself, moving next month. How much is it?")
        live = res_answer(
            "Studios in Spain Cluster are generally around AED 29,000–33,000 a year. Do you prefer a balcony?",
            facts={"for_client": False, "move_in": "next month", "property_type": "studio", "intent": "rent", "community": "Spain"},
        )
        self.turn(message, [live])
        self.assertEqual((self.state().track, self.state().unit), (RENT, tracks.STUDIO))
        self.assertEqual(
            self.fields(),
            [
                (F.FIELD_BOT_STATUS, "2476"),
                (F.FIELD_RENT_SALE, "2443"),
                (F.FIELD_CLIENT_TYPE, "1220"),
                (F.FIELD_BEDROOMS, "26"),
                (F.FIELD_PURPOSE, "805"),
                (F.FIELD_CLUSTERS, "Spain"),
                (F.FIELD_TIMELINE, "next month"),
            ],
        )
        payloads = dict(LeadAiCrmField.objects.values_list("field", "payload"))
        self.assertEqual(payloads[F.FIELD_RENT_SALE], EMPTY_ONLY)
        self.assertEqual(payloads[F.FIELD_CLUSTERS], {})
        self.fields_delay.assert_called_once()  # one batch: one call to the tool
        self.assertIn(F.FIELD_RENT_SALE, LeadAiTurn.objects.get().actions["crm_fields"])
        # The next turn says nothing new: nothing is queued again.
        self.later(3)
        self.turn(self.inbound("ok", seconds_ago=10), [shop_answer("Great, I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", invited=True)])
        self.assertEqual(len(self.fields()), 7)

    def test_a_shop_customers_turn_writes_none_of_them(self):
        message = self.inbound("I need a shop for my mobile phone business")
        self.turn(message, [shop_answer("A mobile phone shop, got it. Is the shop for yourself, or are you checking for a client?", facts={"business_activity": "mobile phones", "for_client": False})])
        self.assertEqual(self.state().track, tracks.SHOP)
        self.assertEqual([field for field, _ in self.fields() if field in leadai_eval.CRM_NAMES], [])

    def test_a_brokers_purpose_broker_is_never_lost_to_ours(self):
        # A studio seeker who said "for myself" earlier (facts.for_client false) now says "Sorry, actually I am an agent, it is
        # for my client", and the model hands over as a broker without recording for_client again: Purpose Broker (2467) and
        # Bot Status Broker go; our "I want for myself" (805) in the same batch would have replaced it (tasks._replaced).
        self.set_state(track=RENT, unit=tracks.STUDIO, facts={"for_client": False, "need": "home", "wanted": "a studio", "property_type": "studio"})
        message = self.inbound("Sorry, actually I am an agent, it is for my client")
        self.turn(message, [shop_answer("Thank you, I'll share it with our agent.", handover="broker_or_for_client")])
        self.assertTrue(self.actions(message).get("broker") or self.state().paused_at)
        purposes = [value for field, value in self.fields() if field == F.FIELD_PURPOSE]
        self.assertEqual(purposes, [str(F.PURPOSE_BROKER)])
        self.assertIn((F.FIELD_BOT_STATUS, str(F.STATUS_BROKER)), self.fields())

    def test_a_brokers_batch_posts_purpose_broker(self):
        # The same batch through the tool: Purpose Broker goes (a newer Purpose row would have replaced it: tasks._replaced).
        turn = F.turn_writes({}, {"for_client": False}, answered=True, first=True, handover=False, broker=True, booked=False)
        writes = turn + F.residential_writes({"for_client": False}, RENT, tracks.STUDIO, besides=turn)
        with self.captureOnCommitCallbacks(execute=True):
            ids = F.queue(self.conversation, self.chat, writes)
        posted = []
        with patch("apps.crmlink.client.call", side_effect=FakeBitrix()), patch(
            "apps.leadai.assistant.crm_fields.post", side_effect=lambda body: posted.append(body) or {"ok": True}
        ):
            from apps.leadai import tasks

            tasks.write_crm_fields.apply(args=[ids])
        self.assertEqual(posted[0]["fields"][F.FIELD_PURPOSE], F.PURPOSE_BROKER)


# E. The eval mirrors it --------------------------------------------------------------------------------------------------


def scenario(scenario_id):
    return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)


CRM_SCENARIOS = ("shops-crm-rent-studio-spain", "shops-crm-for-myself-move-in", "shops-crm-2br-writes-nothing")


@override_settings(LEADAI_OPENAI_API_KEY="test")
class EvalTests(SimpleTestCase):
    def run_scenario(self, scenario_id, completion=None):
        with patch(MODEL, return_value=completion or RIGHT[scenario_id]):
            return leadai_eval.run_once(scenario(scenario_id), scenario_id)

    def test_the_crm_scenarios_pass_with_the_right_answers(self):
        for scenario_id in CRM_SCENARIOS:
            with self.subTest(scenario_id):
                self.assertEqual(self.run_scenario(scenario_id).failures, [])
        run = self.run_scenario("shops-crm-for-myself-move-in")
        self.assertEqual(
            run.crm,
            F.residential_writes({**scenario("shops-crm-for-myself-move-in").facts, "for_client": False, "move_in": "next month"}, RENT, tracks.STUDIO),
        )

    def test_every_shops_scenario_checks_the_tool_takes_its_fields(self):
        shops = [s for s in leadai_eval.SCENARIOS if s.playbook == leadai_eval.IC_SHOPS]
        self.assertTrue(shops)
        for s in shops:
            with self.subTest(s.id):
                self.assertIn("crm_ok", frozenset().union(*(check.kinds for check in leadai_eval.checks_for(s))))
        self.assertFalse(any("crm_ok" in check.kinds for check in leadai_eval.checks_for(scenario("shop-activity"))))

    def test_without_the_flag_or_the_model_saying_so_they_fail(self):
        with patch.object(F, "RES_FIELDS_LIVE", False):
            self.assertIn("no Rent/Sale written", "; ".join(self.run_scenario("shops-crm-rent-studio-spain").failures))
        # The model that never records "for myself": no Purpose, and the scenario says so.
        silent = leadai_eval.Run(scenario=scenario("shops-crm-for-myself-move-in"), label="x")
        silent.crm = F.residential_writes({}, RENT, tracks.STUDIO)
        self.assertEqual(leadai_eval.crm_writes((F.FIELD_PURPOSE, F.PURPOSE_MYSELF))(silent), "no Purpose written")

    def test_crm_ok_catches_a_value_the_tool_refuses(self):
        run = leadai_eval.Run(scenario=scenario("shops-crm-2br-writes-nothing"), label="x")
        run.crm = [(F.FIELD_BEDROOMS, 28, EMPTY_ONLY)]
        self.assertIn("not one of its values", leadai_eval.crm_ok()(run))
        run.crm = [(F.FIELD_TIMELINE, "2027", {})]
        self.assertIsNone(leadai_eval.crm_ok()(run))
