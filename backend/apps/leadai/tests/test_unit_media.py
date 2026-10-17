"""Batch 2e slice E: the studio and one-bedroom photo sets (spec §4; board T96, Q36, D11).

The pick (the lead's own listing's set, else the unit's default; never another unit's), the six-language captions
(the same type of unit, never the exact one, no furniture), the rent track's media step (asked, a "Send pictures" tap,
or a unit and cluster confirmed by a direct customer; never to a broker, never over a line code writes, once a day),
the import from each set's set.json, the send (photos, the caption on the first, then one question), the timeline
note, the panel's routes, and a whole turn of the engine.

The guards' tests switch each guard off (unit_media.SAME_UNIT_ONLY, NEVER_TO_BROKERS, ONCE_A_DAY) to prove it is what
holds. Files are written under a throwaway MEDIA_ROOT; the gateway is a fake. The clock is test_assistant's.
"""

import datetime as dt
import json
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from apps.inbox.models import Message
from apps.leadai import shop_media, tasks, unit_media
from apps.leadai.models import LeadAiAlert, LeadAiChatState, LeadAiShopMedia, LeadAiTurn, LeadAiUnitMediaSet
from apps.leadai.tests.test_assistant import NOW, answer, fake_send_text
from apps.leadai.tests.test_shop_media import CLIENT, MediaBase, jpeg, png
from apps.leadai.tests.test_shops_playbook import ShopsBase, shop_answer

DUBAI = NOW.tzinfo
STUDIO_DEFAULT = "Studio - standard - a7group-1726 (default)"
STUDIO_1722 = "Studio - standard - a7group-1722"
ONE_BR_DEFAULT = "1BR - standard - a7group-1618 (default)"
# The library as sets.json holds it (D11), as plain data.
LIBRARY = [
    {"id": 1, "name": STUDIO_DEFAULT, "unit": "studio", "label": "standard", "default_for_unit": True, "for_listing_refs": ["a7group-1726"], "photo_count": 4},
    {"id": 2, "name": "Studio - standard - a7group-1713", "unit": "studio", "label": "standard", "default_for_unit": False, "for_listing_refs": ["a7group-1713", "a7group-1727"], "photo_count": 4},
    {"id": 3, "name": STUDIO_1722, "unit": "studio", "label": "standard", "default_for_unit": False, "for_listing_refs": ["a7group-1722"], "photo_count": 5},
    {"id": 6, "name": ONE_BR_DEFAULT, "unit": "one_br", "label": "standard", "default_for_unit": True, "for_listing_refs": ["a7group-1618"], "photo_count": 4},
    {"id": 7, "name": "1BR - standard - a7group-1856", "unit": "one_br", "label": "standard", "default_for_unit": False, "for_listing_refs": ["a7group-1855", "a7group-1856"], "photo_count": 4},
]


def name_of(item):
    return item["name"] if isinstance(item, dict) else item.name


def fresh_answer(reply="Sure! Here are the photos.", **facts):
    """A model answer as the step reads it (a copy: each test changes its own)."""
    data = json.loads(json.dumps(answer(reply, segment="residential_tenant").data))
    data["facts"].update(facts)
    return data


# The pick ------------------------------------------------------------------------------------------------------------


