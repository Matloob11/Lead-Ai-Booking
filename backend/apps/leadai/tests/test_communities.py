"""The community packs (assistant/communities.py; the advance plan's workstream B, v1): the seed, the pack a chat is about
(stored, the lead context, their words, else International City), the engine storing it, the endpoint."""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.leadai.assistant import communities
from apps.leadai.models import LeadAiCommunity
from apps.leadai.tests.test_assistant import Base
from apps.leadai.tests.test_residential_turns import RentBase, res_answer

IC = communities.pack_of(communities.SEED[0])
MUDON = communities.pack_of({"name": "Mudon", "aliases": ["mudon", "مدن"], "units": ["villa", "townhouse"]})
JVC = communities.pack_of({"name": "JVC", "aliases": ["jvc", "jumeirah village circle"]})
PACKS = [IC, MUDON, JVC]


class DecisionTests(SimpleTestCase):
    def test_the_default_pack_and_its_clusters(self):
        self.assertTrue(IC.default)
        self.assertIn("Spain Cluster", IC.sub_area_names())
        self.assertEqual(communities.sub_areas_in(["I want a studio in spain cluster or France"], IC), ("Spain Cluster", "France Cluster"))
        self.assertEqual(communities.sub_areas_in(["anything"], IC), ())

    def test_their_words_name_a_pack(self):
        self.assertEqual([pack.name for pack in communities.named_in(["Do you have anything in Mudon?"], PACKS)], ["Mudon"])
        self.assertEqual([pack.name for pack in communities.named_in(["a villa in jumeirah village circle"], PACKS)], ["JVC"])
        self.assertEqual([pack.name for pack in communities.named_in(["عندكم شي في مدن؟"], PACKS)], ["Mudon"])
        # "ic" only as a word of its own; "music" names nothing.
        self.assertEqual(communities.named_in(["I love music"], PACKS), [])
        self.assertEqual([pack.name for pack in communities.named_in(["IC studio"], PACKS)], ["International City"])

    def test_for_turn_in_order(self):
        pack, why = communities.for_turn(words=["I need a studio"], listed=PACKS)
        self.assertEqual((pack.name, why), ("International City", communities.DEFAULTED))
        pack, why = communities.for_turn(words=["I need a studio"], lead={"community": "Mudon"}, listed=PACKS)
        self.assertEqual((pack.name, why), ("Mudon", communities.LEAD))
        pack, why = communities.for_turn(stored="JVC", words=["I need a studio"], lead={"community": "Mudon"}, listed=PACKS)
        self.assertEqual((pack.name, why), ("JVC", communities.STORED))
        # Their words move the chat to a pack named alone.
        pack, why = communities.for_turn(stored="International City", words=["do you have anything in Mudon?"], listed=PACKS)
        self.assertEqual((pack.name, why), ("Mudon", communities.WORDS))
        # A cluster of the stored pack beside another name keeps the stored pack ("I live in JVC, want Spain cluster").
        pack, why = communities.for_turn(stored="International City", words=["I live in JVC now, I want a studio in Spain cluster"], listed=PACKS)
        self.assertEqual((pack.name, why), ("International City", communities.STORED))
        # Two packs named: neither decides.
        pack, why = communities.for_turn(words=["Mudon or JVC?"], listed=PACKS)
        self.assertEqual((pack.name, why), ("International City", communities.DEFAULTED))
        # A stored name nobody knows any more falls back to the default.
        pack, why = communities.for_turn(stored="Atlantis", listed=PACKS)
        self.assertEqual((pack.name, why), ("International City", communities.DEFAULTED))


class SeedTests(TestCase):
    def test_the_migration_seeded_the_packs_and_packs_reads_them(self):
        names = set(LeadAiCommunity.objects.values_list("name", flat=True))
        self.assertIn("International City", names)
        self.assertIn("Mudon", names)
        self.assertEqual(len(names), len(communities.SEED))
        listed = communities.packs()
        self.assertEqual(listed[0].name, "International City")
        self.assertTrue(listed[0].shops)
        self.assertIsNotNone(listed[0].pk)
        # The table emptied: the seed's default still answers.
        LeadAiCommunity.objects.all().delete()
        listed = communities.packs()
        self.assertEqual([pack.name for pack in listed], ["International City"])
        self.assertIsNone(listed[0].pk)
        # An inactive pack is no pack.
        LeadAiCommunity.objects.create(name="Mudon", aliases=["mudon"], active=False)
        self.assertEqual([pack.name for pack in communities.packs()], ["International City"])


class InTheTurnTests(RentBase):
    def test_a_residential_turn_stores_the_chats_community_once(self):
        self.rent(clusters=["Spain"])
        message = self.inbound("How much is the rent?")
        self.turn(message, [res_answer("Studios in Spain Cluster are around AED 29,000–33,000 a year. Would you like to visit our office?", facts={"clusters": ["Spain"]})])
        self.assertEqual(self.state().community, "International City")
        # The next turn finds it stored and writes nothing new (the decision carries no community: the default pack).
        self.turn(self.inbound("ok"), [res_answer("Great. When would you like to visit?")])
        self.assertEqual(self.state().community, "International City")


class EndpointTests(Base):
    def test_the_communities_endpoint_lists_every_pack_with_its_live_units(self):
        from apps.leadai.models import LeadAiUnit

        LeadAiUnit.objects.create(source="pf", source_id="m1", community="Mudon", unit="villa", deal="sale", price=3_000_000, title="Villa")
        self.client.force_login(self.agent)
        response = self.client.get("/api/leadai/communities/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        by_name = {row["name"]: row for row in data["communities"]}
        self.assertEqual(by_name["Mudon"]["units_live"], 1)
        self.assertIsNone(by_name["JVC"]["units_live"])
        self.assertTrue(by_name["International City"]["shops"])
        self.assertIn("Spain Cluster", [area["name"] for area in by_name["International City"]["sub_areas"]])
        self.assertFalse(data["can_edit"])
        self.client.force_login(self.admin)
        self.assertTrue(self.client.get("/api/leadai/communities/").json()["can_edit"])
