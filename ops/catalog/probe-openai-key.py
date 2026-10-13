"""The OpenAI key the live containers use, without ever showing it.

Run through `ops/wa.sh probe-openai-key`. Prints only: whether a key is set,
the first 8 hex of its SHA-256 (enough to tell two keys apart, useless for
anything else), the model, and how a one-token chat completion answered (the
HTTP status and OpenAI's error code, never its message, which can quote part
of the key).
"""

import hashlib

import httpx
from django.conf import settings

key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
print("openai_configured=" + ("yes" if key else "no"))
print("fingerprint=" + (hashlib.sha256(key.encode()).hexdigest()[:8] if key else "-"))
print("model=" + model)
if key:
    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print("http=unreachable " + type(exc).__name__)
    else:
        code = ""
        try:
            code = str((response.json().get("error") or {}).get("code") or "")
        except Exception:  # noqa: BLE001
            code = ""
        print(f"http={response.status_code}" + (f" error_code={code}" if code else ""))
        print("works=" + ("yes" if response.status_code == 200 else "no"))
print("PROBE_OK")