class PickTests(MediaBase):
    def test_the_leads_own_listing_set_else_the_units_default(self):
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "studio", "a7group-1722", NOW)), STUDIO_1722)
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "studio", "A7GROUP-1727", NOW)), "Studio - standard - a7group-1713")
        # An expired listing (no set of its own) and no ref at all: the unit's default.
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "studio", "a7group-1683", NOW)), STUDIO_DEFAULT)
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "one_br", "", NOW)), ONE_BR_DEFAULT)
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "one_br", "a7group-1856", NOW)), "1BR - standard - a7group-1856")
        # The unit not known yet (or a bigger home): nothing; the bot asks the unit first.
        for unit in ("", "two_plus", "villa"):
            self.assertIsNone(unit_media.choose(LIBRARY, unit, "a7group-1722", NOW))

    def test_never_the_other_units_set_even_when_the_lead_ref_names_it(self):
        # Real case: the lead enquired on the Greece K16 one-bedroom (a7group-1618) and now wants a studio.
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "studio", "a7group-1618", NOW)), STUDIO_DEFAULT)
        self.assertEqual(name_of(unit_media.choose(LIBRARY, "one_br", "a7group-1722", NOW)), ONE_BR_DEFAULT)
        # Guard off: the lead's ref would hand a studio customer the one-bedroom's photos.
        with patch.object(unit_media, "SAME_UNIT_ONLY", False):
            self.assertEqual(name_of(unit_media.choose(LIBRARY, "studio", "a7group-1618", NOW)), ONE_BR_DEFAULT)

    def test_a_stale_exact_set_is_passed_over_and_a_standard_set_never_goes_stale(self):
        old = NOW - dt.timedelta(days=200)
        sets = [
            {"id": 10, "name": "Exact 1722", "unit": "studio", "label": "exact", "for_listing_refs": ["a7group-1722"], "photo_count": 3, "verified_at": old, "available": True},
            {"id": 11, "name": "Matching 1722", "unit": "studio", "label": "matching", "for_listing_refs": ["a7group-1713"], "photo_count": 3, "verified_at": NOW - dt.timedelta(days=10)},
            {"id": 12, "name": "Exact gone", "unit": "studio", "label": "exact", "for_listing_refs": ["a7group-1726"], "photo_count": 3, "verified_at": NOW, "available": False},
            {"id": 13, "name": "Standard old", "unit": "studio", "label": "standard", "default_for_unit": True, "photo_count": 2, "verified_at": old},
            {"id": 14, "name": "Reference", "unit": "studio", "label": "reference", "for_listing_refs": ["a7group-1891"], "photo_count": 2},
            {"id": 15, "name": "No photos", "unit": "studio", "label": "standard", "for_listing_refs": ["a7group-1828"], "photo_count": 0},
        ]
        self.assertEqual(name_of(unit_media.choose(sets, "studio", "a7group-1722", NOW)), "Standard old")  # stale exact: the default
        self.assertEqual(name_of(unit_media.choose(sets, "studio", "a7group-1713", NOW)), "Matching 1722")  # fresh matching
        self.assertEqual(name_of(unit_media.choose(sets, "studio", "a7group-1726", NOW)), "Standard old")  # an exact unit gone
        self.assertEqual(name_of(unit_media.choose(sets, "studio", "a7group-1891", NOW)), "Standard old")  # reference: never sent
        self.assertEqual(name_of(unit_media.choose(sets, "studio", "a7group-1828", NOW)), "Standard old")  # nothing to send

    def test_pick_reads_the_database_with_photo_counts(self):
        default = LeadAiUnitMediaSet.objects.create(unit="studio", name=STUDIO_DEFAULT, default_for_unit=True, for_listing_refs=["a7group-1726"])
        own = LeadAiUnitMediaSet.objects.create(unit="studio", name=STUDIO_1722, for_listing_refs=["a7group-1722"])
        empty = LeadAiUnitMediaSet.objects.create(unit="studio", name="Empty", for_listing_refs=["a7group-1891"])
        for media_set, seed in ((default, 1), (own, 2)):
            self.photo(media_set, seed)
        self.assertEqual(unit_media.pick("studio", "a7group-1722").pk, own.pk)
        self.assertEqual(unit_media.pick("studio", "a7group-1891").pk, default.pk)  # its own set has no photo
        self.assertIsNone(unit_media.pick("one_br", "a7group-1722"))
        self.assertEqual(empty.photos.count(), 0)

    def photo(self, media_set, seed):
        row = LeadAiShopMedia(shop=media_set.unit, kind="photo", file_name=f"{seed}.jpg", mime_type="image/jpeg", size_bytes=10, sha256=f"{seed:064d}", order=seed, unit_set=media_set)
        from django.core.files.base import ContentFile

        row.file.save(f"t-{seed}.jpg", ContentFile(jpeg(seed)), save=False)
        row.save()
        return row


# The words -----------------------------------------------------------------------------------------------------------


class CaptionTests(MediaBase):
    LANGUAGES = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")

    def test_six_languages_the_same_type_never_the_exact_unit_never_furniture(self):
        self.assertEqual(
            unit_media.caption("studio", "en"),
            "These are photos of the same type of studio. Inside they are almost the same; the building can differ, and our agent "
            "will show you the exact unit at the viewing.",
        )
        self.assertEqual(
            unit_media.caption("one_br", "en"),
            "These are photos of the same type of one-bedroom apartment. Inside they are almost the same; the building can differ, "
            "and our agent will show you the exact unit at the viewing.",
        )
        for unit in ("studio", "one_br"):
            for language in self.LANGUAGES:
                with self.subTest(unit=unit, language=language):
                    text = unit_media.caption(unit, language)
                    self.assertTrue(text)
                    self.assertNotRegex(text.lower(), r"\bthis (?:unit|studio|apartment|flat)\b|furnish|furniture|available\b")
        self.assertEqual(unit_media.caption("studio", "fr"), unit_media.caption("studio", "en"))
        self.assertIn("استوديو", unit_media.caption("studio", "ar"))
        self.assertIn("ون بیڈروم", unit_media.caption("one_br", "ur"))

    def test_the_question_after_the_photos_and_the_no_media_line(self):
        slots = [NOW.replace(hour=16), NOW.replace(hour=18)]
        self.assertEqual(
            unit_media.follow_up("en", photos_sent=True, invite=True, slots=slots, now=NOW),
            "Would you like to visit and see the exact available option? I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?",
        )
        self.assertEqual(unit_media.follow_up("en", photos_sent=True, invite=True, slots=[], now=NOW), "Would you like to visit and see the exact available option?")
        self.assertEqual(unit_media.follow_up("en", photos_sent=True, questions="Do you prefer a balcony?", invite=False, now=NOW), "Do you prefer a balcony?")
        self.assertEqual(unit_media.follow_up("en", photos_sent=True, invite=False, now=NOW), "")
        self.assertEqual(
            unit_media.follow_up("en", photos_sent=False, invite=True, slots=slots, now=NOW),
            "I don't have approved pictures for this one yet, but we can show you in person. I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?",
        )
        for language in self.LANGUAGES:
            with self.subTest(language):
                self.assertTrue(unit_media.VISIT_QUESTION[language].rstrip().endswith(("?", "؟")))
                self.assertTrue(unit_media.NO_MEDIA[language])


