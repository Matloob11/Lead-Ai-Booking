"""Rewrite an agent's typed draft into Meta-safe UTILITY templates.

The output must stay on that draft: same people, place, date, file,
community. It must not invent a documents card around a viewing, or
pad five generic jobs when the model is down.
"""

from __future__ import annotations

import json
import logging
import re

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"[^a-z0-9_]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
PRICE_RE = re.compile(
    r"(?i)"
    r"(?:\b(?:aed|usd|gbp|eur|rs|pkr)\s*[\d,]+(?:\.\d+)?\b)"
    r"|(?:\b[\d,]+\s*(?:aed|usd|gbp|eur|rs|pkr)\b)"
    r"|(?:\$\s*[\d,]+(?:\.\d+)?)"
    r"|(?:\bstarting from\b[^.!?]*)"
    r"|(?:\bfrom aed\b[^.!?]*)"
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s*[ap]m)?\b", re.I)
DATE_WORD_RE = re.compile(
    r"\b(?:today|tomorrow|yesterday|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|wed|thu|fri|sat|sun)\b",
    re.I,
)
ISO_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
REF_RE = re.compile(r"\b[A-Z]{1,6}-?\d{2,}\b")
PROPER_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
HOLE_RE = re.compile(r"\{\{(\d+)\}\}")
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_-]+|Bearer\s+\S+", re.I)

STOP_PROPER = {
    "A",
    "An",
    "Appointment",
    "Book",
    "Callback",
    "Call",
    "Confirm",
    "Contact",
    "Dear",
    "Document",
    "Documents",
    "File",
    "Hello",
    "Hi",
    "Launch",
    "Limited",
    "New",
    "Now",
    "Offer",
    "Payment",
    "Phase",
    "Please",
    "Property",
    "Register",
    "Reminder",
    "Reply",
    "Sale",
    "Send",
    "Starting",
    "Thank",
    "Thanks",
    "The",
    "This",
    "Units",
    "Update",
    "Viewing",
    "Villas",
    "We",
    "Your",
}

GREET_LEADS = {"Hello", "Hi", "Dear"}


def _proper_from_match(match):
    word = match.group(1)
    start = match.start()
    parts = word.split()
    if parts and parts[0] in GREET_LEADS:
        start = start + len(parts[0])
        rest = word[len(parts[0]):]
        stripped = rest.lstrip()
        start += len(rest) - len(stripped)
        word = stripped
    lead = word.split()[0] if word else ""
    if lead in STOP_PROPER and " " not in word:
        return None
    if not word or word in STOP_PROPER:
        return None
    return start, match.end(), word


# Extra promo lines dropped only by the local rewrite, not Meta-safety.
LOCAL_PROMO_EXTRA = (
    "limited units",
    "book a viewing",
    "book a visit",
    "register now",
    "contact us now",
)

APPOINTMENT_HINTS = (
    "viewing",
    "appointment",
    "meeting",
    "callback",
    "scheduled",
    "confirmed",
    "visit",
)

# Phrases Meta treats as promotional even inside a "utility" submission.
# Checked after the model answers, because a model will still sneak an offer in.
MARKETING_FRAGMENTS = (
    "limited time",
    "special offer",
    "discount",
    "book now",
    "don't miss",
    "do not miss",
    "new launch",
    "new phase",
    "starting from",
    "from aed",
    "from $",
    "investment opportunity",
    "exclusive offer",
    "flash sale",
    "% off",
    "off the price",
    "luxury villas for sale",
    "units still available",
    "register your interest",
    "act now",
)

