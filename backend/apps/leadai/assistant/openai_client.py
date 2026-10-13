"""The Lead AI's own OpenAI calls.

Every call here uses settings.LEADAI_OPENAI_API_KEY and nothing else. If that
key is missing the assistant is simply off; it never borrows the main
OPENAI_API_KEY, which Sara, the AI desk, CRM summaries and template rewrites
use (the owner asked that the new key be used by Lead AI only, and that the
others stay exactly as they were).

Errors carry OpenAI's HTTP status and error code but never its message text,
which can quote part of the key. ``AssistantError.kind`` says what failed:
the way to OpenAI ("transport"), the answer it gave ("content"), something a
retry cannot fix such as a wrong key or no credit ("final"), or the turn's own
time ("time").

A turn passes its ``deadline`` (a time.monotonic() value): each call then
waits at most until a second before it, never retries without time for a
whole attempt, and is not made at all with under five seconds left, so the
Celery time limit is not what ends a turn.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

import httpx
from django.conf import settings

CHAT_URL = "https://api.openai.com/v1/chat/completions"
TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
TRANSCRIBE_MAX_BYTES = 2 * 1024 * 1024  # about ten minutes of WhatsApp voice
CACHE_KEY = "leadai-v2"
CONNECT_TIMEOUT = 5.0
RETRY_PAUSE = 2.0
# Below this, a call cannot finish before the turn's deadline: it is not made.
MIN_TIME_LEFT = 5.0

# Words the transcriber would otherwise misspell (names of places and terms
# customers say in Dubai real-estate voice notes).
VOCABULARY = (
    "Dubai real estate. A7, AR Properties, International City, Russia Cluster, England Cluster, "
    "France Cluster, China Cluster, Dragon Mart, Warsan, Villanova, Mudon, Damac Lagoons, shop, "
    "warehouse, trade licence, Ejari, DEWA, cheques, AED, square feet, studio, 1BHK, 2BHK."
)

# The container types OpenAI accepts, by the mime type the gateway stored.
AUDIO_NAMES = {
    "audio/ogg": ("voice.ogg", "audio/ogg"),
    "audio/opus": ("voice.ogg", "audio/ogg"),
    "audio/mpeg": ("voice.mp3", "audio/mpeg"),
    "audio/mp3": ("voice.mp3", "audio/mpeg"),
    "audio/mp4": ("voice.m4a", "audio/mp4"),
    "audio/m4a": ("voice.m4a", "audio/mp4"),
    "audio/x-m4a": ("voice.m4a", "audio/mp4"),
    "audio/aac": ("voice.m4a", "audio/mp4"),
    "audio/amr": ("voice.amr", "audio/amr"),
    "audio/wav": ("voice.wav", "audio/wav"),
    "audio/x-wav": ("voice.wav", "audio/wav"),
    "audio/webm": ("voice.webm", "audio/webm"),
}


class AssistantError(Exception):
    """OpenAI could not give a usable answer. ``code`` is short and log-safe.

    ``kind``: "transport" (a timeout, no connection, 429, 5xx, or a 200 with
    no chat completion in it), "content" (the model answered, but refused,
    was cut off or wrote something that is not the JSON asked for), "final"
    (400, 401, 403, 404, no credit: a retry cannot fix it) or "time" (the
    turn had no time left for the call). Without a kind it is "final" when
    ``final`` is set, else "transport".
    """

    KINDS = ("transport", "content", "final", "time")

    def __init__(self, code: str, detail: str = "", final: bool = False, kind: str | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.kind = kind if kind in self.KINDS else ("final" if final else "transport")

    @property
    def final(self) -> bool:
        """For older callers: a failure a retry cannot fix."""
        return self.kind == "final"


def _key() -> str:
    return (getattr(settings, "LEADAI_OPENAI_API_KEY", "") or "").strip()


def configured() -> bool:
    return bool(_key())


def chat_model() -> str:
    return (getattr(settings, "LEADAI_OPENAI_MODEL", "") or "gpt-4.1-mini").strip()


def transcribe_model() -> str:
    return (getattr(settings, "LEADAI_TRANSCRIBE_MODEL", "") or "gpt-4o-mini-transcribe").strip()


def _seconds() -> float:
    """How long one call may wait for OpenAI's answer (LEADAI_OPENAI_TIMEOUT, 5-60 s)."""
    try:
        seconds = float(getattr(settings, "LEADAI_OPENAI_TIMEOUT", 25) or 25)
    except (TypeError, ValueError):
        seconds = 25.0
    return min(max(seconds, 5.0), 60.0)


def _timeout(deadline: float | None) -> httpx.Timeout:
    """One attempt's timeout: the configured wait, cut to end a second before ``deadline``.

    Raises AssistantError "no_time" (kind "time") with under MIN_TIME_LEFT
    seconds left, before anything is sent.
    """
    read = _seconds()
    if deadline is not None:
        left = deadline - time.monotonic()
        if left < MIN_TIME_LEFT:
            raise AssistantError("no_time", f"{max(left, 0.0):.1f} s left in the turn", kind="time")
        read = min(read, left - 1)
    return httpx.Timeout(read, connect=min(CONNECT_TIMEOUT, read))