class ReadingTests(MediaBase):
    def test_a_request_for_photos_in_their_words(self):
        for text in (
            "Can you send photos?", "send me pics of the studio", "video bhej do", "pics please", "photos?", "Please share pictures of the 1 bedroom",
            "ممكن ترسل صور الاستوديو؟", "تصاویر بھیج دیں", "फोटो भेजो", "Send Pictures", "Do you have photos of it?", "tasveer dikhao",
            "Thanks for the photos, can you send more?", "Send photos of the studio near the shops",
        ):
            with self.subTest(text):
                self.assertTrue(unit_media.asks_photos(text))
        for text in (
            "No need to send photos, I will come", "I will send my licence photo", "I need a shop for my photo studio", "ok",
            "photos nahi chahiye", "Thanks for the photos, they look nice and I like the kitchen", "", "send me photos of the shop",
            "shop ki video bhejo",
        ):
            with self.subTest(text):
                self.assertFalse(unit_media.asks_photos(text))

    def test_a_request_no_photo_answered_yet_still_stands(self):
        earlier = [("customer", "Can you send pictures?"), ("assistant", "Great! Is the studio for yourself, or are you checking for a client?")]
        self.assertTrue(unit_media.asked_before(earlier))
        answered = [*earlier, ("assistant", f"[sent a photo] {unit_media.caption('studio', 'en')}"), ("assistant", "[sent a photo]")]
        self.assertFalse(unit_media.asked_before(answered))
        long_ago = [("customer", "send photos"), *[("assistant", "ok") for _ in range(unit_media.PENDING_LINES)]]
        self.assertFalse(unit_media.asked_before(long_ago))
        # Answered by the no-media line (no set imported): never that line again on their next message.
        told = [*earlier, ("assistant", f"Sure! {unit_media.NO_MEDIA['ur_latin']} Main aap ke liye ...")]
        self.assertFalse(unit_media.asked_before(told))

    def test_the_triggers(self):
        recently = {"studio": NOW - dt.timedelta(hours=2)}
        self.assertEqual(unit_media.trigger(["send photos"], unit="studio", for_client=None, now=NOW), unit_media.ASKED)
        self.assertEqual(unit_media.trigger(["Spain cluster"], unit="studio", clusters=("Spain",), for_client=False, now=NOW), unit_media.CONFIRMED)
        # Who it is for not known yet, or no cluster: a confirmed unit is no trigger.
        self.assertEqual(unit_media.trigger(["Spain cluster"], unit="studio", clusters=("Spain",), for_client=None, now=NOW), "")
        self.assertEqual(unit_media.trigger(["ok"], unit="studio", clusters=(), for_client=False, now=NOW), "")
        # Their unit's set went to the chat before: never pushed again; asked again after a day, it goes.
        self.assertEqual(unit_media.trigger(["ok"], unit="studio", clusters=("Spain",), for_client=False, sent=recently, now=NOW), "")
        self.assertEqual(unit_media.trigger(["send photos"], unit="studio", sent={"studio": NOW - dt.timedelta(days=2)}, now=NOW), unit_media.ASKED)
        # Another unit's set went: this unit's is still due (studio to one-bedroom, the brief's Part 11).
        self.assertEqual(unit_media.trigger(["1BR in Spain"], unit="one_br", clusters=("Spain",), for_client=False, sent=recently, now=NOW), unit_media.CONFIRMED)
        self.assertEqual(unit_media.trigger(["send photos"], unit="", now=NOW), "")

    def test_never_to_a_broker(self):
        words = ["Send photos, my client wants a studio"]
        self.assertEqual(unit_media.trigger(words, unit="studio", for_client=True, now=NOW), "")
        with patch.object(unit_media, "NEVER_TO_BROKERS", False):  # guard off: the broker would get the photos
            self.assertEqual(unit_media.trigger(words, unit="studio", for_client=True, now=NOW), unit_media.ASKED)

    def test_once_a_day_whatever_they_ask(self):
        sent = {"studio": NOW - dt.timedelta(hours=1)}
        self.assertEqual(unit_media.trigger(["send more photos"], unit="studio", sent=sent, now=NOW), "")
        with patch.object(unit_media, "ONCE_A_DAY", False):  # guard off: the same photos again an hour later
            self.assertEqual(unit_media.trigger(["send more photos"], unit="studio", sent=sent, now=NOW), unit_media.ASKED)


# The step (pure, as the engine and the eval run it) -------------------------------------------------------------------


