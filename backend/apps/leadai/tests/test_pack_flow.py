"""The community packs' flow (round 17; Matloob 2026-10-20: "pictures Property Finder se jayein, office refer karein"): a
home in a community with a pack and live units takes the pack's rent or sale track (tracks.pack_decision), reads the
pack's facts and INVENTORY in International City's place with its own prompt (PACK_SYSTEM) and no opener of code's, quotes
the listed unit (residential.pack_quote when the model does not), and the quoted unit's Property Finder photos follow from
their own task (pack_photos). A community with nothing listed stays another area, as before."""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.leadai.assistant import communities, inventory, prompt, residential, tracks
from apps.leadai.models import LeadAiUnit
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer
from apps.leadai.tests.test_tracks_turns import MixedBase

MUDON = communities.pack_of({"name": "Mudon", "aliases": ["mudon", "مدن"], "units": ["villa", "townhouse", "two_plus"]})
VILLANOVA = communities.pack_of({"name": "Villanova", "aliases": ["villanova", "villa nova"], "units": ["villa", "townhouse"]})
PACKS = (MUDON, VILLANOVA)
TOWNHOUSE = dict(
    source="pf", source_id="m1", reference="a7group-1633", community="Mudon", sub_area="Mudon Al Ranim 6", unit="townhouse", bedrooms="3",
    deal="rent", price=180000, size_sqft=1843, title="3BR Townhouse | Mudon Al Ranim 6 | Mudon", photos=["https://static.shared.propertyfinder.ae/a.jpg", "https://static.shared.propertyfinder.ae/b.jpg"],
)
QUOTE = "We have a 3-bedroom townhouse in Mudon Al Ranim 6, 1,843 sq ft, at AED 180,000 a year (ref a7group-1633); our agent confirms it is still available. Would you like to visit our office?"


class DecisionTests(SimpleTestCase):
    def decide(self, words, **extra):
        return tracks.decide(words=[words], facts={}, packs=PACKS, clusters=tracks.DEFAULT_CLUSTERS, **extra)

    def test_a_home_in_a_pack_community_is_that_packs_track(self):
        decision = self.decide("I need a 3 bedroom townhouse in Mudon to rent")
        self.assertEqual((decision.track, decision.unit, decision.community, decision.reason, decision.deal), ("rent", "townhouse", "Mudon", tracks.PACK, "rent"))
        decision = self.decide("I want to buy a villa in Villanova")
        self.assertEqual((decision.track, decision.unit, decision.community, decision.deal), ("sale", "villa", "Villanova", "sale"))
        decision = self.decide("a 2 bedroom apartment in mudon")
        self.assertEqual((decision.track, decision.unit, decision.community), ("rent", "two_plus", "Mudon"))
        self.assertEqual(decision.as_dict()["community"], "Mudon")

    def test_the_stored_community_and_the_lead_context_decide_too(self):
        decision = tracks.decide(words=["What is the price of the villa?"], facts={"property_type": "villa"}, stored="sale", stored_unit="villa", packs=PACKS, stored_community="Villanova")
        self.assertEqual((decision.track, decision.unit, decision.community), ("sale", "villa", "Villanova"))
        decision = tracks.decide(words=["Hi, I need a townhouse"], facts={}, lead={"community": "Mudon", "unit": "two_plus"}, packs=PACKS)
        self.assertEqual((decision.track, decision.unit, decision.community), ("rent", "townhouse", "Mudon"))

    def test_without_a_pack_another_area_stays_other_and_a_shop_stays_a_shop(self):
        decision = self.decide("I need a villa in JVC")
        self.assertEqual((decision.track, decision.community), ("other", ""))
        decision = tracks.decide(words=["I need a villa in Mudon"], facts={}, packs=(), clusters=tracks.DEFAULT_CLUSTERS)
        self.assertEqual((decision.track, decision.community), ("other", ""))
        decision = self.decide("I need a shop in Mudon")
        self.assertEqual((decision.track, decision.community), ("shop", ""))
        # International City's own flow, byte for byte: a studio in Spain Cluster.
        decision = self.decide("I need a studio in Spain cluster")
        self.assertEqual((decision.track, decision.unit, decision.community, decision.clusters), ("rent", "studio", "", ("Spain",)))


