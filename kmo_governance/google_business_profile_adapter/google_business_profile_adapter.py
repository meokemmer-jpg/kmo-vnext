from __future__ import annotations

from dataclasses import dataclass
import os
import threading
from typing import Any


class GBPError(ValueError):
    """Raised for Google Business Profile adapter errors."""


@dataclass(frozen=True)
class LocationResult:
    location_id: str
    name: str
    address: str
    phone: str | None = None
    website: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    review_id: str
    location_id: str
    author: str
    rating: int
    comment: str
    reply: str | None = None


@dataclass(frozen=True)
class ReplyResult:
    review_id: str
    location_id: str
    reply: str


@dataclass(frozen=True)
class PostUpdateResult:
    update_id: str
    location_id: str
    summary: str
    call_to_action_url: str | None = None


class GBPClient:
    def __init__(
        self,
        *,
        backend: str | None = None,
        seed_data: dict[str, Any] | None = None,
        env_var: str = "KMO_GBP_BACKEND",
    ) -> None:
        self.backend = backend or os.getenv(env_var, "mock")
        self._lock = threading.RLock()

        if self.backend != "mock":
            raise NotImplementedError(
                "Real Google Business Profile API backend is gated but not implemented in MVP."
            )

        self._locations: dict[str, LocationResult] = {}
        self._reviews: dict[str, dict[str, ReviewResult]] = {}
        self._updates: dict[str, dict[str, PostUpdateResult]] = {}
        self._update_seq = 1

        self._load_seed_data(seed_data or self._default_seed_data())

    def get_location(self, location_id: str) -> LocationResult:
        location_id = self._require_text(location_id, "location_id")

        with self._lock:
            try:
                return self._locations[location_id]
            except KeyError as exc:
                raise GBPError(f"Location not found: {location_id}") from exc

    def list_reviews(self, location_id: str) -> list[ReviewResult]:
        location_id = self._require_text(location_id, "location_id")

        with self._lock:
            self.get_location(location_id)
            return list(self._reviews.get(location_id, {}).values())

    def reply_to_review(self, location_id: str, review_id: str, reply: str) -> ReplyResult:
        location_id = self._require_text(location_id, "location_id")
        review_id = self._require_text(review_id, "review_id")
        reply = self._require_text(reply, "reply")

        with self._lock:
            self.get_location(location_id)
            reviews = self._reviews.setdefault(location_id, {})

            try:
                review = reviews[review_id]
            except KeyError as exc:
                raise GBPError(f"Review not found: {review_id}") from exc

            reviews[review_id] = ReviewResult(
                review_id=review.review_id,
                location_id=review.location_id,
                author=review.author,
                rating=review.rating,
                comment=review.comment,
                reply=reply,
            )
            return ReplyResult(review_id=review_id, location_id=location_id, reply=reply)

    def post_update(
        self,
        location_id: str,
        summary: str,
        *,
        call_to_action_url: str | None = None,
    ) -> PostUpdateResult:
        location_id = self._require_text(location_id, "location_id")
        summary = self._require_text(summary, "summary")

        if call_to_action_url is not None:
            call_to_action_url = self._require_text(call_to_action_url, "call_to_action_url")

        with self._lock:
            self.get_location(location_id)
            update_id = f"upd_{self._update_seq}"
            self._update_seq += 1

            update = PostUpdateResult(
                update_id=update_id,
                location_id=location_id,
                summary=summary,
                call_to_action_url=call_to_action_url,
            )
            self._updates.setdefault(location_id, {})[update_id] = update
            return update

    def list_updates(self, location_id: str) -> list[PostUpdateResult]:
        location_id = self._require_text(location_id, "location_id")

        with self._lock:
            self.get_location(location_id)
            return list(self._updates.get(location_id, {}).values())

    def _load_seed_data(self, seed_data: dict[str, Any]) -> None:
        for raw_location in seed_data.get("locations", []):
            location = LocationResult(**raw_location)
            self._locations[location.location_id] = location
            self._reviews.setdefault(location.location_id, {})
            self._updates.setdefault(location.location_id, {})

        for raw_review in seed_data.get("reviews", []):
            review = ReviewResult(**raw_review)
            if review.location_id not in self._locations:
                raise GBPError(f"Review references unknown location: {review.location_id}")
            self._validate_rating(review.rating)
            self._reviews.setdefault(review.location_id, {})[review.review_id] = review

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GBPError(f"{field_name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _validate_rating(rating: int) -> None:
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            raise GBPError("rating must be an integer from 1 to 5")

    @staticmethod
    def _default_seed_data() -> dict[str, Any]:
        return {
            "locations": [
                {
                    "location_id": "loc_berlin",
                    "name": "KMO Berlin",
                    "address": "Invalidenstrasse 1, 10115 Berlin",
                    "phone": "+49 30 000000",
                    "website": "https://example.com",
                }
            ],
            "reviews": [
                {
                    "review_id": "rev_1",
                    "location_id": "loc_berlin",
                    "author": "Ada",
                    "rating": 5,
                    "comment": "Excellent service.",
                },
                {
                    "review_id": "rev_2",
                    "location_id": "loc_berlin",
                    "author": "Max",
                    "rating": 4,
                    "comment": "Good experience.",
                },
            ],
        }
