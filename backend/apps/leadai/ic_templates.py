"""The International City mixed campaign template (2e spec §7, board Q34), as the Template
Center's composer would fill it in.

``intl_city_property_reconnect`` (MARKETING, en): for Matloob to pick in the CRM popup when a
campaign holds shop, studio and one-bedroom leads together. Quick replies [Yes, still looking]
[Not now] [Stop messages]. No header.

The figures are the "from" prices the bot quotes: studios Q41 (AED 29,000), one-bedrooms Q27
(AED 40,000), shops the shops facts' cheapest Type 1 when the template is submitted. Never "we
have" (there is no inventory, D13) and never shops for sale (the shop facts sell none). The
command submit_ic_templates submits it through apps.catalog's own create. Until batch 2e is live,
the engine treats every campaign template as a shops one, so this template must not be SENT
before then, even once Meta approves it.
"""

from __future__ import annotations

from .assistant import shops

MIXED_NAME = "intl_city_property_reconnect"
NAMES = (MIXED_NAME,)
CATEGORY = "MARKETING"
LANGUAGE = "en"
MIXED_BUTTONS = ("Yes, still looking", "Not now", "Stop messages")
# Meta reviews the finished sentence: one sample per placeholder.
MIXED_EXAMPLES = {"1": "Sumon", "2": "Malik"}

STUDIO_FROM = 29000  # Q41 (2026-10-17)
ONE_BR_FROM = 40000  # Q27

MIXED_BODY = (
    "Hi {{{{1}}}}, this is {{{{2}}}} from AR Properties. You asked us earlier about a property in International City. "
    "We can help you rent or buy a studio or a one-bedroom apartment there, or rent a shop: studios from around AED "
    "{studio_from} a year, one-bedrooms from around AED {one_br_from} a year and shops from AED {shop_from} a year. "
    "Are you still looking?"
)


def figures(facts) -> dict:
    """The three "from" prices as the template writes them ("29,000")."""
    small = shops.types_of(facts)[0]
    return {"studio_from": f"{STUDIO_FROM:,}", "one_br_from": f"{ONE_BR_FROM:,}", "shop_from": f"{small.cheapest:,}"}


def mixed_body(facts) -> str:
    """The body, {{1}} the first name and {{2}} who writes."""
    return MIXED_BODY.format(**figures(facts))


def mixed_form(facts) -> dict:
    """The template as the composer sends it (catalog.views._parse_template_form)."""
    return {
        "name": MIXED_NAME,
        "category": CATEGORY,
        "language": LANGUAGE,
        "body_text": mixed_body(facts),
        "body_examples": dict(MIXED_EXAMPLES),
        "buttons": [{"type": "QUICK_REPLY", "text": label} for label in MIXED_BUTTONS],
    }


def kind(name: str) -> str:
    """'mixed' for the mixed template, 'shop' for every other campaign template (2e spec §6.1)."""
    return "mixed" if str(name or "").strip() == MIXED_NAME else "shop"
