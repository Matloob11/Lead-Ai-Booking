"""Yes/no only: Official OpenAI key present, and whether a tiny call has credits."""

import httpx
from django.conf import settings

key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
print("openai_configured=" + ("yes" if key else "no"))
if not key:
    print("credits=unknown")
else:
    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
                "messages": [{"role": "user", "content": "ok"}],
                "max_tokens": 1,
            },
            timeout=30,
        )
    except httpx.HTTPError:
        print("http=unreachable")
        print("credits=unknown")
    else:
        print(f"http={response.status_code}")
        err_code = ""
        try:
            err_code = str((response.json().get("error") or {}).get("code") or "")
        except Exception:
            err_code = ""
        if response.status_code == 200:
            print("credits=yes")
        elif response.status_code == 429 and err_code in (
            "insufficient_quota",
            "credit_balance_exhausted",
        ):
            print("credits=no")
            print(f"error_code={err_code}")
        elif response.status_code == 429:
            print("credits=rate_limited")
            print(f"error_code={err_code or 'none'}")
        elif response.status_code == 401:
            print("credits=unknown")
            print("error_code=unauthorized")
        else:
            print("credits=unknown")
            if err_code:
                print(f"error_code={err_code}")