class ResidentialGuardTests(TestCase):
    def setUp(self):
        self.unit = LeadAiUnit.objects.create(**TOWNHOUSE)

    def settle(self, reply, texts, units=None, **facts):
        from apps.leadai.assistant import schema

        answer = schema.normalize(res_answer(reply, facts=facts).data, shops=True, residential=True)
        residential.settle(
            answer, [], texts, track="rent", unit="townhouse", facts={}, residential_facts=None, shops_facts=None,
            office_address="Russia Cluster, Building V03, Shop 20", pack=True, units=[self.unit] if units is None else units,
        )
        return answer

    def test_the_price_asked_gets_the_listed_unit_when_the_model_gave_none(self):
        answer = self.settle("Sure, a townhouse in Mudon. Would you like to visit our office?", ["what is the rent?"])
        self.assertIn("AED 180,000 a year (ref a7group-1633)", answer["reply"])
        self.assertIn("pack_quote", answer["trimmed"])
        # The model quoted it already: nothing added, and "we have" stays (the unit is live).
        answer = self.settle(QUOTE, ["what is the rent?"])
        self.assertEqual(answer["reply"].count("180,000"), 1)
        self.assertIn("We have a 3-bedroom townhouse", answer["reply"])
        self.assertNotIn("availability", answer.get("trimmed") or [])

    def test_nothing_listed_keeps_the_availability_guard_and_the_honest_line(self):
        answer = self.settle("We have a lovely villa available in Mudon. What is your budget?", ["how much is the rent?"], units=[])
        self.assertNotIn("available in Mudon", answer["reply"])
        self.assertNotIn("180,000", answer["reply"])
        self.assertEqual(residential.pack_quote([]), "")
        self.assertTrue(residential.asks_price(["kitna kiraya hai?"]))
        self.assertFalse(residential.asks_price(["ok thanks"]))

    def test_international_city_steps_do_not_run_for_a_pack(self):
        answer = self.settle("Perfect, a townhouse for yourself. Any cluster you prefer, or are you flexible?", ["For myself"], for_client=False)
        self.assertNotIn("balcony", answer["reply"].lower())
        self.assertNotIn("requirement_first", answer.get("trimmed") or [])
        self.assertNotIn("cluster_first", answer.get("trimmed") or [])

    def test_no_opener_of_codes_for_a_pack_chat(self):
        decision = tracks.Decision("rent", "townhouse", deal="rent", reason=tracks.PACK, community="Mudon")
        self.assertIsNone(residential.pre_model_rule(decision, {}, words=["I need a townhouse in Mudon"], entered=True, plain=True, pack=True))
        spec = residential.pre_model_rule(tracks.Decision("rent", "studio", deal="rent"), {}, words=["I need a studio"], entered=True, plain=True)
        self.assertEqual(spec["kind"], "open")


class PromptAndContextTests(TestCase):
    def test_the_pack_prompt_and_the_context_lines(self):
        self.assertIs(prompt.system_prompt("ic_shops", residential=True, pack=True), prompt.PACK_SYSTEM)
        self.assertIs(prompt.system_prompt("ic_shops", residential=True), prompt.RES_SYSTEM)
        for heading in ("TRACK", "HARD RULES", "STYLE", "LANGUAGE", "STEPS", "CHARGES", "BOOKING", "REMINDER AND ARRIVAL", "HANDOVER", "STOP, SILENCE", "READING THE CONTEXT", "OUTPUT"):
            self.assertIn(f"\n{heading}", prompt.PACK_SYSTEM, heading)
        self.assertIn("Prices come from INVENTORY only", prompt.PACK_SYSTEM)
        self.assertNotIn("Spain Cluster", prompt.PACK_SYSTEM.split("STYLE")[0])
        unit = LeadAiUnit(**TOWNHOUSE)
        facts = communities.facts_block(MUDON, [unit])
        self.assertIn("- Community: Mudon.", facts)
        self.assertIn("INVENTORY below lists the units", facts)
        self.assertIn(communities.NO_BAND_LINE, communities.facts_block(MUDON, []))
        self.assertEqual(communities.lines(MUDON)[0], communities.BLOCK_HEAD)
        self.assertEqual(inventory.pack_units("two_plus"), ("two_plus", "villa", "townhouse"))
        self.assertEqual(inventory.pack_units("villa"), ("villa",))
        self.assertEqual(inventory.by_reference([unit], "the a7group-1633 one").reference, "a7group-1633")

    def test_only_packs_with_live_units_reach_the_decision(self):
        self.assertEqual(communities.named_packs(), ())
        LeadAiUnit.objects.create(**TOWNHOUSE)
        self.assertEqual([pack.name for pack in communities.named_packs()], ["Mudon"])
        self.assertIn("Villanova", [pack.name for pack in communities.named_packs(with_units=False)])


