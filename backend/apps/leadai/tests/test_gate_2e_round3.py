"""Batch 2e's real-model gate, round 3 (2026-10-17, on the server's build context): 570 of 574 runs passed (99.3%), the
model-written ones 301 of 304 (99.0%), but the gate's every-run rule failed on one money-or-policy scenario:
shops-unit-photos-1br-default #2. "Please share pictures of the 1 bedroom" was handed over as media_received with
"I'm AR Properties' virtual assistant — I can't share pictures here, ...", so no set went and a person's silence did.

residential.unasked_handover now takes media_received off too, but only over a photo request and only when the burst
holds no photo, video, document, location, contact card or unheard voice note of theirs (residential.received_media),
which a person must still see or hear; and over a photo request the model's "I can't share pictures" sentence goes with
it (refuses_media).
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import residential, schema
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

HONESTY_NO_PICTURES = (
    "I'm AR Properties' virtual assistant — I can't share pictures here, but our agent will show you the exact England "
    "Cluster one-bedroom apartment at the viewing."
)
# The round-3 run's answer (eval2e_round3.log, shops-unit-photos-1br-default #2).
PHOTOS_1BR_MEDIA = res_answer(f"{HONESTY_NO_PICTURES} I can offer you a slot today at 3:00 PM or 4:00 PM.", handover="media_received")
OLD_UNASKED = ("customer_asked_human", "unclear", "legal_visa_licence_contract", "price_or_details_insisted")


def normal(completion):
    return schema.normalize(completion.data, shops=True, residential=True)


class MediaReceivedOverAPhotoRequestTests(SimpleTestCase):
    def test_the_one_bedroom_set_goes_never_a_person_nobody_asked_for(self):
        run = run_eval("shops-unit-photos-1br-default", PHOTOS_1BR_MEDIA)
        self.assertEqual(run.failures, [])
        self.assertEqual(run.answer["unit_media"]["name"], "1BR - standard - a7group-1618 (default)")
        self.assertNotIn("can't share pictures", run.out)
        self.assertFalse((run.answer.get("handover") or {}).get("needed"))

    def test_it_fails_again_with_the_fix_off(self):
        with patch.object(residential, "UNASKED_HANDOVERS", OLD_UNASKED):
            self.assertTrue(run_eval("shops-unit-photos-1br-default", PHOTOS_1BR_MEDIA).failures)

    def test_the_handover_is_taken_off_and_the_refusal_goes_with_it(self):
        answer = normal(PHOTOS_1BR_MEDIA)
        taken = residential.unasked_handover(answer, ["Please share pictures of the 1 bedroom"], track="rent", unit="one_br")
        self.assertEqual(taken, "media_received")
        self.assertFalse(answer["handover"]["needed"])
        self.assertNotIn("can't share pictures", answer["reply"])

    def test_a_photo_of_theirs_keeps_the_handover(self):
        # Something they sent: a person must see it, whatever the caption asks.
        for item in (
            "[photo you cannot see; caption: Please share pictures of the 1 bedroom]",
            "[document you cannot see]",
            "[shared a location: Spain Cluster]",
            "[shared a contact card: Ahmed]",
            "[voice note could not be heard]",
            "[a message type we cannot open]",
        ):
            with self.subTest(item):
                answer = normal(PHOTOS_1BR_MEDIA)
                words = [item, "Please share pictures of the 1 bedroom"]
                self.assertEqual(residential.unasked_handover(answer, words, track="rent", unit="one_br"), "")
                self.assertTrue(answer["handover"]["needed"])
                self.assertEqual(answer["handover"]["reason"], "media_received")

    def test_no_photo_request_keeps_a_media_handover(self):
        answer = normal(res_answer("Thank you, our agent will reply here.", handover="media_received"))
        self.assertEqual(residential.unasked_handover(answer, ["What is the commission?"], track="rent", unit="one_br"), "")
        self.assertTrue(answer["handover"]["needed"])

    def test_received_media_reads_only_what_they_sent(self):
        self.assertTrue(residential.received_media(["[photos you cannot see]"]))
        self.assertTrue(residential.received_media(["[video you cannot see; caption: the street]"]))
        self.assertTrue(residential.received_media(["[voice note could not be heard]"]))
        self.assertFalse(residential.received_media(["Please share pictures of the 1 bedroom", "[tapped: Yes, still looking]"]))
        # A voice note a transcript heard is words like any other.
        self.assertFalse(residential.received_media(["[voice note] send me photos please"]))

    def test_refuses_media_reads_a_refusal_only(self):
        self.assertTrue(residential.refuses_media("I can't share pictures here, but our agent will show you the flat."))
        self.assertTrue(residential.refuses_media("We are unable to send photos on WhatsApp."))
        self.assertFalse(residential.refuses_media("Here are photos of the same type of one-bedroom apartment."))
        self.assertFalse(residential.refuses_media("I can share more pictures if you like."))
