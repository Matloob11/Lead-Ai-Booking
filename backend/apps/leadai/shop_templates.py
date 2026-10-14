"""The International City shops campaign templates (board T61), as the Template Center's composer
would fill them in.

- Template B, ``intl_city_shops_followup`` (MARKETING, en): the one the automatic follow-ups send
  (followups.py): 72 hours after a shops campaign nobody answered, and on the day a customer asked
  us to check back. Quick replies [Yes, book a viewing] [Not now].
- Template A, ``intl_city_shops_reconnect`` (MARKETING, en, a VIDEO header): for Matloob to pick in
  the CRM popup. Quick replies [Yes, show me shops] [Not now] [Stop messages]. Its header is
  reviewed against the Type 1 video of the Lead AI media library.

The rents are the shops facts' "from" prices (LeadAiSettings.shops_facts) when the template is
submitted, written as 33,000. The command submit_shops_templates submits them (through
apps.catalog's own create, never a Meta call of its own); the eval writes Template B's body from
here, so a customer's answer to it is judged on the same words. Plain functions on plain data.
"""

from __future__ import annotations

from .assistant import shops

FOLLOWUP_NAME = "intl_city_shops_followup"
RECONNECT_NAME = "intl_city_shops_reconnect"
NAMES = (FOLLOWUP_NAME, RECONNECT_NAME)
CATEGORY = "MARKETING"
LANGUAGE = "en"
FOLLOWUP_BUTTONS = ("Yes, book a viewing", "Not now")
RECONNECT_BUTTONS = ("Yes, show me shops", "Not now", "Stop messages")
# Meta reviews the finished sentence: one sample per placeholder.
FOLLOWUP_EXAMPLES = {"1": "Sumon"}
RECONNECT_EXAMPLES = {"1": "Sumon", "2": "Malik"}

FOLLOWUP_BODY = (
    "Hi {{{{1}}}}, just a quick follow-up. Shops in International City are moving fast. Small shops from AED "
    "{small_from}, medium from AED {medium_from}, large from AED {large_from} per year. Would you like to see them "
    "this week?"
)
RECONNECT_BODY = (
    "Hi {{{{1}}}}, this is {{{{2}}}} from AR Properties. Some time ago you asked us about a shop in International City. "
    "We now have new shops available in France, England, China, Russia, Morocco and Persia clusters, from AED "
    "{small_from} per year, payable in 1 to 4 cheques. Are you still looking for a shop?"
)


def figures(facts) -> dict:
    """The three types' "from" prices, as the templates write them ("33,000")."""
    small, medium, large = shops.types_of(facts)[:3]
    return {"small_from": f"{small.cheapest:,}", "medium_from": f"{medium.cheapest:,}", "large_from": f"{large.cheapest:,}"}


def followup_body(facts) -> str:
    """Template B's body, {{1}} for the first name."""
    return FOLLOWUP_BODY.format(**figures(facts))


def reconnect_body(facts) -> str:
    """Template A's body, {{1}} the first name and {{2}} who writes."""
    return RECONNECT_BODY.format(**figures(facts))


def followup_form(facts) -> dict:
    """Template B as the Template Center's composer sends it (catalog.views._parse_template_form)."""
    return {
        "name": FOLLOWUP_NAME,
        "category": CATEGORY,
        "language": LANGUAGE,
        "body_text": followup_body(facts),
        "body_examples": dict(FOLLOWUP_EXAMPLES),
        "buttons": [{"type": "QUICK_REPLY", "text": label} for label in FOLLOWUP_BUTTONS],
    }


def reconnect_form(facts, header_handle: str) -> dict:
    """Template A as the composer sends it, with the video header's sample handle. The handle came
    from the gateway's own upload route, so the create goes through the gateway too."""
    return {
        "name": RECONNECT_NAME,
        "category": CATEGORY,
        "language": LANGUAGE,
        "header_format": "VIDEO",
        "header_handle": header_handle,
        "header_handle_via": "gateway",
        "body_text": reconnect_body(facts),
        "body_examples": dict(RECONNECT_EXAMPLES),
        "buttons": [{"type": "QUICK_REPLY", "text": label} for label in RECONNECT_BUTTONS],
    }


def rendered(body: str, values: dict) -> str:
    """A body with its placeholders filled ("Hi {{1}}" with {"1": "Sumon"}), as a customer reads it."""
    text = body
    for key, value in (values or {}).items():
        text = text.replace("{{%s}}" % key, str(value))
    return text
