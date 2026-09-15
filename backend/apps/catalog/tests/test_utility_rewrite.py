from apps.catalog.utility_rewrite import (
    local_rewrite,
    looks_like_marketing,
    _normalise_suggestion,
)


def test_promo_copy_is_marketing():
    assert looks_like_marketing("NEW PHASE OF VILLAS starting from AED 14M")
    assert looks_like_marketing("Limited time offer — book now")


def test_appointment_copy_is_not_marketing():
    assert not looks_like_marketing(
        "Hello Ahmed, your viewing is confirmed for Tuesday 11:00 at The Oasis."
    )


def test_drops_marketing_suggestion():
    assert _normalise_suggestion(
        {"name": "oasis_launch", "body": "New launch — limited time offer"},
        1,
    ) is None


def test_keeps_utility_suggestion():
    row = _normalise_suggestion(
        {
            "name": "Viewing Confirmed!",
            "body": "Hello {{1}}, your viewing is {{2}}.",
            "body_examples": {"1": "Ahmed", "2": "Tue 11:00"},
            "buttons": [{"type": "QUICK_REPLY", "text": "Confirm"}],
        },
        1,
    )
    assert row["name"] == "viewing_confirmed"
    assert row["body_examples"]["1"] == "Ahmed"
    assert row["buttons"][0]["text"] == "Confirm"


def test_local_rewrite_stays_on_viewing_draft():
    rows, analysis, marketing = local_rewrite(
        body="Hello Ahmed, your viewing at The Oasis is confirmed for Tuesday 11:00.",
        name="oasis_viewing",
    )
    assert not marketing
    assert 1 <= len(rows) <= 2
    joined = " ".join(row["body"] for row in rows).lower()
    assert "document" not in joined
    assert "payment" not in joined
    facts = " ".join(value for row in rows for value in row["body_examples"].values())
    assert "Oasis" in facts
    assert "draft" in analysis.lower()


def test_local_rewrite_does_not_invent_jobs_from_promo():
    rows, analysis, marketing = local_rewrite(
        body="NEW PHASE OF VILLAS starting from AED 14M. Book now at Dubai Hills!",
        name="hills_launch",
    )
    assert marketing
    assert len(rows) == 1
    assert rows[0]["name"] not in {
        "viewing_confirmed",
        "documents_needed",
        "callback_scheduled",
        "payment_received",
    }
    assert "no existing transaction" in analysis.lower()
