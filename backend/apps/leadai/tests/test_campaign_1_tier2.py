"""The first mixed campaign (2026-10-19), the second tier (docs/superpowers/specs/2026-10-19-leadai-campaign-1-issues.md):

- I13: an owner offering a unit is no tenant (chat 50020: "I am owner I want to rent it" got photos and a viewing slot);
  a stored home track stays over a bare other_need tag (chat 50169: "we need a decent family space" on a studio-rent
  track got the "options across Dubai" line).
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import needs, tracks


class OwnerWordsTests(SimpleTestCase):
    def test_an_owner_offering_a_unit_is_read(self):
        for said in (
            "I am owner I want to rent it",
            "I'm the owner of a studio in France cluster",
            "Owner here, want to rent out my flat",
            "I have a flat for rent",
            "main malik hoon",
        ):
            with self.subTest(said):
                need = needs.detect([said])
                self.assertIsNotNone(need)
                self.assertEqual(need.kind, needs.SELL)

    def test_a_tenant_is_not_an_owner(self):
        for said in ("I want to rent a studio", "the owner's number please", "is the owner flexible on price?", "I am the owner of a company"):
            with self.subTest(said):
                need = needs.detect([said])
                self.assertTrue(need is None or need.kind != needs.SELL)


class StoredHomeTrackTests(SimpleTestCase):
    def test_a_bare_other_tag_does_not_move_a_stored_rent_track(self):
        decision = tracks.decide(
            words=["we need a decent family space"], facts={"intent": "rent", "property_type": "studio"}, lead={},
            model_tag="other_need", stored=tracks.RENT, stored_unit=tracks.STUDIO,
        )
        self.assertEqual(decision.track, tracks.RENT)

    def test_cbd_is_no_other_area(self):
        # Chat 49953: International City's own CBD cluster, tagged other_area by the model.
        decision = tracks.decide(
            words=["Do u have any units in cbd"], facts={"intent": "rent", "property_type": "studio"}, lead={},
            model_tag="other_area", stored=tracks.RENT, stored_unit=tracks.STUDIO,
        )
        self.assertEqual(decision.track, tracks.RENT)

    def test_a_shop_track_still_moves_on_the_tag(self):
        # Only a stored home track is kept: a shop customer the model reads as wanting another area still moves.
        decision = tracks.decide(
            words=["ok"], facts={"intent": "rent", "property_type": "shop"}, lead={},
            model_tag="other_area", stored=tracks.SHOP,
        )
        self.assertEqual(decision.track, tracks.OTHER)

    def test_a_named_other_property_still_moves_it_by_its_words(self):
        # Step 1 reads the words before any tag: a villa named moves the track whatever the tag says.
        for words, tag in ((["actually I need a villa in Mirdif"], "other_need"), (["I want a 2BR instead"], "")):
            with self.subTest(words):
                decision = tracks.decide(
                    words=words, facts={"intent": "rent", "property_type": "studio"}, lead={},
                    model_tag=tag, stored=tracks.RENT, stored_unit=tracks.STUDIO,
                )
                self.assertEqual((decision.track, decision.reason), (tracks.OTHER, tracks.WORDS))
