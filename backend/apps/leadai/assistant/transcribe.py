"""Voice notes in Lead AI chats, heard with the Lead AI key (owner's choice).

The gateway downloads an inbound voice note in the background
(apps.gateway.media.download_media: a first try, then up to three more 60 s
apart), and stores it as '<id>.bin' with the mime type 'audio/ogg;
codecs=opus'. ``transcript_for`` answers:
- the text once heard (cached; a heard note is never sent to OpenAI again);
- '' when it cannot be heard (no file in the end, a refused file after two
  tries, or the turn has waited long enough);
- None while the file may still arrive, so the turn waits and comes back.
A failure is recorded with its count, never as a final answer, so a voice
note whose file arrives late is still heard by the next turn.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone

from ..models import LeadAiTranscript
from . import openai_client

logger = logging.getLogger(__name__)

DOWNLOAD_GIVES_UP_AFTER = dt.timedelta(minutes=4)
MAX_ATTEMPTS = 2


def transcript_for(message, *, give_up: bool = False, deadline: float | None = None) -> str | None:
    """``deadline`` is the turn's time.monotonic() budget, handed to the OpenAI call."""
    row = LeadAiTranscript.objects.filter(message=message).first()
    if row is not None and row.heard:
        return row.text
    if row is not None and row.attempts >= MAX_ATTEMPTS:
        return ""

    asset = message.media
    if asset is None:
        return ""
    if not asset.downloaded or not asset.file:
        gave_up = bool(asset.download_error) and asset.created_at < timezone.now() - DOWNLOAD_GIVES_UP_AFTER
        if gave_up or give_up:
            _record(message, "", "not downloaded", count=False)
            return ""
        return None

    try:
        with asset.file.open("rb") as handle:
            content = handle.read()
    except (OSError, ValueError) as exc:
        logger.warning("Lead AI could not read voice note %s: %s", message.pk, exc)
        _record(message, "", "file unreadable")
        return ""

    try:
        text = openai_client.transcribe(content, asset.mime_type, deadline=deadline)
    except openai_client.AssistantError as exc:
        logger.warning("Lead AI transcription failed for message %s: %s %s", message.pk, exc.code, exc.detail)
        # Out of turn time is not the file's fault: the next turn tries it again.
        _record(message, "", exc.code, count=getattr(exc, "kind", "") != "time")
        return ""
    _record(message, text, "", model=openai_client.transcribe_model())
    return text


def _record(message, text: str, error: str, *, model: str = "", count: bool = True) -> None:
    row, _ = LeadAiTranscript.objects.get_or_create(message=message)
    row.text = text[:8000]
    row.error = error[:255]
    if model:
        row.model = model
    if count:
        row.attempts = min(row.attempts + 1, 99)
    row.save()