def _time_for_retry(deadline: float | None) -> bool:
    """Is there time for the pause and one more whole attempt before ``deadline``?"""
    return deadline is None or deadline - time.monotonic() - RETRY_PAUSE >= _seconds() + 1


def _error_code(response) -> str:
    try:
        error = response.json().get("error") or {}
        return str(error.get("code") or error.get("type") or "")[:60]
    except Exception:  # noqa: BLE001
        return ""


def _http_error(response) -> AssistantError:
    code = _error_code(response)
    status = response.status_code
    final = status in (400, 401, 403, 404) or code in ("insufficient_quota", "invalid_api_key", "model_not_found")
    return AssistantError(f"http_{status}", code, final=final)


@dataclass
class Completion:
    data: dict
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def safety_id(conversation_id) -> str:
    """A stable, anonymous id per chat (OpenAI's abuse monitoring), never the number."""
    return hashlib.sha256(f"leadai:{conversation_id}".encode()).hexdigest()[:32]


def complete_json(
    messages: list[dict],
    schema: dict,
    *,
    name: str = "leadai_turn",
    temperature: float = 0.3,
    max_tokens: int = 700,
    user: str = "",
    deadline: float | None = None,
) -> Completion:
    """One chat completion whose answer must match ``schema`` (structured outputs).

    One retry after a short pause on a timeout, a 429 rate limit or a 5xx,
    when the deadline leaves time for it; anything else is not retried.
    Raises AssistantError.
    """
    key = _key()
    if not key:
        raise AssistantError("not_configured", "LEADAI_OPENAI_API_KEY is not set", final=True)
    body = {
        "model": chat_model(),
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
        "prompt_cache_key": CACHE_KEY,
    }
    if user:
        body["safety_identifier"] = user
    started = time.monotonic()
    response = None
    for attempt in range(2):
        timeout = _timeout(deadline)
        try:
            response = httpx.post(
                CHAT_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            if attempt == 0 and _time_for_retry(deadline):
                time.sleep(RETRY_PAUSE)
                continue
            raise AssistantError("unreachable", type(exc).__name__) from None
        if response.status_code == 200:
            break
        error = _http_error(response)
        retryable = response.status_code == 429 or response.status_code >= 500
        if attempt == 0 and error.kind == "transport" and retryable and _time_for_retry(deadline):
            time.sleep(RETRY_PAUSE)
            continue
        raise error

    try:
        payload = response.json()
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, ValueError, TypeError):
        # Not the model's answer but the service's: counts towards the breaker.
        raise AssistantError("unreadable", "no choices in the answer", kind="transport") from None
    if message.get("refusal"):
        raise AssistantError("refused", str(message.get("refusal"))[:200], kind="content")
    if choice.get("finish_reason") == "length":
        raise AssistantError("too_long", "the answer was cut off", kind="content")
    try:
        data = json.loads(message.get("content") or "")
    except (ValueError, TypeError):
        raise AssistantError("unreadable", "the answer was not JSON", kind="content") from None
    if not isinstance(data, dict):
        raise AssistantError("unreadable", "the answer was not a JSON object", kind="content")

    usage = payload.get("usage") or {}
    return Completion(
        data=data,
        model=str(payload.get("model") or chat_model()),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def upload_name(mime_type: str) -> tuple[str, str]:
    """(filename, content type) OpenAI accepts for a stored voice note.

    The gateway stores WhatsApp voice notes as '<id>.bin' with the mime type
    'audio/ogg; codecs=opus'; OpenAI decides the format from the filename,
    so a '.bin' upload is refused. The parameters after ';' are dropped.
    """
    base = (mime_type or "").split(";", 1)[0].strip().lower()
    return AUDIO_NAMES.get(base, ("voice.ogg", "audio/ogg"))


def transcribe(content: bytes, mime_type: str = "", *, deadline: float | None = None) -> str:
    """The words in a voice note. One attempt, cut to the deadline. Raises AssistantError."""
    key = _key()
    if not key:
        raise AssistantError("not_configured", "LEADAI_OPENAI_API_KEY is not set", final=True)
    if not content:
        raise AssistantError("empty_audio", final=True)
    if len(content) > TRANSCRIBE_MAX_BYTES:
        raise AssistantError("audio_too_long", f"{len(content)} bytes", final=True)
    timeout = _timeout(deadline)
    filename, content_type = upload_name(mime_type)
    files = {"file": (filename, content, content_type)}
    data = {"model": transcribe_model(), "response_format": "json", "prompt": VOCABULARY}
    try:
        response = httpx.post(
            TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise AssistantError("unreachable", type(exc).__name__) from None
    if response.status_code != 200:
        raise _http_error(response)
    try:
        text = str(response.json().get("text") or "").strip()
    except (ValueError, AttributeError):
        raise AssistantError("unreadable", "transcription was not JSON", kind="content") from None
    return text
