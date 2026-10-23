"""Set whom a client on the way is told to call (assistant/filters.on_my_way), as the AI settings dialog would.

Run through `ops/wa.sh set-leadai-visit-contact "NAME" PHONE ["BACKUP NAME" BACKUP_PHONE]`: the verb passes the
four as environment variables and pipes this file into `manage.py shell` in the web container. Names are cleaned the
way the settings view cleans them (one line, no markup), phones kept as digits with the country code, and the change
is recorded in the settings history. Two empty backup values clear the backup; the contact itself is cleared from the
AI settings dialog (the verb always takes a name and a phone).
"""

import os

from django.utils import timezone

from apps.leadai.assistant import filters, shops
from apps.leadai.models import LeadAiSettings


def name_of(key: str) -> str:
    text, error = shops.clean_text(os.environ.get(key, ""), shops.AGENT_MAX)
    if error:
        raise SystemExit(f"REFUSED: {key}: {error}")
    return text


def phone_of(key: str) -> str:
    digits = "".join(ch for ch in os.environ.get(key, "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits and (digits.startswith("0") or not 8 <= len(digits) <= 15):
        raise SystemExit(f"REFUSED: {key}: give digits with the country code (8 to 15, no leading 0).")
    return digits


values = {
    "visit_contact_name": name_of("LEADAI_VISIT_NAME"),
    "visit_contact_phone": phone_of("LEADAI_VISIT_PHONE"),
    "visit_contact_backup_name": name_of("LEADAI_VISIT_BACKUP_NAME"),
    "visit_contact_backup_phone": phone_of("LEADAI_VISIT_BACKUP_PHONE"),
}
if bool(values["visit_contact_name"]) != bool(values["visit_contact_phone"]):
    raise SystemExit("REFUSED: the contact needs both a name and a phone (or neither).")
if bool(values["visit_contact_backup_name"]) != bool(values["visit_contact_backup_phone"]):
    raise SystemExit("REFUSED: the backup needs both a name and a phone (or neither).")

row = LeadAiSettings.load()
changes = {key: [str(getattr(row, key) or ""), value] for key, value in values.items() if str(getattr(row, key) or "") != value}
for key, (_, value) in changes.items():
    setattr(row, key, value)
if changes:
    row.history = (list(row.history or []) + [{"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": changes}])[-100:]
    row.save()
for key in values:
    print(f"{key}=", getattr(row, key))
print("changed:", ", ".join(sorted(changes)) or "nothing (already set)")
print("the line a client on the way gets:")
print(filters.on_my_way("en", row.visit_contact()))
