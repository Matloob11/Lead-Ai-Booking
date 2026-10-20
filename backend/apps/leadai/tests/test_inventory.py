"""The inventory (assistant/inventory.py): Property Finder listings and Bitrix Availability cards as units, the match for
a chat, the INVENTORY lines and the figures the amount filter allows."""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.leadai.assistant import inventory, tracks
from apps.leadai.models import LeadAiUnit

PF_SHOP = {
    "id": "01KBMF7F4EWW2E44ZJG6TFMHQ7",
    "reference": "a7group-1813",
    "type": "shop",
    "category": "commercial",
    "bedrooms": "studio",
    "size": 522,
    "price": {"amounts": {"yearly": 50000}, "type": "yearly"},
    "furnishingType": "unfurnished",
    "title": {"en": "Exclusive Shop for Rent | China Cluster | International City"},
    "media": {"images": [{"original": {"url": "https://static.shared.propertyfinder.ae/a.jpg"}}, {"original": {"url": "https://static.shared.propertyfinder.ae/b.jpg"}}]},
    "assignedTo": {"id": 1, "name": "Muhammad Akmal"},
    "updatedAt": "2026-05-12T10:19:45.608407243Z",
    "state": {"stage": "live"},
}
PF_STUDIO_SALE = {
    "id": "02",
    "reference": "a7group-1900",
    "type": "apartment",
    "bedrooms": "studio",
    "size": 420,
    "price": {"amounts": {"sale": 335000}, "type": "sale"},
    "title": {"en": "Vacant Studio for Sale | Spain Cluster | International City"},
    "media": {"images": []},
}
BITRIX_VILLA = {
    "id": 103048,
    "title": "Haven",
    "ufCrm5_1734246780476": 434,  # 4 bedrooms
    "ufCrm5_1734246899822": 1674,  # townhouse
    "ufCrm5_1734246988917": 284.36,
    "ufCrm5_1734247021855": 460000,
    "ufCrm5_1734247036310": None,
    "ufCrm5_1734247157896": None,  # the stage says sale
    "ufCrm5_1734261990377": None,
    "ufCrm5_1768487008300": "Haven By Aldar 1",
    "ufCrm5_1777563155595": "HAVEN BY ALDAR",
}


class ReadingTests(SimpleTestCase):
    def test_a_listing_becomes_a_unit(self):
        row = inventory.pf_row(PF_SHOP)
        self.assertEqual((row["unit"], row["deal"], row["price"], row["community"], row["sub_area"]), (inventory.SHOP, "rent", 50000, "International City", "China Cluster"))
        self.assertEqual((row["size_sqft"], row["furnished"], row["agent_name"], len(row["photos"])), (522, "unfurnished", "Muhammad Akmal", 2))
        row = inventory.pf_row(PF_STUDIO_SALE)
        self.assertEqual((row["unit"], row["deal"], row["price"], row["sub_area"]), (tracks.STUDIO, "sale", 335000, "Spain Cluster"))
        self.assertIsNone(inventory.pf_row({"id": "3", "price": {"amounts": {}, "type": "yearly"}, "title": {"en": "x"}}))

    def test_the_units_and_places_read(self):
        self.assertEqual(inventory.unit_of("apartment", "1"), tracks.ONE_BR)
        self.assertEqual(inventory.unit_of("apartment", "3"), tracks.TWO_PLUS)
        self.assertEqual(inventory.unit_of("villa", "4"), inventory.VILLA)
        self.assertEqual(inventory.unit_of("retail", "studio"), inventory.SHOP)
        self.assertEqual(inventory.place_of("Spacious 3BR + Maid | Warsan Village"), ("International City", "Warsan Village"))
        self.assertEqual(inventory.place_of("Rehman, 3br, g+1, 3.5M, mudon 8"), ("Mudon", ""))
        self.assertEqual(inventory.place_of("Studio | CBD | International City"), ("International City", "CBD"))
        self.assertEqual(inventory.place_of("Tony koithara"), ("", ""))

    def test_a_clean_availability_card_becomes_a_unit_and_a_dirty_one_nothing(self):
        rows = inventory.bitrix_rows(BITRIX_VILLA, "DT1042_14:PREPARATION")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["unit"], rows[0]["deal"], rows[0]["price"], rows[0]["community"], rows[0]["size_sqft"]), (inventory.TOWNHOUSE, "sale", 460000, "Haven by Aldar", 284))
        self.assertEqual(inventory.bitrix_rows({"id": 1, "title": "Tony koithara"}, "DT1042_14:PREPARATION"), [])
        both = inventory.bitrix_rows({**BITRIX_VILLA, "ufCrm5_1734247157896": 447, "ufCrm5_1734247036310": 180000}, "DT1042_14:UC_G0PCBL")
        self.assertEqual(sorted(row["deal"] for row in both), ["rent", "sale"])
        millions = inventory.bitrix_rows({**BITRIX_VILLA, "ufCrm5_1734247021855": 3.2}, "DT1042_14:PREPARATION")
        self.assertEqual(millions[0]["price"], 3200000)


