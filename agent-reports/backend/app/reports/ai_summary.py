"""OpenAI narrative — numbers must come only from the snapshot."""

from __future__ import annotations

import json

from openai import OpenAI

from ..bitrix.metrics import AgentDaySnapshot
from ..config import get_settings


def write_ai_summary(snapshot: AgentDaySnapshot) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        return _fallback_summary(snapshot)

    facts = snapshot.as_dict()
    prompt = (
        "You write a short English daily coaching note for a real-estate sales manager.\n"
        "Use ONLY the JSON facts below. Do not invent numbers, leads, or calls.\n"
        "If check-in is false, say they did not check in (or data missing).\n"
        "3–5 sentences. No markdown. No bullet list.\n\n"
        f"FACTS:\n{json.dumps(facts, ensure_ascii=True)}"
    )
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are concise and factual."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=280,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or _fallback_summary(snapshot)
    except Exception as exc:  # noqa: BLE001
        return _fallback_summary(snapshot) + f" (AI unavailable: {exc})"


def _fallback_summary(snapshot: AgentDaySnapshot) -> str:
    check = "checked in" if snapshot.timeman.checked_in else "did not check in (or no timeman data)"
    return (
        f"{snapshot.agent_name} {check} on {snapshot.day}. "
        f"Open book: {snapshot.leads.total_open} leads "
        f"({snapshot.leads.classic_open} classic, {snapshot.leads.owner_data_open} owner data); "
        f"new today: {snapshot.leads.new_classic_today + snapshot.leads.new_owner_data_today}. "
        f"Calls: {snapshot.calls.count} ({snapshot.calls.talk_minutes} min). "
        f"Tasks completed today: {snapshot.tasks.completed_today}."
    )
