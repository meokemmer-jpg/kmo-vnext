from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.google_business_profile_adapter import (
    GBPClient,
    GBPError,
    LocationResult,
    PostUpdateResult,
    ReplyResult,
    ReviewResult,
)


def test_get_location_returns_seeded_location() -> None:
    client = GBPClient()

    location = client.get_location("loc_berlin")

    assert location == LocationResult(
        location_id="loc_berlin",
        name="KMO Berlin",
        address="Invalidenstrasse 1, 10115 Berlin",
        phone="+49 30 000000",
        website="https://example.com",
    )


def test_list_reviews_returns_seeded_reviews() -> None:
    client = GBPClient()

    reviews = client.list_reviews("loc_berlin")

    assert len(reviews) == 2
    assert reviews[0].review_id == "rev_1"
    assert reviews[1].review_id == "rev_2"


def test_reply_to_review_updates_review_reply() -> None:
    client = GBPClient()

    result = client.reply_to_review("loc_berlin", "rev_1", "Thanks for the feedback.")

    assert result == ReplyResult(
        review_id="rev_1",
        location_id="loc_berlin",
        reply="Thanks for the feedback.",
    )
    review = next(item for item in client.list_reviews("loc_berlin") if item.review_id == "rev_1")
    assert review.reply == "Thanks for the feedback."


def test_post_update_creates_update() -> None:
    client = GBPClient()

    update = client.post_update(
        "loc_berlin",
        "Holiday opening hours published.",
        call_to_action_url="https://example.com/hours",
    )

    assert update == PostUpdateResult(
        update_id="upd_1",
        location_id="loc_berlin",
        summary="Holiday opening hours published.",
        call_to_action_url="https://example.com/hours",
    )


def test_list_updates_returns_created_updates() -> None:
    client = GBPClient()

    first = client.post_update("loc_berlin", "First update.")
    second = client.post_update("loc_berlin", "Second update.")

    assert client.list_updates("loc_berlin") == [first, second]


def test_empty_location_id_is_rejected() -> None:
    client = GBPClient()

    with pytest.raises(GBPError, match="location_id"):
        client.get_location("   ")


def test_empty_review_id_is_rejected() -> None:
    client = GBPClient()

    with pytest.raises(GBPError, match="review_id"):
        client.reply_to_review("loc_berlin", "", "Reply text")


def test_empty_reply_is_rejected() -> None:
    client = GBPClient()

    with pytest.raises(GBPError, match="reply"):
        client.reply_to_review("loc_berlin", "rev_1", "")


def test_missing_location_raises_error() -> None:
    client = GBPClient()

    with pytest.raises(GBPError, match="Location not found"):
        client.list_reviews("missing")


def test_missing_review_raises_error() -> None:
    client = GBPClient()

    with pytest.raises(GBPError, match="Review not found"):
        client.reply_to_review("loc_berlin", "missing", "Reply text")


def test_real_backend_switch_is_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KMO_GBP_BACKEND", "real")

    with pytest.raises(NotImplementedError, match="not implemented"):
        GBPClient()


def test_result_dataclasses_are_frozen() -> None:
    location = LocationResult(location_id="loc", name="Name", address="Address")
    review = ReviewResult(
        review_id="rev",
        location_id="loc",
        author="Author",
        rating=5,
        comment="Comment",
    )
    reply = ReplyResult(review_id="rev", location_id="loc", reply="Reply")
    update = PostUpdateResult(update_id="upd", location_id="loc", summary="Summary")

    with pytest.raises(FrozenInstanceError):
        location.name = "Changed"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        review.rating = 1  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        reply.reply = "Changed"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        update.summary = "Changed"  # type: ignore[misc]
