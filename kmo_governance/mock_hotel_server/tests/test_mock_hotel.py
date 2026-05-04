"""KMO Mock-Hotel-Server Tests [CRUX-MK].

Welle-9zeta E2E Pre-Production: 10 Pflicht-Tests fuer Mock-Hotel-Server.

Pflicht-Tests:
  1. test_mock_oauth2_token_lifecycle (generate -> validate -> refresh -> revoke)
  2. test_booking_state_pending_to_confirmed
  3. test_booking_state_invalid_transition_raises (z.B. CANCELLED -> CHECKED_IN)
  4. test_concurrent_booking_create_idempotency (10 threads, gleiche hotel_id, distinct ids)
  5. test_rate_limit_429_response (Token-Bucket erschoepft)
  6. test_token_validation_404_after_revoke
  7. test_hotel_id_isolation (hotel-A kann nicht hotel-B Bookings sehen)
  8. test_pagination_metadata_returns_correct_count
  9. test_state_transition_full_lifecycle (PENDING->CONFIRMED->CHECKED_IN->CHECKED_OUT)
  10. test_storage_stats_per_hotel
"""

from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.mock_hotel_server import (
    BookingState,
    InvalidStateTransitionError,
    MockHotelStateMachine,
    MockHotelStorage,
    MockOAuth2Provider,
    MockRateLimiter,
    TokenInvalidError,
)


# ---------------------------------------------------------------------------
# 1. test_mock_oauth2_token_lifecycle
# ---------------------------------------------------------------------------


def test_mock_oauth2_token_lifecycle() -> None:
    """OAuth2 generate -> validate -> refresh -> revoke."""
    provider = MockOAuth2Provider(default_ttl_s=3600)

    # Generate
    tokens = provider.generate_token(
        client_id="apaleo-mock-client",
        client_secret="secret-xyz",
    )
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["expires_in"] == 3600
    assert tokens["token_type"] == "Bearer"
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    # Validate
    assert provider.validate_token(access) is True
    assert provider.lookup_status(access) == "valid"

    # Refresh -> alter access wird invalidiert, neuer ausgegeben
    new_tokens = provider.refresh(refresh)
    assert new_tokens["access_token"] != access
    assert new_tokens["refresh_token"] != refresh
    # Alter access ist jetzt invalid (revoked)
    assert provider.validate_token(access) is False
    assert provider.lookup_status(access) == "revoked"
    # Neuer access ist valid
    assert provider.validate_token(new_tokens["access_token"]) is True

    # Revoke des neuen access_token
    revoked = provider.revoke_token(new_tokens["access_token"])
    assert revoked is True
    assert provider.validate_token(new_tokens["access_token"]) is False
    assert provider.lookup_status(new_tokens["access_token"]) == "revoked"


# ---------------------------------------------------------------------------
# 2. test_booking_state_pending_to_confirmed
# ---------------------------------------------------------------------------


def test_booking_state_pending_to_confirmed() -> None:
    """PENDING -> CONFIRMED ist gueltige Transition."""
    fsm = MockHotelStateMachine()
    booking = {
        "booking_id": "bk-001",
        "state": BookingState.PENDING.value,
        "guest_name": "K. Werner",
    }
    assert fsm.validate_transition(
        BookingState.PENDING, BookingState.CONFIRMED
    ) is True

    updated = fsm.apply_transition(booking, BookingState.CONFIRMED)
    assert updated["state"] == BookingState.CONFIRMED.value
    assert updated["booking_id"] == "bk-001"
    assert "state_changed_at" in updated
    # Original booking unveraendert (immutability)
    assert booking["state"] == BookingState.PENDING.value


# ---------------------------------------------------------------------------
# 3. test_booking_state_invalid_transition_raises
# ---------------------------------------------------------------------------


def test_booking_state_invalid_transition_raises() -> None:
    """Terminal-State CANCELLED kann nicht zu CHECKED_IN uebergehen."""
    fsm = MockHotelStateMachine()
    booking = {
        "booking_id": "bk-002",
        "state": BookingState.CANCELLED.value,
    }
    assert fsm.validate_transition(
        BookingState.CANCELLED, BookingState.CHECKED_IN
    ) is False

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        fsm.apply_transition(booking, BookingState.CHECKED_IN)
    assert exc_info.value.from_state == BookingState.CANCELLED
    assert exc_info.value.to_state == BookingState.CHECKED_IN
    assert exc_info.value.booking_id == "bk-002"

    # Auch andere ungueltige Transitions
    assert fsm.validate_transition(
        BookingState.CHECKED_OUT, BookingState.CHECKED_IN
    ) is False
    assert fsm.validate_transition(
        BookingState.PENDING, BookingState.CHECKED_OUT
    ) is False


# ---------------------------------------------------------------------------
# 4. test_concurrent_booking_create_idempotency
# ---------------------------------------------------------------------------


