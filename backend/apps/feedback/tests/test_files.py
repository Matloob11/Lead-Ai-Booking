from io import BytesIO

from apps.feedback.files import classify_upload, sniff_kind


class _Upload:
    def __init__(self, data, content_type, name="file.bin"):
        self._buf = BytesIO(data)
        self.content_type = content_type
        self.size = len(data)
        self.name = name

    def read(self, n=-1):
        return self._buf.read(n)

    def seek(self, pos):
        self._buf.seek(pos)


def test_jpeg_is_image():
    data = b"\xff\xd8\xff" + b"\x00" * 20
    kind, mime, error = classify_upload(_Upload(data, "image/jpeg", "shot.jpg"))
    assert error is None
    assert kind == "image"
    assert mime == "image/jpeg"


def test_png_is_image():
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    kind, _mime, error = classify_upload(_Upload(data, "image/png", "a.png"))
    assert error is None
    assert kind == "image"


def test_mp4_is_video():
    data = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8
    kind, _mime, error = classify_upload(_Upload(data, "video/mp4", "clip.mp4"))
    assert error is None
    assert kind == "video"


def test_html_is_rejected():
    data = b"<!DOCTYPE html><html></html>"
    kind, _mime, error = classify_upload(_Upload(data, "text/html", "x.html"))
    assert kind is None
    assert error


def test_svg_claimed_as_png_is_rejected():
    data = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    kind, _mime, error = classify_upload(_Upload(data, "image/png", "x.png"))
    assert kind is None
    assert error


def test_empty_is_rejected():
    kind, _mime, error = classify_upload(_Upload(b"", "image/jpeg", "a.jpg"))
    assert kind is None
    assert error


def test_sniff_webp():
    head = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBP"
    assert sniff_kind(head) == "image"


def test_sniff_unknown():
    assert sniff_kind(b"PK\x03\x04") is None
