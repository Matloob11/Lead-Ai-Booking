"""Batch 2b: the shops media library (board T30), its import, its admin API, and the sends
it feeds (T31 the shop types list, T32 a type's video, photos and detail card).

Files are checked by their bytes. The gateway is a fake; files are written under a
throwaway MEDIA_ROOT, removed after each test. The clock is test_assistant's (Monday
12 October 2026, 14:00 Dubai).
"""

import datetime as dt
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.catalog.models import WabaNumber
from apps.gateway.client import AlotsError
from apps.inbox.models import MediaAsset, Message
from apps.leadai import shop_media, tasks
from apps.leadai.assistant import shop_flow
from apps.leadai.models import LeadAiAlert, LeadAiChatState, LeadAiShopMedia, LeadAiShopMediaUpload
from apps.leadai.tests.test_assistant import NOW, Base

CLIENT = "apps.gateway.client.AlotsClient"


def box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def mp4(*codecs, pad: int = 0) -> bytes:
    """A minimal MP4: ftyp, then one trak per codec (moov > trak > mdia > minf > stbl > stsd > entry)."""
    traks = b""
    for codec in codecs:
        entry = box(codec.encode("latin-1"), b"\x00" * 8)
        stsd = box(b"stsd", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + entry)
        # A track header first, as in a real file: the walk skips it.
        traks += box(b"trak", box(b"tkhd", b"\x00" * 12) + box(b"mdia", box(b"minf", box(b"stbl", stsd))))
    return box(b"ftyp", b"isom\x00\x00\x02\x00isomavc1") + box(b"moov", traks) + b"\x00" * pad


def jpeg(seed: int = 0, size: int = 200) -> bytes:
    return b"\xff\xd8\xff\xe0" + bytes([seed % 256]) * size


def png(seed: int = 0) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + bytes([seed % 256]) * 100


MB = 1024 * 1024


class MediaBase(Base):
    """A throwaway MEDIA_ROOT, removed after the test."""

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="leadai-media-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)

    def stored(self, row) -> bool:
        return os.path.exists(os.path.join(self.media_root, row.file.name))


# Checking a file by its bytes ------------------------------------------------------------------


class CheckFileTests(MediaBase):
    def test_an_h264_mp4_is_a_video_and_a_jpeg_or_png_a_photo(self):
        self.assertEqual(shop_media.check_file("tour.mp4", mp4("avc1", "mp4a")), ("video", "video/mp4", "mp4"))
        self.assertEqual(shop_media.check_file("tour.mp4", mp4("avc1")), ("video", "video/mp4", "mp4"))  # no sound is fine
        self.assertEqual(shop_media.check_file("a.jpg", jpeg()), ("photo", "image/jpeg", "jpeg"))
        self.assertEqual(shop_media.check_file("a.png", png()), ("photo", "image/png", "png"))
        # The bytes decide, never the name.
        self.assertEqual(shop_media.check_file("photo.jpg", mp4("avc1"))[0], "video")
        self.assertEqual(shop_media.check_file("video.mp4", jpeg())[0], "photo")

    def test_what_whatsapp_cannot_play_or_take_is_refused_with_the_reason(self):
        cases = {
            "hevc.mp4": (mp4("hvc1", "mp4a"), "must be H.264"),
            "both.mp4": (mp4("avc1", "hvc1"), "must be H.264"),
            "opus.mp4": (mp4("avc1", "Opus"), "sound must be AAC"),
            "empty.mp4": (box(b"ftyp", b"isom") + b"\x00" * 20, "no readable video track"),
            "big.mp4": (mp4("avc1", pad=16 * MB), "at most 16 MB"),
            "big.jpg": (jpeg(size=5 * MB + 1), "at most 5 MB"),
            "doc.pdf": (b"%PDF-1.7 hello", "only an MP4 video"),
            "anim.gif": (b"GIF89a" + b"\x00" * 50, "only an MP4 video"),
            "nothing.jpg": (b"", "the file is empty"),
        }
        for name, (data, reason) in cases.items():
            with self.subTest(name), self.assertRaises(shop_media.MediaRejected) as raised:
                shop_media.check_file(name, data)
            self.assertIn(reason, str(raised.exception))
            self.assertTrue(str(raised.exception).startswith(name))
        with self.assertRaises(shop_media.MediaRejected) as raised:
            shop_media.check_file("tour.mp4", mp4("avc1"), "office")
        self.assertIn("office takes one photo", str(raised.exception))

    def test_a_name_from_a_computer_is_cut_to_its_last_part_and_cleaned(self):
        self.assertEqual(shop_media.clean_name("C:\\Users\\x\\Type 1\\shop front.jpg"), "shop front.jpg")
        self.assertEqual(shop_media.clean_name("../../etc/pass\x00wd\n.jpg"), "passwd.jpg")
        self.assertEqual(shop_media.clean_name(""), "file")
        self.assertEqual(len(shop_media.clean_name("x" * 400)), shop_media.NAME_MAX)

    def test_the_build_packs_folders(self):
        cases = {
            "Type 1 400 550sqft": "type_1",
            "Tpye 2 700 800 sqft": "type_2",
            "type-3": "type_3",
            "TYPE_2": "type_2",
            "office": "office",
            "Office front": "office",
            "Types shops": "",
            "Type 12": "",
            "Videos": "",
        }
        for name, shop in cases.items():
            with self.subTest(name):
                self.assertEqual(shop_media.folder_shop(name), shop)


