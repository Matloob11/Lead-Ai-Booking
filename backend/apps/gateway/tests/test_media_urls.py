from apps.gateway.media import candidate_media_urls


class _Asset:
    def __init__(self, source_url="", fallback_url="", mime_type=""):
        self.source_url = source_url
        self.fallback_url = fallback_url
        self.mime_type = mime_type


def test_audio_bin_filelink_tries_ogg_before_lookaside():
    urls = candidate_media_urls(
        _Asset(
            source_url="https://gsauth.com/WhatsAppMedia/LiveAgent/X/Audio/Received/1.bin",
            fallback_url="https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
            mime_type="audio/ogg; codecs=opus",
        )
    )
    assert urls[0].endswith(".bin")
    assert urls[1].endswith(".ogg")
    assert urls[-1].startswith("https://lookaside.fbsbx.com/")


def test_image_keeps_real_extension_without_extra_guesses():
    urls = candidate_media_urls(
        _Asset(
            source_url="https://gsauth.com/WhatsAppMedia/LiveAgent/X/Image/Received/1.jpg",
            fallback_url="https://lookaside.fbsbx.com/x",
            mime_type="image/jpeg",
        )
    )
    assert urls == [
        "https://gsauth.com/WhatsAppMedia/LiveAgent/X/Image/Received/1.jpg",
        "https://lookaside.fbsbx.com/x",
    ]
