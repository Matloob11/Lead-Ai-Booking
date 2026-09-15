"""Classify Meta / gateway send failures that must never auto-retry."""

from __future__ import annotations

import re

# Meta (and our own) codes that will never succeed on retry within minutes/hours.
PERMANENT_FAIL_CODES = {
    "131049",  # marketing daily cap
    "131026",  # undeliverable / not on WhatsApp
    "130472",  # number in Meta experiment
    "RECIPIENT_MISMATCH",  # Alots resolved a different wa_id (e.g. added 91)
}
_PERMANENT_DETAIL = re.compile(
    r"131049|131026|130472|RECIPIENT_MISMATCH|"
    r"marketing daily cap|Message undeliverable|"
    r"part of an experiment|Gateway resolved",
    re.I,
)
# After this many marketing-cap permanent fails in one campaign, skip the rest
# of the PENDING queue — continuing only burns the same Meta limit.
MARKETING_CAP_PAUSE_AFTER = 12


def is_permanent_send_failure(error_code: str = "", detail: str = "") -> tuple[bool, str]:
    """Return (is_permanent, short_label). Used by retry + webhook reconcile."""
    code = str(error_code or "").strip()
    note = (detail or "").strip()
    if code in PERMANENT_FAIL_CODES:
        return True, permanent_fail_label(code, note)
    if _PERMANENT_DETAIL.search(note):
        guessed = ""
        if "131049" in note or "marketing" in note.lower():
            guessed = "131049"
        elif "undeliverable" in note.lower() or "131026" in note:
            guessed = "131026"
        elif "experiment" in note.lower() or "130472" in note:
            guessed = "130472"
        elif "resolved" in note.lower() or "RECIPIENT_MISMATCH" in note:
            guessed = "RECIPIENT_MISMATCH"
        return True, permanent_fail_label(guessed or code, note)
    return False, ""


def permanent_fail_label(code: str, detail: str = "") -> str:
    code = str(code or "").strip()
    note = (detail or "").strip()
    if code == "131049" or "marketing" in note.lower() or "131049" in note:
        return f"Meta marketing daily cap (131049): {note or 'per-customer daily limit'}"
    if code == "131026" or "undeliverable" in note.lower():
        return note or "Message undeliverable"
    if code == "130472" or "experiment" in note.lower():
        return note or "User's number is part of an experiment"
    if code == "RECIPIENT_MISMATCH" or "resolved" in note.lower():
        return note or "Gateway resolved a different WhatsApp id"
    return note or (f"Permanent failure ({code})" if code else "Permanent failure")
