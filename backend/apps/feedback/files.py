"""What an agent may attach to a report.

These files are later opened by an admin on the panel's own origin, so the
allowlist is the type, not a blocklist: HTML and SVG execute in a browser and
must never be stored.
"""

IMAGE_MAX_BYTES = 8 * 1024 * 1024
VIDEO_MAX_BYTES = 28 * 1024 * 1024
MAX_FILES = 4
BODY_MAX = 4000
OPEN_CAP = 15
NOTE_MAX = 2000

IMAGE_TYPES = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/gif": "image",
}

VIDEO_TYPES = {
    "video/mp4": "video",
    "video/webm": "video",
    "video/quicktime": "video",
    "video/3gpp": "video",
}

ALLOWED_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES}


def sniff_kind(head: bytes):
    """Kind from the first bytes, or None if the file is not an image/video we keep."""
    if not head:
        return None
    if head.startswith(b"\xff\xd8"):
        return "image"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "video"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video"
    return None


def claimed_kind(content_type: str):
    claimed = (content_type or "").split(";")[0].strip().lower()
    return ALLOWED_TYPES.get(claimed), claimed


def classify_upload(file_obj):
    """Return (kind, mime, error). error is a sentence the agent can be shown."""
    claimed, mime = claimed_kind(getattr(file_obj, "content_type", "") or "")
    if not claimed:
        return None, mime, "Attach a JPEG, PNG, WebP, GIF, MP4, WebM or MOV file."

    size = int(getattr(file_obj, "size", 0) or 0)
    limit = IMAGE_MAX_BYTES if claimed == "image" else VIDEO_MAX_BYTES
    if size <= 0:
        return None, mime, "That attachment is empty."
    if size > limit:
        label = "8 MB" if claimed == "image" else "28 MB"
        return None, mime, f"That {claimed} is too large. Keep it under {label}."

    head = file_obj.read(16)
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    sniffed = sniff_kind(head)
    if sniffed != claimed:
        return None, mime, "That file does not match an allowed image or video type."

    return claimed, mime, None