class PackTurnTests(MixedBase):
    def setUp(self):
        super().setUp()
        self.unit = LeadAiUnit.objects.create(**TOWNHOUSE)

    def test_a_mudon_townhouse_quotes_the_listed_unit_and_queues_its_photos(self):
        message = self.inbound("I need a 3 bedroom townhouse in Mudon to rent, what is the rent?")
        with patch("apps.leadai.tasks.send_pack_photos.delay") as photos:
            outcome, calls, _, _ = self.turn(message, [res_answer(QUOTE, facts={"property_type": "townhouse", "bedrooms": "3", "intent": "rent", "community": "Mudon"})])
        self.assertEqual(outcome.status, "replied", outcome.reason)
        self.assertIn("180,000", self.body(outcome))
        self.assertEqual(calls[0][0]["content"], prompt.PACK_SYSTEM)
        context = calls[0][1]["content"]
        self.assertIn(communities.BLOCK_HEAD, context)
        self.assertIn("a7group-1633", context)
        self.assertIn("- Community: Mudon.", context)
        self.assertNotIn("Studios to rent: AED", context)
        self.assertNotIn("CHARGE LINES", context)
        state = self.state()
        self.assertEqual((state.track, state.unit, state.community), ("rent", "townhouse", "Mudon"))
        self.assertEqual(state.facts.get("pack_photos"), ["a7group-1633"])
        photos.assert_called_once()
        args = photos.call_args.args
        self.assertEqual((args[0], args[1], args[3]), (self.conversation.pk, self.unit.pk, "en"))
        actions = self.actions(message)
        self.assertEqual((actions["pack_photos"], actions["track"]["community"]), ("a7group-1633", "Mudon"))
        # The same unit again: no second set of photos.
        with patch("apps.leadai.tasks.send_pack_photos.delay") as photos:
            self.turn(self.inbound("ok, and is it furnished?"), [res_answer("It is unfurnished (ref a7group-1633). Shall I hold a slot for you to see it?")])
        photos.assert_not_called()

    def test_nothing_listed_for_the_community_stays_another_area(self):
        LeadAiUnit.objects.all().delete()
        message = self.inbound("I need a villa in Mudon to rent")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(self.state().track, "other")
        self.assertNotEqual(self.state().community, "Mudon")


class PhotosTests(MixedBase):
    def setUp(self):
        super().setUp()
        self.unit = LeadAiUnit.objects.create(**TOWNHOUSE)
        from apps.leadai.models import LeadAiChatState

        LeadAiChatState.for_conversation(self.conversation)

    def test_the_photos_are_downloaded_uploaded_and_sent_once_each(self):
        sent = []

        class FakeResponse:
            headers = {"content-type": "image/jpeg"}
            content = b"\xff\xd8\xff" + b"0" * 100

            def raise_for_status(self):
                return None

        class FakeHttp:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, **kwargs):
                return FakeResponse()

        def upload(client, phone_number_id, file_obj, filename, mime_type):
            return f"gw-{filename}"

        def send_media(client, phone_number_id, to, kind, media_id, caption=None, filename=None):
            sent.append((kind, media_id, caption))
            return {"messages": [{"id": f"wamid.{len(sent)}"}]}

        from apps.leadai import pack_photos

        with patch.object(pack_photos.httpx, "Client", FakeHttp), patch.multiple("apps.gateway.client.AlotsClient", upload_media=upload, send_media=send_media), patch(
            "apps.inbox.events.publish_message"
        ), patch("apps.inbox.events.publish_status"), patch("apps.leadai.tasks.record_crm_note.delay"), patch.object(pack_photos, "SEND_PAUSE", 0), self.captureOnCommitCallbacks(execute=True):
            result = pack_photos.send_photos(self.conversation.pk, self.unit.pk, None, "en")
        self.assertEqual((result["sent"], result["skipped"], result["stopped"]), (2, 0, ""))
        self.assertEqual([kind for kind, _, _ in sent], ["image", "image"])
        self.assertEqual(sent[0][2], "a7group-1633: 3BR Townhouse | Mudon Al Ranim 6 | Mudon")
        self.assertEqual(sent[1][2], "")
        from apps.inbox.models import Message

        rows = list(Message.objects.filter(conversation=self.conversation, kind="image").order_by("pk"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload["source"], pack_photos.SOURCE)
        self.assertEqual(rows[0].payload["reference"], "a7group-1633")
        self.assertIsNotNone(rows[0].media_id)
        self.assertEqual(rows[0].wamid, "wamid.1")

    def test_a_person_on_the_chat_or_a_closed_window_stops_the_photos(self):
        from apps.leadai import pack_photos
        from apps.leadai.models import LeadAiChatState

        LeadAiChatState.objects.filter(conversation=self.conversation).update(handed_over_at=NOW, handover_reason="unclear")
        result = pack_photos.send_photos(self.conversation.pk, self.unit.pk, None, "en")
        self.assertEqual(result["sent"], 0)
        self.assertTrue(result["stopped"])


class EvalTests(SimpleTestCase):
    def test_the_three_pack_scenarios_pass_with_their_right_answers(self):
        from apps.leadai.tests.test_eval_command import RIGHT

        for scenario_id in ("shops-pack-mudon-townhouse-rent-price", "shops-pack-mudon-no-units", "shops-pack-villanova-villa-sale-price"):
            with self.subTest(scenario_id):
                run = run_eval(scenario_id, RIGHT[scenario_id])
                self.assertEqual(run.failures, [], run.out)
        # A pack chat's model reply with no figure still quotes the unit (the guard), and a figure of International City's goes.
        run = run_eval("shops-pack-mudon-townhouse-rent-price", res_answer("Sure, a townhouse in Mudon. Studios in International City are around AED 29,000–33,000 a year. Would you like to visit our office?", facts={"property_type": "townhouse", "intent": "rent", "community": "Mudon"}))
        self.assertEqual(run.failures, [], run.out)
        self.assertIn("180,000", run.out)
        self.assertNotIn("29,000", run.out)