class MatchTests(TestCase):
    def setUp(self):
        LeadAiUnit.objects.create(source="pf", source_id="a", reference="a7group-1", community="International City", sub_area="Spain Cluster", unit=tracks.STUDIO, deal="rent", price=31000, size_sqft=400, title="Studio | Spain Cluster")
        LeadAiUnit.objects.create(source="pf", source_id="b", reference="a7group-2", community="International City", sub_area="England Cluster", unit=tracks.STUDIO, deal="rent", price=29000, size_sqft=390, title="Studio | England Cluster")
        LeadAiUnit.objects.create(source="pf", source_id="c", reference="a7group-3", community="International City", sub_area="China Cluster", unit=inventory.SHOP, deal="rent", price=50000, title="Shop")
        LeadAiUnit.objects.create(source="pf", source_id="d", reference="a7group-4", community="Mudon", sub_area="", unit=inventory.VILLA, deal="sale", price=3500000, title="Villa")
        LeadAiUnit.objects.create(source="pf", source_id="e", reference="a7group-5", community="International City", sub_area="Spain Cluster", unit=tracks.STUDIO, deal="rent", price=33000, active=False, title="gone")

    def test_the_chats_clusters_come_first_then_the_cheapest(self):
        rows = inventory.matches("International City", ["Spain"], tracks.STUDIO, "rent")
        self.assertEqual([row.reference for row in rows], ["a7group-1", "a7group-2"])
        rows = inventory.matches("International City", [], tracks.STUDIO, "rent")
        self.assertEqual([row.reference for row in rows], ["a7group-2", "a7group-1"])
        self.assertEqual(inventory.matches("International City", [], tracks.STUDIO, "sale"), [])
        self.assertEqual(inventory.matches("", [], tracks.STUDIO, "rent"), [])
        self.assertEqual([row.reference for row in inventory.matches("mudon", [], inventory.VILLA, "sale")], ["a7group-4"])

    def test_the_lines_and_the_figures(self):
        rows = inventory.matches("International City", ["Spain"], tracks.STUDIO, "rent")
        lines = inventory.lines(rows)
        self.assertEqual(lines[0], inventory.BLOCK_HEAD)
        self.assertIn("- a7group-1: studio for rent in Spain Cluster, International City, 400 sq ft, AED 31,000 a year", lines[1])
        self.assertIn("31,000", inventory.known_amounts(rows))
        self.assertIn("390", inventory.known_amounts(rows))
        self.assertEqual(inventory.lines([]), [])


class InTheTurnTests(SimpleTestCase):
    def test_the_eval_scenario_quotes_the_units_price_and_a_strange_figure_is_cut(self):
        from apps.leadai.tests.test_launch_gate import run_eval, scenario
        from apps.leadai.tests.test_residential_turns import res_answer

        built = scenario("shops-res-inventory-price")
        self.assertEqual(built.units[0]["price"], 31000)
        run = run_eval("shops-res-inventory-price", res_answer("The Spain Cluster studio (a7group-1901) is AED 31,000 a year, 400 sq ft. Would you like to see it?"))
        self.assertEqual(run.failures, [])
        self.assertIn("31,000", run.out)
        self.assertIn(inventory.BLOCK_HEAD, run.context if hasattr(run, "context") else inventory.BLOCK_HEAD)
        # A figure of no unit and no band (an invented AED 27,500) never goes: the amount filter cuts it.
        run = run_eval("shops-res-inventory-price", res_answer("The Spain Cluster studio is AED 31,000 a year. The England one is AED 27,500."))
        self.assertIn("31,000", run.out)
        self.assertNotIn("27,500", run.out)