# The library -------------------------------------------------------------------------------------


class LibraryTests(MediaBase):
    def test_a_file_goes_in_once_in_name_order_and_the_same_bytes_are_the_same_row(self):
        video, created = shop_media.add("type_1", "tour.mp4", mp4("avc1", "mp4a"), uploaded_by=self.admin)
        self.assertTrue(created)
        self.assertEqual((video.kind, video.order, video.mime_type, video.uploaded_by), ("video", 1, "video/mp4", self.admin))
        self.assertTrue(self.stored(video))
        self.assertTrue(video.file.name.startswith("leadai/shops/"))
        photo, _ = shop_media.add("type_1", "front.jpg", jpeg(1))
        again, created = shop_media.add("type_1", "copy of front.jpg", jpeg(1))
        self.assertEqual((again.pk, created), (photo.pk, False))
        # The same bytes in another type are that type's own row.
        _, created = shop_media.add("type_2", "front.jpg", jpeg(1))
        self.assertTrue(created)
        self.assertEqual([row.pk for row in shop_media.rows_for("type_1")], [video.pk, photo.pk])

    def test_one_video_six_photos_a_type_and_one_office_photo(self):
        shop_media.add("type_1", "tour.mp4", mp4("avc1"))
        with self.assertRaises(shop_media.MediaRejected) as raised:
            shop_media.add("type_1", "second.mp4", mp4("avc1", "mp4a"))
        self.assertIn("has its video already", str(raised.exception))
        for index in range(6):
            shop_media.add("type_1", f"{index}.jpg", jpeg(index))
        with self.assertRaises(shop_media.MediaRejected) as raised:
            shop_media.add("type_1", "7.jpg", jpeg(7))
        self.assertIn("6 photos already", str(raised.exception))
        shop_media.add("office", "front.jpg", jpeg(9))
        with self.assertRaises(shop_media.MediaRejected) as raised:
            shop_media.add("office", "front2.jpg", jpeg(10))
        self.assertIn("office has its photo already", str(raised.exception))
        with self.assertRaises(shop_media.MediaRejected):
            shop_media.add("type_4", "x.jpg", jpeg(11))

    def test_the_video_goes_first_whatever_its_order(self):
        photo, _ = shop_media.add("type_2", "a.jpg", jpeg(1))
        video, _ = shop_media.add("type_2", "tour.mp4", mp4("avc1"))
        self.assertEqual([row.pk for row in shop_media.rows_for("type_2")], [video.pk, photo.pk])

    def test_replace_keeps_the_place_and_forgets_the_old_gateway_ids(self):
        first, _ = shop_media.add("type_1", "a.jpg", jpeg(1))
        second, _ = shop_media.add("type_1", "b.jpg", jpeg(2))
        LeadAiShopMediaUpload.objects.create(media=first, number=self.number, gateway_id="old-id", uploaded_at=NOW)
        old_name = first.file.name
        shop_media.replace(first, "better.png", png(3), uploaded_by=self.admin)
        first.refresh_from_db()
        self.assertEqual((first.order, first.file_name, first.mime_type), (1, "better.png", "image/png"))
        self.assertFalse(LeadAiShopMediaUpload.objects.filter(media=first).exists())
        self.assertFalse(os.path.exists(os.path.join(self.media_root, old_name)))
        with self.assertRaises(shop_media.MediaRejected):
            shop_media.replace(first, "tour.mp4", mp4("avc1"))  # a photo's place takes a photo
        with self.assertRaises(shop_media.MediaRejected):
            shop_media.replace(first, "b again.jpg", jpeg(2))  # the other photo's bytes
        self.assertEqual(second.order, 2)

    def test_delete_keeps_a_file_a_sent_message_still_shows(self):
        kept, _ = shop_media.add("type_1", "a.jpg", jpeg(1))
        gone, _ = shop_media.add("type_1", "b.jpg", jpeg(2))
        shop_media._asset(kept)  # a send linked it to the thread
        shop_media.delete(kept)
        shop_media.delete(gone)
        self.assertEqual(LeadAiShopMedia.objects.count(), 0)
        self.assertTrue(os.path.exists(os.path.join(self.media_root, kept.file.name)))
        self.assertFalse(os.path.exists(os.path.join(self.media_root, gone.file.name)))

    def test_reorder_takes_every_file_of_the_shop_once(self):
        a, _ = shop_media.add("type_3", "a.jpg", jpeg(1))
        b, _ = shop_media.add("type_3", "b.jpg", jpeg(2))
        c, _ = shop_media.add("type_3", "c.jpg", jpeg(3))
        other, _ = shop_media.add("type_1", "x.jpg", jpeg(4))
        self.assertEqual([row.pk for row in shop_media.reorder("type_3", [c.pk, a.pk, b.pk])], [c.pk, a.pk, b.pk])
        for ids in ([c.pk, a.pk], [c.pk, a.pk, a.pk], [c.pk, a.pk, b.pk, other.pk], ["x", a.pk, b.pk]):
            with self.subTest(ids=ids), self.assertRaises(shop_media.MediaRejected):
                shop_media.reorder("type_3", ids)