class SettleTests(MediaBase):
    def settle(self, data, words=("Can you send photos?",), **extra):
        values = {
            "track": "rent", "unit": "studio", "clusters": ("Spain",), "words": list(words), "known": {"for_client": False},
            "library": LIBRARY, "listing_ref": "a7group-1722", "sent": {}, "now": NOW,
            "slots": [NOW.replace(hour=16), NOW.replace(hour=18)],
        }
        values.update(extra)
        return unit_media.settle(data, **values)

    def test_statements_before_the_photos_and_the_question_after_them(self):
        data = fresh_answer("Sure! Here are the photos of the Spain Cluster studio. Do you prefer a balcony?")
        self.assertEqual(self.settle(data), unit_media.ASKED)
        step = data[unit_media.STEP]
        self.assertEqual((step["name"], step["unit"], step["photos"], step["label"]), (STUDIO_1722, "studio", 5, "standard"))
        self.assertEqual(step["before"], "Sure! Here are the photos of the Spain Cluster studio.")
        self.assertEqual(step["after"], "Do you prefer a balcony?")
        self.assertFalse(step["invite"])  # their question goes after the photos, so no slots are added
        self.assertEqual(step["slots"], [])
        self.assertFalse(data["share_office_location"])
        # No question of the model's: code's visit question with the two slots goes after the photos.
        data = fresh_answer("Sure!")
        self.settle(data)
        self.assertTrue(data[unit_media.STEP]["invite"])
        self.assertEqual(len(data[unit_media.STEP]["slots"]), 2)

    def test_a_sentence_that_denies_photos_never_goes_with_them(self):
        data = fresh_answer("Sorry, I don't have photos right now. Our agent can show you the apartments.")
        self.settle(data)
        self.assertEqual(data[unit_media.STEP]["before"], "Our agent can show you the apartments.")

    def test_only_on_the_rent_track_with_a_known_unit(self):
        for track, unit in (("shop", "studio"), ("sale", "studio"), ("other", "studio"), ("", "studio"), ("rent", ""), ("rent", "two_plus")):
            with self.subTest(track=track, unit=unit):
                data = fresh_answer()
                self.assertEqual(self.settle(data, track=track, unit=unit), "")
                self.assertNotIn(unit_media.STEP, data)

    def test_never_over_a_line_code_writes_a_booking_or_a_handover(self):
        cases = {
            "a fixed line": ({"converted": "for_whom"}, {}),
            "the owner's line": ({"not_a_shop": {"kind": "home"}}, {}),
            "a shops step": ({"shop_step": {"kind": "list"}}, {}),
            "an opt-out": ({"opt_out": "stop_all"}, {}),
            "a handover": ({"handover": {"needed": True, "reason": "customer_asked_human"}}, {}),
            "a booking": ({}, {"when": NOW + dt.timedelta(hours=3)}),
            "a time to refuse": ({}, {"still_invalid": True}),
            "a person holds the chat": ({}, {"quiet": True}),
        }
        for label, (fields, extra) in cases.items():
            with self.subTest(label):
                data = fresh_answer()
                data.update(fields)
                self.assertEqual(self.settle(data, **extra), "")
                self.assertNotIn(unit_media.STEP, data)

    def test_a_booked_customer_asking_gets_the_photos_with_no_invitation_and_nothing_unasked(self):
        booked = object()
        data = fresh_answer("Sure!")
        self.assertEqual(self.settle(data, appointment=booked), unit_media.ASKED)
        self.assertFalse(data[unit_media.STEP]["invite"])
        data = fresh_answer("Perfect, the Spain Cluster studio.")
        self.assertEqual(self.settle(data, words=["Spain cluster"], appointment=booked), "")
        # Nor in a turn that says nothing (an "ok" the model leaves unanswered): unasked photos come with words.
        data = fresh_answer("")
        data["send"] = False
        self.assertEqual(self.settle(data, words=["ok"]), "")
        self.assertEqual(self.settle(data, words=["send photos"]), unit_media.ASKED)  # asked for, they go all the same

    def test_no_set_imported_a_request_gets_the_no_media_line_and_a_confirmed_unit_nothing(self):
        data = fresh_answer("Sure!")
        self.assertEqual(self.settle(data, library=[]), unit_media.ASKED)
        self.assertIsNone(data[unit_media.STEP]["set"])
        self.assertEqual(
            unit_media.text_without_set(data[unit_media.STEP], "en", NOW),
            "Sure! I don't have approved pictures for this one yet, but we can show you in person. I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?",
        )
        data = fresh_answer("Perfect, the Spain Cluster studio.")
        self.assertEqual(self.settle(data, words=["Spain cluster"], library=[]), "")

    def test_the_answers_own_facts_count_and_its_empty_ones_say_nothing(self):
        # The model recorded "for myself" this turn: a confirmed unit and cluster are a trigger now.
        data = fresh_answer("Perfect.", for_client=False)
        self.assertEqual(self.settle(data, words=["Spain, for myself"], known={}), unit_media.CONFIRMED)
        # Its unset for_client (None) never hides what the chat knew.
        data = fresh_answer("Perfect.")
        self.assertEqual(self.settle(data, words=["Spain cluster"], known={"for_client": False}), unit_media.CONFIRMED)

    def test_the_library_the_ref_and_the_history_are_read_only_when_a_step_is_due(self):
        calls = []

        def reader(value, name):
            def read():
                calls.append(name)
                return value

            return read

        data = fresh_answer("Sure.")
        self.settle(data, words=["ok thanks"], known={"for_client": None}, library=reader(LIBRARY, "library"), listing_ref=reader("", "ref"), sent=reader({}, "sent"))
        self.assertEqual(calls, [])
        self.settle(data, library=reader(LIBRARY, "library"), listing_ref=reader("a7group-1722", "ref"), sent=reader({}, "sent"))
        self.assertEqual(sorted(calls), ["library", "ref", "sent"])


# The import ------------------------------------------------------------------------------------------------------------