PROMPT = """You rewrite ONE WhatsApp draft into Meta UTILITY wording.

Stay on the agent's typed situation. Do not invent a different job
(no documents card unless the draft is about documents; no payment
receipt unless the draft is about a payment; no callback unless they
asked for a call).

WhatsApp UTILITY is only for a specific transaction the customer already has:
appointment confirmed/changed/reminded, documents requested or received,
callback scheduled, payment or booking receipt, account or ticket update.

It is NOT for: new projects, prices, offers, "limited units", launches,
re-engagement, or asking a cold contact to book a viewing of a promotion.

Return JSON only:
{
  "analysis": "1-2 English sentences. If the draft would be MARKETING, say
               which promotional bit Meta would score. If already utility,
               say what you kept.",
  "original_would_be_marketing": true or false,
  "suggestions": [ 1 to 3 objects ]
}

Each suggestion:
{
  "name": "lowercase_underscores_only",
  "header": "optional, max 60 chars, no promo",
  "body": "required. Same people, place, date, file, community as the draft.
           Reuse those facts as {{1}} {{2}} … . No prices, offers, launches.",
  "footer": "optional, max 60 chars, e.g. A7 Group Real Estate",
  "body_examples": { "1": "Ahmed", "2": "Tue 11:00" },
  "header_examples": {},
  "buttons": [ { "type": "QUICK_REPLY", "text": "Confirm" } ]
}

Give 1 to 3 suggestions — wordings of THIS draft, not five generic jobs.
If the draft is already Utility: one tightened version, optional second as
a reminder of the same event.
If Marketing: strip promo, keep the real facts.
Write the body in the language code given.
Buttons: at most 2, QUICK_REPLY only, labels max 25 chars.
Names: unique, snake_case, max 40 chars."""


class RewriteError(Exception):
    pass


def configured():
    return bool((getattr(settings, "OPENAI_API_KEY", "") or "").strip())


def looks_like_marketing(text):
    haystack = " ".join(str(text or "").lower().split())
    return any(fragment in haystack for fragment in MARKETING_FRAGMENTS)


def _safe_ai_error(exc):
    return SECRET_RE.sub("[redacted]", str(exc)[:180]).strip()


def _clean_name(raw, fallback):
    name = NAME_RE.sub("_", str(raw or "").lower()).strip("_")[:40]
    return name or fallback


def _clean_buttons(raw):
    buttons = []
    if not isinstance(raw, list):
        return buttons
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()[:25]
        if not text or looks_like_marketing(text):
            continue
        buttons.append({"type": "QUICK_REPLY", "text": text, "url": "", "phone_number": "", "example": ""})
        if len(buttons) >= 2:
            break
    return buttons


def _examples_from(text, stored):
    holes = HOLE_RE.findall(text or "")
    out = {}
    source = stored if isinstance(stored, dict) else {}
    for hole in holes:
        sample = str(source.get(hole) or source.get(int(hole) if hole.isdigit() else hole) or "").strip()
        out[hole] = sample or "sample"
    return out


def _normalise_suggestion(raw, index):
    if not isinstance(raw, dict):
        return None
    body = str(raw.get("body") or "").strip()
    if not body or looks_like_marketing(body):
        return None
    header = str(raw.get("header") or "").strip()[:60]
    footer = str(raw.get("footer") or "").strip()[:60]
    if looks_like_marketing(header) or looks_like_marketing(footer):
        header = ""
        if looks_like_marketing(footer):
            footer = "A7 Group Real Estate"
    name = _clean_name(raw.get("name"), f"utility_update_{index}")
    return {
        "name": name,
        "header": header,
        "body": body[:1024],
        "footer": footer,
        "body_examples": _examples_from(body, raw.get("body_examples")),
        "header_examples": _examples_from(header, raw.get("header_examples")),
        "buttons": _clean_buttons(raw.get("buttons")),
    }


def _sentences(text):
    return [part.strip() for part in SENTENCE_RE.split(text or "") if part.strip()]


def _is_local_promo(sentence):
    if looks_like_marketing(sentence):
        return True
    haystack = " ".join(str(sentence or "").lower().split())
    return any(fragment in haystack for fragment in LOCAL_PROMO_EXTRA)


def _strip_marketing_text(text):
    cleaned = PRICE_RE.sub(" ", text or "")
    kept = []
    for sentence in _sentences(cleaned):
        if _is_local_promo(sentence):
            continue
        piece = " ".join(sentence.split())
        if piece:
            kept.append(piece)
    return " ".join(kept).strip()