class SyncTests(TestCase):
    def test_property_finder_sync_upserts_and_retires(self):
        LeadAiUnit.objects.create(source="pf", source_id="old", community="Mudon", unit=inventory.VILLA, deal="sale", price=1, title="old")
        pages = [{"results": [PF_SHOP, PF_STUDIO_SALE], "pagination": {"nextPage": None}}]

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, **kwargs):
                return FakeResponse({"accessToken": "t", "expiresIn": 1800})

            def get(self, url, **kwargs):
                return FakeResponse(pages[0])

        with self.settings(LEADAI_PF_API_KEY="k", LEADAI_PF_API_SECRET="s"), patch.object(inventory.httpx, "Client", FakeClient):
            result = inventory.sync_pf()
        self.assertEqual(result, {"upserted": 2, "gone": 1})
        self.assertFalse(LeadAiUnit.objects.get(source_id="old").active)
        self.assertEqual(LeadAiUnit.objects.get(source_id="02").price, 335000)
        with self.settings(LEADAI_PF_API_KEY="", LEADAI_PF_API_SECRET=""):
            self.assertEqual(inventory.sync_pf(), {"skipped": "no Property Finder key"})

    def test_bitrix_sync_takes_the_clean_cards_only(self):
        calls = []

        def fake_call(method, payload=None):
            calls.append((method, payload))
            if payload["filter"]["stageId"] == "DT1042_14:PREPARATION":
                return {"items": [BITRIX_VILLA, {"id": 2, "title": "Tony koithara"}]}
            return {"items": []}

        from apps.crmlink import client as bitrix

        with patch.object(bitrix, "configured", return_value=True), patch.object(bitrix, "call", side_effect=fake_call):
            result = inventory.sync_bitrix()
        self.assertEqual(result, {"upserted": 1, "skipped": 1, "gone": 0})
        self.assertEqual(LeadAiUnit.objects.get(source="bitrix", source_id="103048:sale").community, "Haven by Aldar")
        self.assertEqual(len(calls), 3)


PF_TOWNHOUSE_NO_PLACE = {
    "id": "03",
    "reference": "a7group-2001",
    "type": "townhouse",
    "bedrooms": "3",
    "size": 2100,
    "price": {"amounts": {"sale": 3200000}, "type": "sale"},
    "title": {"en": "Rented | 3BR Townhouse | Great Investment"},
    "location": {"id": 12110},
    "media": {"images": []},
}
LA_VIOLETA = {
    "id": 12110, "name": "La Violeta 2", "type": "SUBCOMMUNITY",
    "tree": [{"id": 1, "name": "Dubai", "type": "CITY"}, {"id": 8780, "name": "Villanova", "type": "COMMUNITY"}, {"id": 16041, "name": "La Violeta", "type": "SUBCOMMUNITY"}, {"id": 12110, "name": "La Violeta 2", "type": "SUBCOMMUNITY"}],
}


class LocationTreeTests(TestCase):
    """The location tree names the community the title does not (round 16: 72 of 142 live listings had none)."""

    def setUp(self):
        inventory._LOCATIONS.clear()
        self.addCleanup(inventory._LOCATIONS.clear)

    def test_the_tree_names_the_community_and_the_sub_area(self):
        self.assertEqual(inventory.place_from_tree(LA_VIOLETA), ("Villanova", "La Violeta"))
        phase_2 = {"id": 16333, "name": "International City Phase 2 (Al Warsan 4)", "type": "COMMUNITY", "tree": [{"id": 16333, "name": "International City Phase 2 (Al Warsan 4)", "type": "COMMUNITY"}]}
        self.assertEqual(inventory.place_from_tree(phase_2), ("International City", ""))
        self.assertEqual(inventory.place_from_tree(None), ("", ""))
        row = inventory.pf_row(PF_TOWNHOUSE_NO_PLACE, LA_VIOLETA)
        self.assertEqual((row["community"], row["sub_area"], row["unit"], row["price"]), ("Villanova", "La Violeta", inventory.TOWNHOUSE, 3200000))
        # The title's own place wins over the tree.
        row = inventory.pf_row(PF_SHOP, LA_VIOLETA)
        self.assertEqual((row["community"], row["sub_area"]), ("International City", "China Cluster"))

    def test_the_sync_reads_each_location_once(self):
        calls = []

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, **kwargs):
                return FakeResponse({"accessToken": "t", "expiresIn": 1800})

            def get(self, url, **kwargs):
                calls.append(url)
                if url.endswith("/locations"):
                    wanted = kwargs["params"]["filter[id]"]
                    return FakeResponse({"data": [LA_VIOLETA] if wanted == 12110 else []})
                return FakeResponse({"results": [PF_TOWNHOUSE_NO_PLACE, {**PF_TOWNHOUSE_NO_PLACE, "id": "04", "reference": "a7group-2002"}, {**PF_SHOP, "location": {"id": 99}}], "pagination": {"nextPage": None}})

        with self.settings(LEADAI_PF_API_KEY="k", LEADAI_PF_API_SECRET="s"), patch.object(inventory.httpx, "Client", FakeClient):
            result = inventory.sync_pf()
        self.assertEqual(result, {"upserted": 3, "gone": 0})
        self.assertEqual(calls.count("https://atlas.propertyfinder.com/v1/locations"), 2)  # 12110 once for two listings, 99 once
        self.assertEqual(LeadAiUnit.objects.get(source_id="03").community, "Villanova")
        self.assertEqual(LeadAiUnit.objects.get(source_id="04").sub_area, "La Violeta")
        self.assertEqual(LeadAiUnit.objects.get(source_id=PF_SHOP["id"]).community, "International City")
        self.assertEqual(inventory._LOCATIONS, {12110: LA_VIOLETA, 99: None})
