"""Set the new-lead greet's settings (apps/leadai/assistant/newlead.py; round 22) from the environment, as the Django admin
form would, and say what they are now: GREET_ON (on/off), GREET_NUMBER (the sending number's digits), GREET_AGENT (the
sender's Bitrix user id), GREET_TEMPLATE (the approved template's name), GREET_HOURS (how old a lead may be). Runs inside
the web container through ``ops/wa.sh leadai-greet-settings``; prints no secret. Checks every value the greet checks
(newlead.settings_ready, greet_template, template_ready) before saving, and refuses a set that could not greet anyone."""

import os

from django.contrib.auth import get_user_model

from apps.catalog.models import WabaNumber
from apps.leadai.assistant import newlead
from apps.leadai.models import LeadAiSettings

on = (os.environ.get("GREET_ON") or "").strip().lower() == "on"
digits = "".join(ch for ch in (os.environ.get("GREET_NUMBER") or "") if ch.isdigit())
bitrix_id = (os.environ.get("GREET_AGENT") or "").strip()
template = (os.environ.get("GREET_TEMPLATE") or "").strip()
hours = int((os.environ.get("GREET_HOURS") or "48").strip() or 48)

row = LeadAiSettings.load()
if not on:
    row.greet_enabled = False
    row.save(update_fields=["greet_enabled", "updated_at"])
    print("greet=off")
else:
    number = WabaNumber.objects.filter(phone_number=digits, is_active=True).first()
    agent = get_user_model().objects.filter(bitrix_user_id=bitrix_id, is_active=True).first()
    problems = []
    if number is None:
        problems.append(f"no active number {digits}")
    if agent is None:
        problems.append(f"no active agent for Bitrix user {bitrix_id}")
    if problems:
        print("REFUSED: " + "; ".join(problems))
    else:
        row.greet_enabled = True
        row.greet_number = number
        row.greet_agent = agent
        row.greet_template = template
        row.greet_within_hours = hours
        why = newlead.settings_ready(row)
        chosen = newlead.greet_template(row) if not why else None
        if not why and chosen is None:
            why = "no approved template of that name on the number's WABA"
        if not why:
            why = newlead.template_ready(chosen)
        if why:
            print(f"REFUSED: {why}")
        else:
            row.save(update_fields=["greet_enabled", "greet_number", "greet_agent", "greet_template", "greet_within_hours", "updated_at"])
            print(
                f"greet=on number={number.phone_number} agent={agent.username} (bitrix {agent.bitrix_user_id}) "
                f"template={chosen.name}/{chosen.language}/{chosen.category} variables={chosen.variable_count} within={hours}h"
            )
row = LeadAiSettings.load()
print(f"now: enabled={row.greet_enabled} number_id={row.greet_number_id} agent_id={row.greet_agent_id} template={row.greet_template!r} within={row.greet_within_hours}h ready={newlead.settings_ready(row) or 'yes'}")