def test_concurrent_booking_create_idempotency() -> None:
    """10 Threads erzeugen Bookings parallel -> alle haben distinct IDs."""
    storage = MockHotelStorage()
    hotel_id = "hotel-stress-test"
    n_threads = 10
    booking_ids: list[str] = []
    lock = threading.Lock()

    def create_booking_thread(thread_idx: int) -> None:
        bid = storage.create_booking(
            hotel_id=hotel_id,
            booking_data={"guest_name": f"Guest-{thread_idx}"},
        )
        with lock:
            booking_ids.append(bid)

    threads = [
        threading.Thread(target=create_booking_thread, args=(i,))
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Alle 10 IDs distinct
    assert len(booking_ids) == n_threads
    assert len(set(booking_ids)) == n_threads, (
        f"Expected {n_threads} distinct IDs, got {len(set(booking_ids))}"
    )

    # Storage hat genau 10 Bookings fuer den hotel_id
    listing = storage.list_bookings(hotel_id, page=0, page_size=100)
    assert listing["total"] == n_threads


# ---------------------------------------------------------------------------
# 5. test_rate_limit_429_response
# ---------------------------------------------------------------------------


def test_rate_limit_429_response() -> None:
    """Token-Bucket erschoepft -> success=False, retry_after_ms > 0."""
    # Kleiner Bucket fuer Test (5 tokens, refill 1/s)
    limiter = MockRateLimiter(tokens_per_second=1.0, max_tokens=5.0)
    hotel_id = "hotel-rl-test"

    # 5 erfolgreiche Aufrufe
    for i in range(5):
        success, retry = limiter.try_consume(hotel_id, n_tokens=1)
        assert success is True, f"Call #{i} should succeed"
        assert retry == 0

    # 6. Aufruf -> erschoepft -> 429-aequivalent
    success, retry_ms = limiter.try_consume(hotel_id, n_tokens=1)
    assert success is False
    assert retry_ms > 0, "retry_after_ms must be > 0 when exhausted"
    # Bei 1 token/s und Defizit 1 -> ~1000 ms
    assert 500 <= retry_ms <= 2000, f"retry_ms ~1000 expected, got {retry_ms}"

    # get_remaining sollte 0 sein
    assert limiter.get_remaining(hotel_id) == 0


# ---------------------------------------------------------------------------
# 6. test_token_validation_404_after_revoke
# ---------------------------------------------------------------------------


def test_token_validation_404_after_revoke() -> None:
    """Nach revoke_token liefert validate_token False ('404-aequivalent')."""
    provider = MockOAuth2Provider(default_ttl_s=600)
    tokens = provider.generate_token(
        client_id="client-A",
        client_secret="pw",
    )
    access = tokens["access_token"]

    assert provider.validate_token(access) is True

    revoked = provider.revoke_token(access)
    assert revoked is True
    assert provider.validate_token(access) is False
    assert provider.lookup_status(access) == "revoked"

    # Doppel-Revoke ist idempotent (no-op, returned False)
    second_revoke = provider.revoke_token(access)
    assert second_revoke is False

    # Refresh-Token nach revoke schlaegt fehl
    with pytest.raises(TokenInvalidError):
        provider.refresh(tokens["refresh_token"])


# ---------------------------------------------------------------------------
# 7. test_hotel_id_isolation
# ---------------------------------------------------------------------------


def test_hotel_id_isolation() -> None:
    """hotel-A kann hotel-B-Bookings nicht sehen (Multi-Tenancy-Isolation)."""
    storage = MockHotelStorage()
    bid_a = storage.create_booking(
        hotel_id="hotel-A",
        booking_data={"guest_name": "Alice"},
    )
    bid_b = storage.create_booking(
        hotel_id="hotel-B",
        booking_data={"guest_name": "Bob"},
    )

    # Booking-A nur fuer hotel-A sichtbar
    assert storage.get_booking("hotel-A", bid_a) is not None
    assert storage.get_booking("hotel-B", bid_a) is None
    # Booking-B nur fuer hotel-B sichtbar
    assert storage.get_booking("hotel-B", bid_b) is not None
    assert storage.get_booking("hotel-A", bid_b) is None

    # Listing pro hotel_id liefert nur eigene Bookings
    listing_a = storage.list_bookings("hotel-A", page=0, page_size=10)
    assert listing_a["total"] == 1
    assert listing_a["items"][0]["booking_id"] == bid_a
    assert listing_a["items"][0]["guest_name"] == "Alice"

    listing_b = storage.list_bookings("hotel-B", page=0, page_size=10)
    assert listing_b["total"] == 1
    assert listing_b["items"][0]["booking_id"] == bid_b

    # Update auf falschem hotel_id schlaegt fehl
    ok = storage.update_booking(
        hotel_id="hotel-A",
        booking_id=bid_b,
        updates={"guest_name": "INVADER"},
    )
    assert ok is False
    # Original-Booking unveraendert
    assert (
        storage.get_booking("hotel-B", bid_b)["guest_name"]
        == "Bob"
    )

    # Delete auf falschem hotel_id schlaegt fehl
    deleted = storage.delete_booking("hotel-A", bid_b)
    assert deleted is False
    # Booking-B existiert weiterhin
    assert storage.get_booking("hotel-B", bid_b) is not None


# ---------------------------------------------------------------------------
# 8. test_pagination_metadata_returns_correct_count
# ---------------------------------------------------------------------------


def test_pagination_metadata_returns_correct_count() -> None:
    """Pagination liefert korrekte total/page/page_size Metadaten."""
    storage = MockHotelStorage()
    hotel_id = "hotel-paged"
    # 25 Bookings erzeugen
    for i in range(25):
        storage.create_booking(
            hotel_id=hotel_id,
            booking_data={"guest_name": f"Guest-{i:02d}"},
        )
        # Time-spreading damit created_at stable sortierbar
        time.sleep(0.0005)

    # Page 0, size 10
    p0 = storage.list_bookings(hotel_id, page=0, page_size=10)
    assert p0["total"] == 25
    assert p0["page"] == 0
    assert p0["page_size"] == 10
    assert len(p0["items"]) == 10

    # Page 1, size 10
    p1 = storage.list_bookings(hotel_id, page=1, page_size=10)
    assert p1["total"] == 25
    assert p1["page"] == 1
    assert len(p1["items"]) == 10

    # Page 2, size 10 -> nur 5 verbleibende
    p2 = storage.list_bookings(hotel_id, page=2, page_size=10)
    assert p2["total"] == 25
    assert p2["page"] == 2
    assert len(p2["items"]) == 5

    # Page 3 -> leer
    p3 = storage.list_bookings(hotel_id, page=3, page_size=10)
    assert p3["total"] == 25
    assert len(p3["items"]) == 0

    # Disjoint check: items in p0 + p1 + p2 = 25 distinct booking_ids
    all_ids = {b["booking_id"] for b in p0["items"]}
    all_ids |= {b["booking_id"] for b in p1["items"]}
    all_ids |= {b["booking_id"] for b in p2["items"]}
    assert len(all_ids) == 25


# ---------------------------------------------------------------------------
# 9. test_state_transition_full_lifecycle
# ---------------------------------------------------------------------------


def test_state_transition_full_lifecycle() -> None:
    """PENDING -> CONFIRMED -> CHECKED_IN -> CHECKED_OUT (Happy-Path)."""
    fsm = MockHotelStateMachine()
    booking = {
        "booking_id": "bk-lifecycle",
        "state": BookingState.PENDING.value,
        "guest_name": "Lifecycle Test",
    }
    # Step 1: PENDING -> CONFIRMED
    booking = fsm.apply_transition(booking, BookingState.CONFIRMED)
    assert booking["state"] == BookingState.CONFIRMED.value
    t1 = booking["state_changed_at"]
    assert t1 > 0

    # Kleine Pause damit timestamps echt monoton wachsen
    time.sleep(0.001)

    # Step 2: CONFIRMED -> CHECKED_IN
    booking = fsm.apply_transition(booking, BookingState.CHECKED_IN)
    assert booking["state"] == BookingState.CHECKED_IN.value
    t2 = booking["state_changed_at"]
    assert t2 >= t1

    time.sleep(0.001)

    # Step 3: CHECKED_IN -> CHECKED_OUT (terminal)
    booking = fsm.apply_transition(booking, BookingState.CHECKED_OUT)
    assert booking["state"] == BookingState.CHECKED_OUT.value
    t3 = booking["state_changed_at"]
    assert t3 >= t2

    # Terminal-State: keine ausgehenden Transitions mehr
    assert fsm.validate_transition(
        BookingState.CHECKED_OUT, BookingState.CHECKED_IN
    ) is False
    with pytest.raises(InvalidStateTransitionError):
        fsm.apply_transition(booking, BookingState.CHECKED_IN)


# ---------------------------------------------------------------------------
# 10. test_storage_stats_per_hotel
# ---------------------------------------------------------------------------


def test_storage_stats_per_hotel() -> None:
    """get_storage_stats liefert booking-counts pro hotel_id."""
    storage = MockHotelStorage()
    # hotel-A: 3 Bookings
    for i in range(3):
        storage.create_booking(
            "hotel-A", {"guest_name": f"A-{i}"}
        )
    # hotel-B: 5 Bookings
    bid_b_first = None
    for i in range(5):
        bid = storage.create_booking(
            "hotel-B", {"guest_name": f"B-{i}"}
        )
        if i == 0:
            bid_b_first = bid
    # hotel-C: 0 Bookings (kein create -> nicht im stats)

    stats = storage.get_storage_stats()
    assert stats == {"hotel-A": 3, "hotel-B": 5}
    assert "hotel-C" not in stats

    # Nach delete sollte counter sinken
    deleted = storage.delete_booking("hotel-B", bid_b_first)
    assert deleted is True
    stats2 = storage.get_storage_stats()
    assert stats2 == {"hotel-A": 3, "hotel-B": 4}


# CRUX-MK
