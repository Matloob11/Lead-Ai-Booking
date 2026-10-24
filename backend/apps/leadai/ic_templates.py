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
# "Reconnect again" (Matloob 2026-10-22; reconnect.py): one more template to the mixed campaign's customers who never
# refused (never reached, never answered, or quiet since), read by the engine exactly as the mixed template is (kind MIXED:
# the lead context's first answer, the same yes / "Not now" / "Stop messages" taps). One variable: the first name.
AGAIN_NAME = "intl_city_property_reconnect_again"
# Blank-community old leads (2026-10-24): no area named, so the body says Dubai, not International City.
# Read as mixed, like the two above: the lead context answers first, and the same three taps.
ENQUIRY_NAME = "property_enquiry_reconnect"
NAMES = (MIXED_NAME, AGAIN_NAME)
MIXED_NAMES = (MIXED_NAME, AGAIN_NAME, ENQUIRY_NAME)
# The new-lead greet's template (assistant/newlead.py, round 22; Cursor's C68): "Hi {{1}}, thank you for your enquiry
# about {{2}} … Are you still looking?" to a portal lead minutes after it lands. Any template named portal_… is one.
PORTAL_NAME = "portal_enquiry_reply"
PORTAL_PREFIX = "portal_"
# What kind() says of a campaign template (2e spec §6.1). A portal greet is answered for by the lead context first
# (tracks.decide's step 4, as the mixed template's first answer): the first live greet's reply (chat 52745, 2026-10-22,
# a Bayut studio lead asking about the payment plan) ran on the shop track and got the shop types list, because the
# greet read as a shops template (round 22e).
SHOP = "shop"
MIXED = "mixed"
PORTAL = "portal"
# The template names kind() reads as no shops one: Template B never follows them (followups).
NOT_SHOP_NAMES = (MIXED_NAME, PORTAL_NAME, AGAIN_NAME, ENQUIRY_NAME)
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


AGAIN_BODY = (
    "Hi {{{{1}}}}, this is {brand}. You asked us about a property in International City a while ago. We still have shops "
    "to rent, and studios and one-bedroom apartments to rent or buy there, with viewings this week. Are you still looking?"
)
AGAIN_EXAMPLES = {"1": "Sumon"}


def again_body(brand: str) -> str:
    """The reconnect-again body, {{1}} the first name; ``brand`` the AI settings' brand name ("AR Properties")."""
    return AGAIN_BODY.format(brand=" ".join(str(brand or "AR Properties").split()))


def again_form(brand: str) -> dict:
    """The reconnect-again template as the composer sends it (catalog.views._parse_template_form)."""
    return {
        "name": AGAIN_NAME,
        "category": CATEGORY,
        "language": LANGUAGE,
        "body_text": again_body(brand),
        "body_examples": dict(AGAIN_EXAMPLES),
        "buttons": [{"type": "QUICK_REPLY", "text": label} for label in MIXED_BUTTONS],
    }


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
    """'mixed' for the mixed template and its reconnect-again, 'portal' for the new-lead greet's (a name starting
    portal_), 'shop' for every other campaign template (2e spec §6.1)."""
    text = str(name or "").strip()
    if text in MIXED_NAMES:
        return MIXED
    if text.lower().startswith(PORTAL_PREFIX):
        return PORTAL
    return SHOP


def kind_of(message) -> str:
    """kind() of the template a campaign message (or the follow-ups' Template B) went out with: 'shop' when there is
    none, as for any template this module does not name."""
    template = getattr(message, "template", None) if message is not None and getattr(message, "template_id", None) else None
    return kind(getattr(template, "name", "") if template is not None else "")
