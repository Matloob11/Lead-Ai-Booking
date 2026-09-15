"""Yes/no only: whether Official Django has an OpenAI key. Never prints the secret."""

from django.conf import settings

key = getattr(settings, "OPENAI_API_KEY", "") or ""
print("openai_configured=" + ("yes" if bool(key.strip()) else "no"))
print("openai_model=" + (getattr(settings, "OPENAI_MODEL", "") or "unset"))
