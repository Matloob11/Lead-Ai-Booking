"""Re-queue failed inbound audio downloads after the .bin→.ogg fix."""

from apps.gateway.media import download_media
from apps.inbox.models import MediaAsset, Message

qs = MediaAsset.objects.filter(
    downloaded=False,
    mime_type__startswith="audio",
    source_url__iendswith=".bin",
).order_by("-id")[:80]

queued = 0
for asset in qs:
    msg = (
        Message.objects.filter(media_id=asset.pk)
        .select_related("conversation__number")
        .first()
    )
    if not msg or not msg.conversation or not msg.conversation.number_id:
        continue
    pnid = msg.conversation.number.phone_number_id
    asset.download_error = ""
    asset.save(update_fields=["download_error"])
    download_media.delay(asset.pk, pnid)
    queued += 1

print(f"queued_audio_retries={queued}", flush=True)