def _extract_nouns(text):
    nouns = []
    for match in PROPER_RE.finditer(text or ""):
        parsed = _proper_from_match(match)
        if parsed:
            nouns.append(parsed[2])
    for match in REF_RE.finditer(text or ""):
        nouns.append(match.group(0))
    seen = set()
    out = []
    for noun in nouns:
        key = noun.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(noun)
    return out


def _collect_spans(text):
    spans = []
    for regex in (TIME_RE, DATE_WORD_RE, ISO_DATE_RE, REF_RE):
        for match in regex.finditer(text):
            spans.append((match.start(), match.end(), match.group(0)))
    for match in PROPER_RE.finditer(text):
        parsed = _proper_from_match(match)
        if parsed:
            spans.append(parsed)
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    picked = []
    occupied = []
    for start, end, value in spans:
        if any(start < other_end and end > other_start for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        picked.append((start, end, value))
    picked.sort(key=lambda item: item[0])
    return picked


def _placeholderize(text):
    """Turn leftover facts into {{n}}. Keep holes the agent already typed."""
    text = text or ""
    if HOLE_RE.search(text):
        return text, {}
    examples = {}
    out = []
    last = 0
    index = 1
    for start, end, value in _collect_spans(text):
        out.append(text[last:start])
        out.append(f"{{{{{index}}}}}")
        examples[str(index)] = value
        index += 1
        last = end
    out.append(text[last:])
    return "".join(out), examples


def _footer_from(footer):
    cleaned = (footer or "").strip()
    if not cleaned or looks_like_marketing(cleaned):
        return "A7 Group Real Estate"
    return cleaned[:60]


def _closest_utility_line(nouns):
    if len(nouns) >= 2:
        return (
            "Hello {{1}}, this is an update about {{2}}.",
            {"1": nouns[0], "2": nouns[1]},
        )
    if nouns:
        return (
            "Hello {{1}}, this is an update about {{2}}.",
            {"1": "there", "2": nouns[0]},
        )
    return (
        "Hello {{1}}, this is an update on your request.",
        {"1": "there"},
    )


def local_rewrite(*, body, name="", header="", footer="", language="en"):
    """1–2 Utility wordings derived from the typed draft. Deterministic."""
    combined = " ".join(part for part in (name, header, body, footer) if part)
    marketing = looks_like_marketing(combined)
    core = _strip_marketing_text(body)
    header_core = _strip_marketing_text(header)
    if looks_like_marketing(header_core):
        header_core = ""
    footer_core = _footer_from(footer)
    nouns = _extract_nouns(" ".join(part for part in (header, body) if part))
    suggestions = []

    if len(core) < 12:
        line, examples = _closest_utility_line(nouns)
        row = _normalise_suggestion(
            {
                "name": _clean_name(name, "utility_update"),
                "header": header_core[:60],
                "body": line,
                "footer": footer_core,
                "body_examples": examples,
                "buttons": [{"type": "QUICK_REPLY", "text": "Okay"}],
            },
            1,
        )
        if row:
            suggestions.append(row)
        analysis = (
            "The draft had no existing transaction after promotional wording was removed. "
            "This is the closest Utility line using a name from your text."
            if marketing
            else "One Utility wording from your draft."
        )
        return [item for item in suggestions if item][:2], analysis, marketing

    body_ph, examples = _placeholderize(core)
    english = (language or "en").lower().startswith("en")
    if english and not HOLE_RE.search(body_ph) and not examples:
        greeting = nouns[0] if nouns else "there"
        if re.match(r"(?i)^(hello|hi|dear)\b", body_ph):
            body_ph = re.sub(r"(?i)^(hello|hi|dear)\s*", r"\1 {{1}}, ", body_ph, count=1)
        else:
            rest = body_ph[0].lower() + body_ph[1:] if body_ph else "this is an update."
            body_ph = f"Hello {{1}}, {rest}"
        examples = {"1": greeting}

    is_appointment = any(hint in core.lower() for hint in APPOINTMENT_HINTS)
    primary = _normalise_suggestion(
        {
            "name": _clean_name(name, "utility_update"),
            "header": header_core[:60],
            "body": body_ph,
            "footer": footer_core,
            "body_examples": examples,
            "buttons": [{"type": "QUICK_REPLY", "text": "Confirm" if is_appointment else "Okay"}],
        },
        1,
    )
    if primary:
        suggestions.append(primary)

    if is_appointment and "remind" not in core.lower() and examples:
        holes = sorted(examples, key=lambda key: int(key) if str(key).isdigit() else 0)
        first = holes[0]
        rest = " ".join(f"{{{{{hole}}}}}" for hole in holes[1:]) or f"{{{{{first}}}}}"
        reminder = _normalise_suggestion(
            {
                "name": "same_event_reminder",
                "header": "Reminder",
                "body": f"Hello {{{{{first}}}}}, this is a reminder about {rest}.",
                "footer": footer_core,
                "body_examples": examples,
                "buttons": [{"type": "QUICK_REPLY", "text": "Okay"}],
            },
            2,
        )
        if reminder:
            suggestions.append(reminder)

    analysis = (
        "Promotional wording was removed. These Utility wordings keep the facts from your draft."
        if marketing
        else "Utility wording of your draft. Same situation, no extra jobs."
    )
    return [item for item in suggestions if item][:2], analysis, marketing


def _ask_openai(draft):
    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": draft},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.45,
            },
            timeout=int(getattr(settings, "OPENAI_TIMEOUT", 45) or 45),
        )
    except httpx.HTTPError as exc:
        raise RewriteError(f"OpenAI unreachable: {exc}") from None

    if response.status_code != 200:
        raise RewriteError(f"OpenAI answered {response.status_code}")

    try:
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise RewriteError(f"OpenAI returned something unreadable: {exc}") from None


