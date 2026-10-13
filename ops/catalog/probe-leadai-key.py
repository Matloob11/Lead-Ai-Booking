"""The Lead AI's own OpenAI key, as a freshly created container reads it.

Run through `ops/wa.sh probe-leadai-key`, in a one-off container (env_file is
read when a container is created, so a running one still holds the old
value). Prints only: whether LEADAI_OPENAI_API_KEY is set, the first 8 hex of
its SHA-256, the model, and how a one-token chat completion answered (HTTP
status and OpenAI's error code, never its message, which can quote the key).
OPENAI_API_KEY, which the rest of the system uses, is only fingerprinted.
"""

import hashlib
import os

import httpx


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8] if value else "-"


key = (os.environ.get("LEADAI_OPENAI_API_KEY") or "").strip()
main = (os.environ.get("OPENAI_API_KEY") or "").strip()
model = (os.environ.get("LEADAI_OPENAI_MODEL") or "gpt-4.1-mini").strip()
print("leadai_key_set=" + ("yes" if key else "no"))
print("leadai_fingerprint=" + fingerprint(key))
print("main_fingerprint=" + fingerprint(main))
print("model=" + model)
if key:
    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": "ok"}], "max_completion_tokens": 1},
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