class ImportTests(MediaBase):
    def library_folder(self, **changes) -> str:
        """A copy of the library's shape: three sets, each with its set.json and photos (01.jpg ...)."""
        root = tempfile.mkdtemp(prefix="leadai-sets-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        sets = {
            STUDIO_DEFAULT: {"unit": "studio", "label": "standard", "cluster": "", "default_for_unit": True, "for_listing_refs": ["a7group-1726"], "seed": 10, "photos": 4},
            STUDIO_1722: {"unit": "studio", "label": "standard", "cluster": "", "default_for_unit": False, "for_listing_refs": ["a7group-1722"], "seed": 20, "photos": 5},
            ONE_BR_DEFAULT: {"unit": "one_br", "label": "standard", "cluster": "", "default_for_unit": True, "for_listing_refs": ["a7group-1618"], "seed": 30, "photos": 4},
        }
        for name, extra in changes.items():
            sets[name] = {**sets.get(name, {}), **extra}
        for name, spec in sets.items():
            folder = os.path.join(root, "Residential sets", name)
            os.makedirs(folder)
            photos = []
            for index in range(spec["photos"]):
                file_name = f"{index + 1:02d}.jpg"
                with open(os.path.join(folder, file_name), "wb") as handle:
                    handle.write(spec.get("bytes", {}).get(index, jpeg(spec["seed"] + index)))
                photos.append({"file": file_name, "from": "listing/0x.jpg", "room": "main room", "bytes": 10})
            data = {
                "unit": spec["unit"], "label": spec["label"], "cluster": spec["cluster"], "default_for_unit": spec["default_for_unit"],
                "for_listing_refs": spec["for_listing_refs"], "photos": spec.get("photo_list", photos), "video": spec.get("video"),
                "note": "a7 listing", "rule": "Q36", "built_on": "2026-10-16",
            }
            with open(os.path.join(folder, "set.json"), "w", encoding="utf-8") as handle:
                json.dump(data, handle)
        return root

    def test_every_set_goes_in_from_its_set_json_and_twice_is_once(self):
        root = self.library_folder()
        lines = unit_media.import_directory(root)
        self.assertEqual(
            sorted(lines),
            sorted([
                f"added set '{ONE_BR_DEFAULT}' (one-bedroom apartment, 4 photos, the unit's default)",
                f"added set '{STUDIO_1722}' (studio, 5 photos)",
                f"added set '{STUDIO_DEFAULT}' (studio, 4 photos, the unit's default)",
            ]),
        )
        own = LeadAiUnitMediaSet.objects.get(name=STUDIO_1722)
        self.assertEqual((own.unit, own.label, own.default_for_unit, own.for_listing_refs), ("studio", "standard", False, ["a7group-1722"]))
        self.assertEqual(own.verified_at, dt.datetime(2026, 10, 16, tzinfo=DUBAI))
        photos = list(own.photos.order_by("order"))
        self.assertEqual([(row.file_name, row.order, row.shop, row.kind) for row in photos], [(f"{i:02d}.jpg", i, "studio", "photo") for i in range(1, 6)])
        self.assertTrue(all(self.stored(row) for row in photos))
        again = unit_media.import_directory(root)
        self.assertTrue(all(line.startswith("already there") for line in again), again)
        self.assertEqual(LeadAiShopMedia.objects.count(), 13)
        # The shop library never shows a set's photos.
        self.assertEqual(shop_media.rows_for("type_1"), [])

    def test_the_whole_types_shops_folder_and_the_command(self):
        root = self.library_folder()
        os.makedirs(os.path.join(root, "Type 1 400 550sqft"))
        with open(os.path.join(root, "Type 1 400 550sqft", "a.jpg"), "wb") as handle:
            handle.write(jpeg(99))
        out = StringIO()
        call_command("leadai_media_import", root, "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn(f"would add set '{STUDIO_DEFAULT}' (studio, 4 photos, the unit's default)", text)
        self.assertIn("would add Type 1 / a.jpg", text)
        self.assertNotIn("skipped folder 'Residential sets'", text)
        self.assertTrue(text.rstrip().endswith("sets: would add or update 3; 0 already there; 0 refused; nothing stored"), text)
        self.assertFalse(LeadAiUnitMediaSet.objects.exists())
        out = StringIO()
        call_command("leadai_media_import", os.path.join(root, "Residential sets"), stdout=out)
        self.assertTrue(out.getvalue().rstrip().endswith("sets: added or updated 3; 0 already there; 0 refused"), out.getvalue())
        self.assertEqual(LeadAiUnitMediaSet.objects.count(), 3)

    def test_what_the_import_refuses_and_a_refused_set_leaves_nothing(self):
        cases = {
            "label exact (Q36)": ({"label": "exact"}, "every set is the same type of unit, 'standard'"),
            "a ref not shaped a7group-NNNN": ({"for_listing_refs": ["1722"]}, "is not shaped a7group-NNNN"),
            "six photos": ({"photos": 6}, "6 photos: a set takes at most 5"),
            "not an image": ({"bytes": {1: b"not an image"}}, "only an MP4 video (H.264) or a JPEG or PNG photo"),
            "a unit that is no studio or 1BR": ({"unit": "two_plus"}, "a set is a studio or a one_br"),
            "a file of another folder": ({"photo_list": [{"file": "../x.jpg"}]}, "is not a file of this folder"),
            "the same photo twice": ({"bytes": {1: jpeg(20)}}, "the same photo twice in the set"),
            "a video listed": ({"video": "tour.mp4"}, "tour.mp4: cannot read it"),
        }
        for label, (change, reason) in cases.items():
            with self.subTest(label):
                root = self.library_folder(**{STUDIO_1722: change})
                lines = unit_media.import_directory(root)
                refused = [line for line in lines if line.startswith(f"refused set '{STUDIO_1722}'")]
                self.assertEqual(len(refused), 1, lines)
                self.assertIn(reason, refused[0])
                self.assertFalse(LeadAiUnitMediaSet.objects.filter(name=STUDIO_1722).exists())
                LeadAiShopMedia.objects.all().delete()
                LeadAiUnitMediaSet.objects.all().delete()

    def test_a_second_default_one_ref_in_two_sets_and_one_photo_in_two_sets_are_refused(self):
        root = self.library_folder(**{STUDIO_1722: {"default_for_unit": True}})
        lines = unit_media.import_directory(root)
        self.assertTrue(any(line.startswith(f"refused set '{STUDIO_DEFAULT}': a second default for studio") or line.startswith(f"refused set '{STUDIO_1722}': a second default for studio") for line in lines), lines)
        self.assertEqual(LeadAiUnitMediaSet.objects.filter(unit="studio", default_for_unit=True).count(), 1)
        LeadAiShopMedia.objects.all().delete()
        LeadAiUnitMediaSet.objects.all().delete()
        root = self.library_folder(**{STUDIO_1722: {"for_listing_refs": ["a7group-1722", "a7group-1726"]}})
        lines = unit_media.import_directory(root)
        self.assertTrue(any("listing ref a7group-1726 is in set" in line for line in lines), lines)
        LeadAiShopMedia.objects.all().delete()
        LeadAiUnitMediaSet.objects.all().delete()
        # One photo in two sets of a unit: in this run (the set read first keeps it), or against the library.
        root = self.library_folder(**{STUDIO_DEFAULT: {"bytes": {0: jpeg(20)}}})  # 1722's first photo, and 1722 comes first
        lines = unit_media.import_directory(root)
        self.assertIn(f"refused set '{STUDIO_DEFAULT}': 01.jpg: the same photo is in '{STUDIO_1722}' already.", lines)
        LeadAiShopMedia.objects.all().delete()
        LeadAiUnitMediaSet.objects.all().delete()
        unit_media.import_directory(self.library_folder())
        root = self.library_folder(**{STUDIO_1722: {"bytes": {0: jpeg(10)}}})  # the default set's first photo
        lines = unit_media.import_directory(root)
        self.assertIn(f"refused set '{STUDIO_1722}': 01.jpg: the same photo is in '{STUDIO_DEFAULT}' already.", lines)
        self.assertEqual(LeadAiUnitMediaSet.objects.get(name=STUDIO_1722).photos.count(), 5)  # the library's copy stays as it was

    def test_a_default_handed_from_one_set_to_another_in_one_run(self):
        unit_media.import_directory(self.library_folder())
        root = self.library_folder(**{STUDIO_DEFAULT: {"default_for_unit": False}, STUDIO_1722: {"default_for_unit": True}})
        lines = unit_media.import_directory(root)
        self.assertFalse([line for line in lines if line.startswith("refused")], lines)
        self.assertEqual(LeadAiUnitMediaSet.objects.get(unit="studio", default_for_unit=True).name, STUDIO_1722)

    def test_a_set_already_there_is_brought_to_its_set_json(self):
        unit_media.import_directory(self.library_folder())
        before = {row.sha256 for row in LeadAiUnitMediaSet.objects.get(name=STUDIO_DEFAULT).photos.all()}
        # Two photos now, a new one first, and a listing ref more.
        root = self.library_folder(**{STUDIO_DEFAULT: {"photos": 2, "bytes": {0: jpeg(77)}, "for_listing_refs": ["a7group-1726", "a7group-1732"]}})
        lines = unit_media.import_directory(root, dry_run=True)
        self.assertIn(f"would update set '{STUDIO_DEFAULT}' (studio, 2 photos, the unit's default)", lines)
        lines = unit_media.import_directory(root)
        self.assertIn(f"updated set '{STUDIO_DEFAULT}' (studio, 2 photos, the unit's default)", lines)
        media_set = LeadAiUnitMediaSet.objects.get(name=STUDIO_DEFAULT)
        photos = list(media_set.photos.order_by("order"))
        self.assertEqual([row.order for row in photos], [1, 2])
        self.assertNotIn(photos[0].sha256, before)
        self.assertIn(photos[1].sha256, before)
        self.assertEqual(media_set.for_listing_refs, ["a7group-1726", "a7group-1732"])

    def test_a_dry_run_stores_nothing(self):
        lines = unit_media.import_directory(self.library_folder(), dry_run=True)
        self.assertEqual(sum(line.startswith("would add set") for line in lines), 3)
        self.assertFalse(LeadAiUnitMediaSet.objects.exists())
        self.assertEqual(os.listdir(self.media_root), [])


# Sending ----------------------------------------------------------------------------------------------------------------


class SendTests(MediaBase):
    def setUp(self):
        super().setUp()
        for target in ("apps.inbox.events.publish_message", "apps.inbox.events.publish_status", "apps.inbox.services.publish_message"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        for module in (shop_media, unit_media):
            patcher = patch.object(module, "SEND_PAUSE", 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sent = []
        self.wamid = 0
        self.note = patch("apps.leadai.tasks.record_crm_note.delay")
        self.note_delay = self.note.start()
        self.addCleanup(self.note.stop)
        unit_media.import_directory(ImportTests.library_folder(self))
        self.media_set = LeadAiUnitMediaSet.objects.get(name=STUDIO_1722)

    def gateway(self, *, refuse=()):
        names = {}

        def upload(client, phone_number_id, file_obj, filename, mime_type):
            names[f"media-{len(names) + 1}"] = filename
            return f"media-{len(names)}"

        def send_media(client, phone_number_id, to, kind, media_id, caption=None, filename=None):
            from apps.gateway.client import AlotsError

            if names.get(media_id) in refuse:
                raise AlotsError("(#131052) could not send", status_code=400)
            self.sent.append((kind, names.get(media_id), caption))
            self.wamid += 1
            return {"messages": [{"id": f"wamid.u{self.wamid}"}]}

        return patch.multiple(CLIENT, upload_media=upload, send_media=send_media)

    def test_the_photos_the_caption_on_the_first_then_the_visit_question_and_the_note(self):
        with self.gateway(), patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
            result = unit_media.send_set(self.conversation.pk, self.media_set.pk, turn_id=51, language="en", invite=True)
        self.assertEqual((result["files"], result["skipped"], result["stopped"]), (5, [], ""))
        self.assertEqual([item[0] for item in self.sent], ["image"] * 5)
        self.assertEqual(self.sent[0][2], unit_media.caption("studio", "en"))
        self.assertTrue(all(not item[2] for item in self.sent[1:]))
        rows = list(Message.objects.filter(conversation=self.conversation, payload__turn=51).order_by("pk"))
        self.assertEqual([row.kind for row in rows], ["image"] * 5 + ["text"])
        self.assertTrue(all(row.payload["unit_set"] == self.media_set.pk and row.payload["unit"] == "studio" for row in rows[:5]))
        self.assertTrue(rows[5].body.startswith("Would you like to visit and see the exact available option? I can hold a slot for you today at "))
        self.assertEqual(rows[5].payload["unit_follow_up"], self.media_set.pk)
        self.note_delay.assert_called_once()
        conversation_id, kind, lines = self.note_delay.call_args.args
        self.assertEqual((conversation_id, kind), (self.conversation.pk, "photos sent"))
        self.assertIn(f'Sent 5 photos of the same type of studio, set "{STUDIO_1722}".', lines[0])
        self.assertIn("the same type of unit, never the exact one (Q36)", lines[1])
        self.assertEqual(unit_media.sent_units(self.conversation), {"studio": rows[4].created_at})  # when its set last went

    def test_the_models_question_goes_after_the_photos_and_twice_sends_nothing_twice(self):
        with self.gateway(), patch("apps.inbox.services.send_text", side_effect=fake_send_text):
            unit_media.send_set(self.conversation.pk, self.media_set.pk, turn_id=52, language="ar", questions="Do you prefer a balcony?")
            again = unit_media.send_set(self.conversation.pk, self.media_set.pk, turn_id=52, language="ar", questions="Do you prefer a balcony?")
        self.assertEqual(self.sent[0][2], unit_media.caption("studio", "ar"))
        self.assertEqual((again["files"], again["stopped"]), (0, "the question went out already"))
        texts = list(Message.objects.filter(conversation=self.conversation, payload__turn=52, kind="text").values_list("body", flat=True))
        self.assertEqual(texts, ["Do you prefer a balcony?"])

    def test_no_photo_delivered_gets_the_no_media_line(self):
        refused = {row.file_name for row in unit_media.photos_of(self.media_set)}
        with self.gateway(refuse=refused), patch("apps.inbox.services.send_text", side_effect=fake_send_text):
            result = unit_media.send_set(self.conversation.pk, self.media_set.pk, turn_id=53, invite=True)
        self.assertEqual((result["files"], len(result["skipped"])), (0, 5))
        follow = Message.objects.get(conversation=self.conversation, payload__turn=53, kind="text")
        self.assertTrue(follow.body.startswith("I don't have approved pictures for this one yet, but we can show you in person. I can hold a slot"))
        self.note_delay.assert_not_called()

    def test_nothing_goes_once_the_chat_is_not_the_assistants(self):
        state = LeadAiChatState.for_conversation(self.conversation)
        LeadAiChatState.objects.filter(pk=state.pk).update(paused_at=NOW)
        with self.gateway():
            result = unit_media.send_set(self.conversation.pk, self.media_set.pk, turn_id=54)
        self.assertEqual((result["stopped"], self.sent), ("stopped or paused", []))

    def test_the_task_tells_the_agents_when_it_breaks(self):
        with patch.object(unit_media, "send_set", side_effect=RuntimeError("boom")):
            tasks.send_unit_media(self.conversation.pk, self.media_set.pk, 55, "en")
        alert = LeadAiAlert.objects.get(kind="send_failed")
        self.assertEqual(alert.title, "Lead AI could not send the apartment photos")


# The panel's routes ------------------------------------------------------------------------------------------------------


class ApiTests(MediaBase):
    def test_every_agent_lists_the_sets_and_opens_a_photo_and_the_shop_library_keeps_out(self):
        unit_media.import_directory(ImportTests.library_folder(self))
        self.client.force_login(self.agent)
        data = self.client.get("/api/leadai/unit-media/").json()
        self.assertFalse(data["can_edit"])
        self.assertEqual([group["unit"] for group in data["units"]], ["studio", "one_br"])
        studio = data["units"][0]["sets"]
        self.assertEqual([item["name"] for item in studio], [STUDIO_DEFAULT, STUDIO_1722])  # the default first
        first = studio[0]
        self.assertEqual((first["label"], first["default_for_unit"], first["for_listing_refs"], first["sendable"]), ("standard", True, ["a7group-1726"], True))
        self.assertEqual(first["verified_at"][:10], "2026-10-16")
        self.assertEqual(len(first["files"]), 4)
        self.assertEqual(data["limits"]["photos"], 5)
        self.assertEqual(data["captions"]["studio"], unit_media.caption("studio", "en"))
        response = self.client.get(first["files"][0]["url"])
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/jpeg"))
        # A set's photo is never the shop library's: not listed, not opened, replaced or deleted through its routes.
        row = LeadAiShopMedia.objects.filter(unit_set__isnull=False).first()
        shops = self.client.get("/api/leadai/shop-media/").json()
        self.assertEqual([group["shop"] for group in shops["shops"]], ["type_1", "type_2", "type_3", "office"])
        self.assertEqual(self.client.get(f"/api/leadai/shop-media/{row.pk}/file/").status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.delete(f"/api/leadai/shop-media/{row.pk}/").status_code, 404)
        self.assertEqual(self.client.post("/api/leadai/shop-media/", {"shop": "studio", "file": self.upload()}).status_code, 400)
        shop_row, _ = shop_media.add("type_1", "a.jpg", png(4))
        self.assertEqual(self.client.get(f"/api/leadai/unit-media/{shop_row.pk}/file/").status_code, 404)
        self.client.logout()
        self.assertIn(self.client.get("/api/leadai/unit-media/").status_code, (401, 403))

    def upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile("a.jpg", jpeg(5))


# A whole turn of the engine ----------------------------------------------------------------------------------------------


class EngineTurnTests(ShopsBase):
    """A rent chat of a shops campaign (test_shops_playbook's lead 555), as 2e keeps it: code's track and unit, and 2d's
    facts.need beside them; the lead context read already (a Bayut lead on a7group-1722)."""

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="leadai-media-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        unit_media.import_directory(ImportTests.library_folder(self))
        self.set_state(
            track="rent", unit="studio", language="en",
            facts={"need": "home", "wanted": "a studio", "for_client": False, "property_type": "studio", "intent": "rent"},
            lead_context={"source": "Bayut", "listing_ref": "a7group-1722", "unit": "studio", "cluster": "Spain", "deal": "rent"},
            lead_context_at=NOW - dt.timedelta(hours=1), lead_info_at=NOW - dt.timedelta(hours=1),
        )
        self.ours("Perfect, the Spain Cluster studio. Do you prefer a balcony, and when are you planning to move?", minutes_ago=5)

    def run_turn(self, words, reply="Sure! Here are the photos.", **facts):
        message = self.inbound(words)
        with patch("apps.leadai.tasks.send_unit_media.delay") as queued:
            outcome, _, _, _ = self.turn(message, [shop_answer(reply, segment="residential_tenant", facts=facts)])
        return message, outcome, queued

    def test_photos_asked_for_queue_the_leads_own_set_after_the_models_words(self):
        message, outcome, queued = self.run_turn("Can you send photos first?")
        self.assertEqual(outcome.reason, f"unit photos queued ({STUDIO_1722})")
        media_set = LeadAiUnitMediaSet.objects.get(name=STUDIO_1722)
        turn = LeadAiTurn.objects.get(inbound=message)
        queued.assert_called_once_with(self.conversation.pk, media_set.pk, turn.pk, "en", "", True)
        words = Message.objects.filter(conversation=self.conversation, direction="out", payload__turn=turn.pk)
        self.assertEqual([row.body for row in words], ["Sure! Here are the photos."])
        self.assertEqual(turn.actions["unit_media"], {"trigger": "asked", "unit": "studio", "set": media_set.pk, "name": STUDIO_1722, "photos": 5, "invite": True})
        self.assertEqual(self.state().invites, 1)  # the question after the photos offers two slots

    def test_with_no_set_imported_the_no_media_line_goes_as_the_reply(self):
        LeadAiShopMedia.objects.all().delete()
        LeadAiUnitMediaSet.objects.all().delete()
        message, outcome, queued = self.run_turn("Do you have photos of it?", reply="Sure!")
        queued.assert_not_called()
        self.assertTrue(
            self.body(outcome).startswith("Sure! I don't have approved pictures for this one yet, but we can show you in person. I can hold a slot"),
            self.body(outcome),
        )
        self.assertEqual(self.actions(message)["unit_media"]["trigger"], "asked")

    def test_a_broker_gets_no_set(self):
        state = LeadAiChatState.for_conversation(self.conversation)
        self.set_state(facts={**state.facts, "for_client": True})
        message, outcome, queued = self.run_turn("Send photos of the studio for my client", reply="Thank you.")
        queued.assert_not_called()
        self.assertNotIn("unit_media", self.actions(message))

    def test_a_shop_chat_gets_the_shop_flow_never_a_set(self):
        self.set_state(track="shop", unit="", facts={"for_client": False, "property_type": "shop", "business_activity": "mobile phones"})
        message, outcome, queued = self.run_turn("send photos please", reply="Sure.")
        queued.assert_not_called()
        self.assertNotIn("unit_media", self.actions(message))

    def test_a_direct_customer_confirming_the_cluster_gets_the_set_with_the_models_question_after_it(self):
        self.set_state(lead_context={})
        # (Our last message said "Perfect, the Spain Cluster studio." already: the repeat guard keeps it from going twice.)
        message, outcome, queued = self.run_turn("Spain cluster", reply="Great choice. Do you prefer a balcony?")
        default = LeadAiUnitMediaSet.objects.get(name=STUDIO_DEFAULT)
        turn = LeadAiTurn.objects.get(inbound=message)
        queued.assert_called_once_with(self.conversation.pk, default.pk, turn.pk, "en", "Do you prefer a balcony?", False)
        self.assertEqual(turn.actions["unit_media"]["trigger"], "confirmed")
        self.assertEqual(self.body(outcome), "Great choice.")