def _collect_openai_rows(raw_rows):
    suggestions = []
    seen = set()
    for index, row in enumerate(raw_rows, start=1):
        item = _normalise_suggestion(row, index)
        if not item or item["name"] in seen:
            continue
        seen.add(item["name"])
        suggestions.append(item)
        if len(suggestions) >= 3:
            break
    return suggestions


def rewrite_as_utility(*, body, name="", header="", footer="", language="en", category=""):
    """1–3 Utility wordings of this draft. OpenAI when a key exists, else local."""
    local_rows, local_analysis, marketing = local_rewrite(
        body=body,
        name=name,
        header=header,
        footer=footer,
        language=language,
    )
    ai_configured = configured()
    ai_error = ""
    source = "local"
    analysis = local_analysis
    suggestions = local_rows
    original_would_be_marketing = marketing

    if not ai_configured:
        ai_error = "Rewrite service is not configured"
    else:
        draft = (
            f"language: {language or 'en'}\n"
            f"agent_category: {category or 'UTILITY'}\n"
            f"name: {name or '(none)'}\n"
            f"header: {header or '(none)'}\n"
            f"footer: {footer or '(none)'}\n"
            f"body:\n{body}"
        )
        try:
            data = _ask_openai(draft)
            analysis = str(data.get("analysis") or analysis).strip()[:500]
            original_would_be_marketing = bool(
                data.get("original_would_be_marketing", original_would_be_marketing)
            )
            raw_rows = data.get("suggestions") if isinstance(data.get("suggestions"), list) else []
            openai_rows = _collect_openai_rows(raw_rows)
            if openai_rows:
                source = "openai"
                suggestions = openai_rows
            else:
                ai_error = "Model returned no usable Utility wording"
                analysis = local_analysis
        except RewriteError as exc:
            logger.warning("Utility rewrite fell back: %s", exc)
            ai_error = _safe_ai_error(exc)
            analysis = local_analysis

    return {
        "analysis": analysis,
        "original_would_be_marketing": original_would_be_marketing,
        "source": source,
        "ai_configured": ai_configured,
        "ai_error": ai_error,
        "suggestions": suggestions[:3],
    }