# The build pack's folders --------------------------------------------------------------------------


class ImportTests(MediaBase):
    def folder(self) -> str:
        root = tempfile.mkdtemp(prefix="leadai-import-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)

        def put(path, data):
            os.makedirs(os.path.dirname(os.path.join(root, path)), exist_ok=True)
            with open(os.path.join(root, path), "wb") as handle:
                handle.write(data)

        put("Type 1 400 550sqft/20261013_161440.mp4", mp4("avc1", "mp4a"))
        for index in (10, 2, 3, 4, 5, 6, 7):  # seven photos: name order is 2, 3, ... 10
            put(f"Type 1 400 550sqft/photo {index}.jpg", jpeg(index))
        put("Type 1 400 550sqft/broken.jpg", b"not an image at all")
        put("Tpye 2 700 800 sqft/a.png", png(1))
        put("Videos/random.mp4", mp4("avc1"))
        put("office_front.jpg", jpeg(99))
        put("notes.txt", b"hello")
        return root

    def test_the_folders_go_in_by_name_and_what_does_not_fit_is_reported(self):
        root = self.folder()
        lines = shop_media.import_directory(root)
        self.assertIn("added Office / office_front.jpg (photo, 0.0 MB)", lines)
        self.assertIn("added Type 2 / a.png (photo, 0.0 MB)", lines)
        self.assertIn("added Type 1 / 20261013_161440.mp4 (video, 0.0 MB)", lines)
        self.assertIn("left out Type 1 / photo 10.jpg: Type 1 takes at most 6 photos", lines)
        self.assertTrue(any(line.startswith("refused Type 1: broken.jpg: only an MP4 video") for line in lines), lines)
        self.assertIn("skipped folder 'Videos': not 'Type 1/2/3 ...' or 'office'", lines)
        self.assertIn("skipped file 'notes.txt': not in a 'Type 1/2/3 ...' or 'office' folder", lines)
        photos = [row.file_name for row in shop_media.rows_for("type_1") if row.kind == "photo"]
        self.assertEqual(photos, [f"photo {index}.jpg" for index in (2, 3, 4, 5, 6, 7)])
        self.assertEqual(shop_media.rows_for("type_1")[0].kind, "video")
        self.assertEqual([row.file_name for row in shop_media.rows_for("office")], ["office_front.jpg"])
        # Twice is the same as once.
        again = shop_media.import_directory(root)
        self.assertFalse([line for line in again if line.startswith("added")], again)
        self.assertIn("already there Office / office_front.jpg", again)
        self.assertEqual(LeadAiShopMedia.objects.count(), 9)

    def test_a_dry_run_reports_the_same_and_stores_nothing(self):
        lines = shop_media.import_directory(self.folder(), dry_run=True)
        self.assertEqual(sum(line.startswith("would add") for line in lines), 9)
        self.assertIn("left out Type 1 / photo 10.jpg: Type 1 takes at most 6 photos", lines)
        self.assertFalse(LeadAiShopMedia.objects.exists())
        self.assertEqual(os.listdir(self.media_root), [])

    def test_a_file_too_large_is_refused_by_its_size_without_reading_it(self):
        root = tempfile.mkdtemp(prefix="leadai-import-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "Type 3"))
        with open(os.path.join(root, "Type 3", "huge.mp4"), "wb") as handle:
            handle.write(mp4("avc1", pad=17 * MB))
        lines = shop_media.import_directory(root)
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^refused Type 3: huge\.mp4: 17\.0 MB; a video takes at most 16 MB")

    def test_the_command_prints_each_line_and_a_total(self):
        out = StringIO()
        call_command("leadai_media_import", self.folder(), "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("would add Office / office_front.jpg", text)
        self.assertTrue(text.rstrip().endswith("would add 9 file(s); 2 refused or left out; nothing stored"), text)
        self.assertFalse(LeadAiShopMedia.objects.exists())
        out = StringIO()
        call_command("leadai_media_import", self.folder(), stdout=out)
        self.assertTrue(out.getvalue().rstrip().endswith("added 9 file(s); 2 refused or left out"), out.getvalue())
        with self.assertRaises(CommandError):
            call_command("leadai_media_import", os.path.join(self.media_root, "no-such-folder"), stdout=StringIO())


# The admin API (panel admins change it; every agent reads it) ----------------------------------------


class MediaApiTests(MediaBase):
    URL = "/api/leadai/shop-media/"

    def upload(self, shop, name, data):
        return self.client.post(self.URL, {"shop": shop, "file": self.file(name, data)})

    def file(self, name, data):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(name, data)

    def test_every_agent_reads_it_and_only_a_panel_admin_changes_it(self):
        self.client.force_login(self.agent)
        library = self.client.get(self.URL).json()
        self.assertFalse(library["can_edit"])
        self.assertEqual([group["shop"] for group in library["shops"]], ["type_1", "type_2", "type_3", "office"])
        self.assertEqual(library["shops"][0]["label"], "Type 1 – Small")
        self.assertEqual(library["shops"][3]["limits"], {"videos": 0, "photos": 1})
        self.assertEqual(library["limits"], {"video_mb": 16, "photo_mb": 5})
        self.assertEqual(self.upload("type_1", "a.jpg", jpeg()).status_code, 403)
        row, _ = shop_media.add("type_1", "a.jpg", jpeg())
        self.assertEqual(self.client.delete(f"{self.URL}{row.pk}/").status_code, 403)
        self.assertEqual(self.client.post(f"{self.URL}reorder/", {"shop": "type_1", "ids": [row.pk]}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(f"{self.URL}{row.pk}/replace/", {"file": self.file("b.jpg", jpeg(2))}).status_code, 403)
        # The file itself is what customers get: every agent may open it.
        response = self.client.get(f"{self.URL}{row.pk}/file/")
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(b"".join(response.streaming_content), jpeg())
        self.client.logout()
        self.assertIn(self.client.get(self.URL).status_code, (401, 403))

    def test_an_admin_adds_replaces_reorders_and_deletes(self):
        self.client.force_login(self.admin)
        response = self.upload("type_2", "tour.mp4", mp4("avc1", "mp4a"))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["created"])
        response = self.upload("type_2", "front.jpg", jpeg(1))
        items = response.json()["shops"][1]["items"]
        self.assertEqual([(item["kind"], item["file_name"], item["order"]) for item in items], [("video", "tour.mp4", 1), ("photo", "front.jpg", 2)])
        self.assertEqual(items[1]["url"], f"{self.URL}{items[1]['id']}/file/")
        self.assertEqual(items[1]["uploaded_by"], "admin")
        # The same file again is no second row.
        response = self.upload("type_2", "front again.jpg", jpeg(1))
        self.assertEqual((response.status_code, response.json()["created"]), (200, False))
        back, _ = shop_media.add("type_2", "back.jpg", jpeg(2))
        response = self.client.post(f"{self.URL}reorder/", {"shop": "type_2", "ids": [items[0]["id"], back.pk, items[1]["id"]]}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item["file_name"] for item in response.json()["shops"][1]["items"]], ["tour.mp4", "back.jpg", "front.jpg"])
        response = self.client.post(f"{self.URL}{back.pk}/replace/", {"file": self.file("back new.png", png(5))})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(LeadAiShopMedia.objects.get(pk=back.pk).file_name, "back new.png")
        response = self.client.delete(f"{self.URL}{back.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeadAiShopMedia.objects.filter(pk=back.pk).exists())

    def test_a_refused_file_says_why_in_words_an_admin_can_act_on(self):
        self.client.force_login(self.admin)
        response = self.upload("type_1", "clip.mp4", mp4("hvc1"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be H.264", response.json()["detail"])
        response = self.upload("office", "tour.mp4", mp4("avc1"))
        self.assertIn("office takes one photo", response.json()["detail"])
        response = self.upload("villa", "a.jpg", jpeg())
        self.assertEqual(response.json()["detail"], "Choose Type 1, Type 2, Type 3 or the office.")
        response = self.client.post(self.URL, {"shop": "type_1"})
        self.assertEqual(response.json()["detail"], "Choose a file.")
        response = self.client.post(f"{self.URL}reorder/", {"shop": "type_1", "ids": "1,2"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.delete(f"{self.URL}999/").status_code, 404)
        self.assertFalse(LeadAiShopMedia.objects.exists())


# Sending -------------------------------------------------------------------------------------------


class SendTests(MediaBase):
    def setUp(self):
        super().setUp()
        for target in ("apps.inbox.events.publish_message", "apps.inbox.events.publish_status", "apps.inbox.services.publish_message"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(shop_media, "SEND_PAUSE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sent = []  # (kind, gateway payload)
        self.uploads = []
        self.wamid = 0

    def answer(self):
        self.wamid += 1
        return {"messages": [{"id": f"wamid.test{self.wamid}"}]}

    def gateway(self, *, refuse_media=(), bad_id_once=False):
        """The gateway: uploads give ids, sends give wamids; ``refuse_media``: file names it refuses to send."""
        state = {"bad": bad_id_once}
        names = {}  # media id -> the file name uploaded with it

        def upload(client, phone_number_id, file_obj, filename, mime_type):
            self.uploads.append((phone_number_id, filename))
            names[f"media-{len(self.uploads)}"] = filename
            return f"media-{len(self.uploads)}"

        def send_media(client, phone_number_id, to, kind, media_id, caption=None, filename=None):
            if state["bad"]:
                state["bad"] = False
                raise AlotsError("(#131053) Media upload error: media id is invalid", status_code=400)
            if names.get(media_id) in refuse_media:
                raise AlotsError("(#131052) could not send", status_code=400)
            self.sent.append((kind, media_id, caption))
            return self.answer()

        def send_interactive(client, phone_number_id, to, interactive):
            self.sent.append(("interactive", interactive["type"], interactive))
            return self.answer()

        return patch.multiple(CLIENT, upload_media=upload, send_media=send_media, send_interactive=send_interactive)

    def library(self):
        video, _ = shop_media.add("type_2", "tour.mp4", mp4("avc1", "mp4a"))
        first, _ = shop_media.add("type_2", "1.jpg", jpeg(1))
        second, _ = shop_media.add("type_2", "2.jpg", jpeg(2))
        return video, first, second

    def test_a_types_video_then_its_photos_then_its_card_each_stored_as_ours(self):
        video, first, second = self.library()
        with self.gateway():
            result = shop_media.send_type(self.conversation.pk, "type_2", turn_id=41, language="en")
        self.assertEqual((result["files"], result["skipped"], result["stopped"]), (3, [], ""))
        self.assertEqual([item[0] for item in self.sent], ["video", "image", "image", "interactive"])
        self.assertEqual(self.sent[0][2], "Type 2 – Medium · 600-800 sq ft")  # the video's caption
        card = self.sent[3][2]
        self.assertEqual(card["type"], "button")
        self.assertEqual([b["reply"]["id"] for b in card["action"]["buttons"]], ["lai-shop:book:type_2", "lai-shop:types"])
        self.assertTrue(card["body"]["text"].startswith("TYPE 2 – MEDIUM SHOP\nSize: 600-800 sq ft\nRent: AED 48,000-65,000 per year"))
        rows = list(Message.objects.filter(conversation=self.conversation, direction="out", payload__turn=41).order_by("pk"))
        self.assertEqual([row.kind for row in rows], ["video", "image", "image", "interactive"])
        self.assertTrue(all(row.payload["source"] == "leadai_ai" and row.status == "sent" for row in rows))
        self.assertEqual([row.payload.get("shop_media_id") for row in rows[:3]], [video.pk, first.pk, second.pk])
        self.assertEqual(rows[3].payload["shop_card"], "type_2")
        # The thread shows what went out: the library's own file, not a copy.
        self.assertEqual(rows[1].media.file.name, first.file.name)
        self.assertEqual(MediaAsset.objects.count(), 3)

    def test_a_task_delivered_twice_sends_nothing_twice(self):
        self.library()
        with self.gateway():
            shop_media.send_type(self.conversation.pk, "type_2", turn_id=42)
            again = shop_media.send_type(self.conversation.pk, "type_2", turn_id=42)
        self.assertEqual((again["files"], again["card"], again["stopped"]), (0, None, "the card went out already"))
        self.assertEqual(len(self.sent), 4)

    def test_the_card_alone_when_the_files_went_out_today(self):
        self.library()
        with self.gateway():
            result = shop_media.send_type(self.conversation.pk, "type_2", turn_id=43, files=False)
        self.assertEqual([item[0] for item in self.sent], ["interactive"])
        self.assertEqual(result["files"], 0)
        self.assertFalse(self.uploads)

    def test_a_refused_file_is_skipped_and_the_card_still_goes(self):
        video, first, second = self.library()
        with self.gateway(refuse_media=("1.jpg",)):
            result = shop_media.send_type(self.conversation.pk, "type_2", turn_id=44)
        self.assertEqual(result["skipped"], [first.pk])
        self.assertEqual([item[0] for item in self.sent], ["video", "image", "interactive"])
        failed = Message.objects.get(payload__shop_media_id=first.pk)
        self.assertEqual(failed.status, "failed")

    def test_an_expired_media_id_is_uploaded_again_and_sent_once_more(self):
        video, _ = shop_media.add("type_1", "tour.mp4", mp4("avc1"))
        LeadAiShopMediaUpload.objects.create(media=video, number=self.number, gateway_id="stale-id", uploaded_at=NOW)
        with self.gateway(bad_id_once=True):
            message = shop_media.send_file(self.conversation, video, turn_id=45, shop_type="type_1")
        self.assertEqual(message.status, "sent")
        self.assertEqual(self.uploads, [("pn1", "tour.mp4")])
        self.assertEqual(message.payload["media_id"], "media-1")
        self.assertEqual(LeadAiShopMediaUpload.objects.get(media=video).gateway_id, "media-1")

    def test_a_media_id_is_kept_per_number_for_25_days(self):
        photo, _ = shop_media.add("type_1", "a.jpg", jpeg())
        other = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba1")
        with self.gateway():
            first = shop_media.gateway_media_id(photo, self.number)
            self.assertEqual(shop_media.gateway_media_id(photo, self.number), first)
            self.assertNotEqual(shop_media.gateway_media_id(photo, other), first)  # a media id is its number's own
            self.assertEqual(len(self.uploads), 2)
            self.clock.return_value = NOW + dt.timedelta(days=26)
            self.assertNotEqual(shop_media.gateway_media_id(photo, self.number), first)
        self.assertEqual(len(self.uploads), 3)

    def test_nothing_goes_once_the_chat_is_not_the_assistants(self):
        self.library()
        state = LeadAiChatState.for_conversation(self.conversation)
        LeadAiChatState.objects.filter(pk=state.pk).update(paused_at=NOW)
        with self.gateway():
            result = shop_media.send_type(self.conversation.pk, "type_2", turn_id=46)
        self.assertEqual((result["stopped"], self.sent), ("stopped or paused", []))
        LeadAiChatState.objects.filter(pk=state.pk).update(paused_at=None)
        self.conversation.session_expires_at = NOW - dt.timedelta(minutes=1)
        self.conversation.save(update_fields=["session_expires_at"])
        with self.gateway():
            result = shop_media.send_type(self.conversation.pk, "type_2", turn_id=47)
        self.assertEqual(result["stopped"], "the 24-hour window is closed")

    def test_the_shop_types_list_goes_as_an_interactive_list(self):
        with self.gateway():
            message = shop_media.send_list(self.conversation, "en", None, turn_id=48)
        kind, sub, interactive = self.sent[0]
        self.assertEqual((kind, sub), ("interactive", "list"))
        self.assertEqual(interactive["body"]["text"], "Great! We have 3 types of shops available in International City:")
        self.assertEqual(interactive["action"]["button"], "View shop types")
        rows = interactive["action"]["sections"][0]["rows"]
        self.assertEqual(
            rows,
            [
                {"id": "type_1", "title": "Type 1 – Small", "description": "400-550 sq ft | from AED 33,000/yr"},
                {"id": "type_2", "title": "Type 2 – Medium", "description": "600-800 sq ft | from AED 48,000/yr"},
                {"id": "type_3", "title": "Type 3 – Large", "description": "900-1,200 sq ft | from AED 80,000/yr"},
            ],
        )
        self.assertEqual((message.payload["source"], message.payload["shop_list"], message.status), ("leadai_ai", True, "sent"))
        self.assertTrue(message.body.startswith("Great! We have 3 types"))

    def test_the_task_tells_the_agents_when_the_card_cannot_go(self):
        self.library()

        def broken(*args, **kwargs):
            raise AlotsError("gateway down", status_code=503)

        with self.gateway(), patch(f"{CLIENT}.send_interactive", side_effect=broken), self.captureOnCommitCallbacks(execute=True):
            tasks.send_shop_media(self.conversation.pk, "type_2", 49, "en")
        alert = LeadAiAlert.objects.get(kind="send_failed")
        self.assertIn("could not send the shop details", alert.title)

    def test_a_failed_shop_photo_forgets_its_media_id(self):
        photo, _ = shop_media.add("type_1", "a.jpg", jpeg())
        LeadAiShopMediaUpload.objects.create(media=photo, number=self.number, gateway_id="m1", uploaded_at=NOW)
        message = Message.objects.create(
            conversation=self.conversation, direction="out", kind="image", status="failed",
            payload={"source": "leadai_ai", "shop_media_id": photo.pk, "media_id": "m1"}, error_code="131052",
        )
        with self.captureOnCommitCallbacks(execute=True):
            tasks.outbound_failed(message.pk)
        self.assertFalse(LeadAiShopMediaUpload.objects.filter(media=photo).exists())


class ListAndCardWordsTests(MediaBase):
    """WhatsApp's limits: a row title 24 characters, a description 72, a button 20."""

    def test_every_language_keeps_whatsapps_limits(self):
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                interactive = shop_flow.list_interactive(language, None)
                self.assertLessEqual(len(interactive["action"]["button"]), 20)
                self.assertLessEqual(len(interactive["action"]["sections"][0]["title"]), 24)
                for row in interactive["action"]["sections"][0]["rows"]:
                    self.assertLessEqual(len(row["title"]), 24)
                    self.assertLessEqual(len(row["description"]), 72)
                for button in shop_flow.card_buttons(language, "type_1"):
                    self.assertLessEqual(len(button["title"]), 20)
        self.assertEqual(shop_flow.list_interactive("ar", None)["body"]["text"], "رائع! لدينا 3 أنواع من المحلات المتاحة في المدينة العالمية:")
        # A row's own words stay English, as the build pack's list does.
        self.assertEqual(shop_flow.list_rows(None)[0]["title"], "Type 1 – Small")
