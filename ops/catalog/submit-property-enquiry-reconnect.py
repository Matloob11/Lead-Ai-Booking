"""Submit property_enquiry_reconnect (MARKETING, en) to the eight sending WABAs.

For Old Leads Before 6 Month whose community is blank. {{1}} first name, {{2}} who writes.
Quick replies match the mixed template so a later reply can be read the same way.
A WABA that already has the name, in any status, is left alone.

SUBMIT_DRY=1 prints the plan and submits nothing.
"""

import os

from apps.catalog.views import _parse_template_form, _submit_template_to_waba
from apps.leadai.management.commands.submit_shops_templates import SENDING_NUMBERS, existing, wabas_for

DRY = os.environ.get("SUBMIT_DRY", "").strip() == "1"
NAME = "property_enquiry_reconnect"
FORM = {
    "name": NAME,
    "category": "MARKETING",
    "language": "en",
    "body_text": (
        "Hi {{1}}, this is {{2}} from AR Properties. You asked us earlier about a property in Dubai. "
        "Are you still looking to rent or buy?"
    ),
    "body_examples": {"1": "Sumon", "2": "Malik"},
    "buttons": [
        {"type": "QUICK_REPLY", "text": "Yes, still looking"},
        {"type": "QUICK_REPLY", "text": "Not now"},
        {"type": "QUICK_REPLY", "text": "Stop messages"},
    ],
}

parsed, error = _parse_template_form(FORM)
if error:
    raise SystemExit(f"form: {error}")
print(NAME + ": " + FORM["body_text"])

targets, problems = wabas_for(list(SENDING_NUMBERS))
for line in problems:
    print("WARN " + line)
if not targets:
    raise SystemExit("no WABA to submit to")

submitted = skipped = failed = 0
for waba, phones in sorted(targets.items()):
    label = "WABA " + waba + " (+" + ", +".join(phones) + ")"
    have = existing(waba, NAME)
    if have:
        skipped += 1
        print(label + ": already " + have + ", left alone")
    elif DRY:
        submitted += 1
        print(label + ": would be submitted")
    else:
        template, err, was_skipped = _submit_template_to_waba(waba, parsed)
        if err:
            failed += 1
            print(label + ": FAILED " + err)
        elif was_skipped:
            skipped += 1
            print(label + ": Meta has it already (" + str(getattr(template, "status", "")) + "), left alone")
        else:
            submitted += 1
            print(label + ": submitted, " + str(template.status) + " at Meta")

verb = "would submit" if DRY else "submitted"
print(f"{verb}={submitted} skipped={skipped} failed={failed}")
if not DRY and failed:
    raise SystemExit(1)
print("SUBMIT_OK")
