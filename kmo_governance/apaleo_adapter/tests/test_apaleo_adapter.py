"""KMO Apaleo-Adapter Tests [CRUX-MK].

Welle-9-zeta SUBAGENT-A: 12 Pflicht-Tests fuer Apaleo-Adapter SKELETON.

Test-Coverage:
  1. test_mock_auth_token_lifecycle
  2. test_booking_create_returns_id
  3. test_booking_read_after_create
  4. test_booking_update_modifies_state
  5. test_booking_delete_removes
  6. test_retry_on_500_succeeds_eventually
  7. test_rate_limit_backoff_respects_header
  8. test_concurrent_token_refresh_idempotent
  9. test_token_caching_avoids_redundant_calls
 10. test_invalid_credentials_raises_auth_error
 11. test_network_error_retry_max_3_attempts
 12. test_pagination_handling_returns_correct_page
"""

from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.apaleo_adapter import (
    ApaleoAuthError,
    ApaleoBookingAdapter,
    ApaleoErrorHandler,
    ApaleoMockAuth,
    ApaleoMockServer,
    ApaleoNetworkError,
    ApaleoRateLimitError,
    ApaleoTokenState,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def auth() -> ApaleoMockAuth:
    return ApaleoMockAuth(
        client_id="kmo-mock-client",
        client_secret="kmo-mock-secret",
        default_ttl_s=3600.0,
    )


@pytest.fixture
def server() -> ApaleoMockServer:
    return ApaleoMockServer(
        success_rate=1.0,
        latency_ms=0.0,
        rate_limit_remaining=10000,
    )


@pytest.fixture
def fast_handler() -> ApaleoErrorHandler:
    """ErrorHandler mit minimal-backoff fuer schnelle Retry-Tests."""
    return ApaleoErrorHandler(
        max_retries=3, backoff_base=0.001, max_backoff_s=0.01
    )


@pytest.fixture
def adapter(
    auth: ApaleoMockAuth,
    server: ApaleoMockServer,
    fast_handler: ApaleoErrorHandler,
) -> ApaleoBookingAdapter:
    return ApaleoBookingAdapter(
        server=server, auth=auth, error_handler=fast_handler
    )


# ---------------- Test 1: Token-Lifecycle ----------------


def test_mock_auth_token_lifecycle(auth: ApaleoMockAuth) -> None:
    """get -> valid -> refresh -> expire -> invalid (full lifecycle)."""
    # 1. get_token -> valid
    tok1 = auth.get_token()
    assert isinstance(tok1, ApaleoTokenState)
    assert tok1.access_token.startswith("mock-access-")
    assert auth.is_token_valid(tok1.access_token) is True

    # 2. refresh -> NEW access_token, old still in cache-position-replaced
    tok2 = auth.refresh_token(tok1.refresh_token)
    assert tok2.access_token != tok1.access_token
    assert tok2.refresh_token != tok1.refresh_token
    assert auth.is_token_valid(tok2.access_token) is True
    # Old token revoked by refresh
    assert auth.is_token_valid(tok1.access_token) is False

    # 3. expire current -> invalid
    assert auth.expire_token(tok2.access_token) is True
    assert auth.is_token_valid(tok2.access_token) is False

    # 4. Token immutability (frozen-dataclass)
    with pytest.raises(Exception):
        tok2.access_token = "tampered"  # type: ignore[misc]


# ---------------- Test 2: Create Returns ID ----------------


def test_booking_create_returns_id(adapter: ApaleoBookingAdapter) -> None:
    """create_booking returns dict with booking_id + provenance_hash."""
    rec = adapter.create_booking(
        hotel_id="apaleo-eu-001",
        guest_data={"name": "Klaus Mueller", "email": "k@example.com"},
        check_in="2026-06-01",
        check_out="2026-06-05",
    )
    assert "booking_id" in rec
    assert rec["booking_id"].startswith("bkg-apaleo-eu-001-")
    assert rec["hotel_id"] == "apaleo-eu-001"
    assert rec["status"] == "confirmed"
    assert "provenance_hash" in rec
    assert len(rec["provenance_hash"]) == 16


# ---------------- Test 3: Read After Create ----------------


def test_booking_read_after_create(adapter: ApaleoBookingAdapter) -> None:
    """read_booking returns same record after create."""
    created = adapter.create_booking(
        hotel_id="apaleo-eu-002",
        guest_data={"name": "Anna"},
        check_in="2026-07-01",
        check_out="2026-07-03",
    )
    bid = created["booking_id"]
    read = adapter.read_booking(hotel_id="apaleo-eu-002", booking_id=bid)
    assert read["booking_id"] == bid
    assert read["guest"]["name"] == "Anna"
    assert read["check_in"] == "2026-07-01"
    assert "provenance_hash" in read


# ---------------- Test 4: Update Modifies State ----------------


def test_booking_update_modifies_state(adapter: ApaleoBookingAdapter) -> None:
    """update_booking modifies state, hotel_id-mutation forbidden."""
    created = adapter.create_booking(
        hotel_id="hotel-A",
        guest_data={"name": "Bob"},
        check_in="2026-08-01",
        check_out="2026-08-02",
    )
    bid = created["booking_id"]
    # Legitimate update
    updated = adapter.update_booking(
        hotel_id="hotel-A",
        booking_id=bid,
        updates={"status": "checked_in", "room_number": "101"},
    )
    assert updated["status"] == "checked_in"
    assert updated["room_number"] == "101"
    assert updated["hotel_id"] == "hotel-A"  # unchanged

    # Attempted hotel_id-mutation: silently dropped (Multi-Tenancy invariant)
    updated2 = adapter.update_booking(
        hotel_id="hotel-A",
        booking_id=bid,
        updates={"hotel_id": "hotel-B-evil", "notes": "x"},
    )
    assert updated2["hotel_id"] == "hotel-A"
    assert updated2["notes"] == "x"


# ---------------- Test 5: Delete Removes ----------------


def test_booking_delete_removes(adapter: ApaleoBookingAdapter) -> None:
    """delete_booking removes booking; subsequent read raises KeyError."""
    created = adapter.create_booking(
        hotel_id="hotel-X",
        guest_data={"name": "Carl"},
        check_in="2026-09-01",
        check_out="2026-09-02",
    )
    bid = created["booking_id"]
    assert adapter.delete_booking(hotel_id="hotel-X", booking_id=bid) is True
    with pytest.raises(KeyError):
        adapter.read_booking(hotel_id="hotel-X", booking_id=bid)
    # Idempotent: deleting again returns False
    assert adapter.delete_booking(hotel_id="hotel-X", booking_id=bid) is False


# ---------------- Test 6: Retry on 500 ----------------


def test_retry_on_500_succeeds_eventually(
    adapter: ApaleoBookingAdapter, server: ApaleoMockServer
) -> None:
    """Server returns 500 twice, then 200; retry_on_5xx eventually succeeds."""
    # 2 forced 500s, then success
    server.set_forced_status_sequence([500, 500])
    rec = adapter.create_booking(
        hotel_id="retry-hotel",
        guest_data={"name": "Resilient"},
        check_in="2026-10-01",
        check_out="2026-10-02",
    )
    assert rec["hotel_id"] == "retry-hotel"
    # ErrorHandler should have made 3 attempts (2 fails + 1 success)
    assert adapter.error_handler.last_attempt_count == 3


# ---------------- Test 7: Rate Limit Backoff Respects Header ----------------


def test_rate_limit_backoff_respects_header() -> None:
    """rate_limit_backoff sleeps for retry_after_header seconds."""
    handler = ApaleoErrorHandler(
        max_retries=0, backoff_base=0.001, max_backoff_s=10.0
    )
    start = time.monotonic()
    handler.rate_limit_backoff(0.05)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04  # Allow scheduling slack

    # Negative header rejected
    with pytest.raises(ValueError):
        handler.rate_limit_backoff(-1.0)

    # Clamp test: max_backoff_s caps oversized header
    handler2 = ApaleoErrorHandler(
        max_retries=0, backoff_base=0.001, max_backoff_s=0.02
    )
    start2 = time.monotonic()
    handler2.rate_limit_backoff(5.0)  # Would sleep 5s without cap
    elapsed2 = time.monotonic() - start2
    assert elapsed2 < 1.0  # Cap should hold


# ---------------- Test 8: Concurrent Token Refresh Idempotent ----------------


def test_concurrent_token_refresh_idempotent(auth: ApaleoMockAuth) -> None:
    """Concurrent get_token() calls don't multi-mint (RLock-protected)."""
    # First call mints token
    initial = auth.get_token()
    assert auth.auth_call_count() == 1

    # Spawn 10 threads all calling get_token concurrently
    tokens: list[ApaleoTokenState] = []
    lock = threading.Lock()

    def worker() -> None:
        t = auth.get_token()
        with lock:
            tokens.append(t)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should get the SAME cached token (no re-mint)
    assert len(tokens) == 10
    assert all(t.access_token == initial.access_token for t in tokens)
    # auth_call_count unchanged (still 1)
    assert auth.auth_call_count() == 1


# ---------------- Test 9: Token Caching Avoids Redundant Calls ----------------


def test_token_caching_avoids_redundant_calls(auth: ApaleoMockAuth) -> None:
    """Multiple get_token() calls within TTL return cached token."""
    assert auth.auth_call_count() == 0
    t1 = auth.get_token()
    assert auth.auth_call_count() == 1
    t2 = auth.get_token()
    t3 = auth.get_token()
    # Same token returned (cache hit)
    assert t1.access_token == t2.access_token == t3.access_token
    # Counter stayed at 1 (no re-mint)
    assert auth.auth_call_count() == 1


# ---------------- Test 10: Invalid Credentials ----------------


def test_invalid_credentials_raises_auth_error(auth: ApaleoMockAuth) -> None:
    """authenticate() with wrong creds raises ApaleoAuthError."""
    with pytest.raises(ApaleoAuthError):
        auth.authenticate(client_id="evil-client", client_secret="x")
    with pytest.raises(ApaleoAuthError):
        auth.authenticate(
            client_id="kmo-mock-client", client_secret="wrong-secret"
        )

    # refresh with bogus refresh_token
    with pytest.raises(ApaleoAuthError):
        auth.refresh_token("bogus-refresh-token")

    # empty refresh_token
    with pytest.raises(ApaleoAuthError):
        auth.refresh_token("")


# ---------------- Test 11: Network Error Retry Max 3 ----------------


def test_network_error_retry_max_3_attempts(
    adapter: ApaleoBookingAdapter, server: ApaleoMockServer
) -> None:
    """After max_retries=3 exhausted, ApaleoNetworkError propagates."""
    # 4 forced 500s -> handler does 1 initial + 3 retries = 4 attempts total
    # last attempt still fails -> propagate
    server.set_forced_status_sequence([500, 500, 500, 500])
    with pytest.raises(ApaleoNetworkError):
        adapter.create_booking(
            hotel_id="fail-hotel",
            guest_data={"name": "Doomed"},
            check_in="2026-11-01",
            check_out="2026-11-02",
        )
    # Verify exactly 4 attempts made (max_retries=3 means 1 + 3 retries)
    assert adapter.error_handler.last_attempt_count == 4


# ---------------- Test 12: Pagination Returns Correct Page ----------------


def test_pagination_handling_returns_correct_page(
    adapter: ApaleoBookingAdapter,
) -> None:
    """list_bookings respects page + page_size + Multi-Tenancy."""
    hotel = "pag-hotel-001"
    # Create 7 bookings in our hotel + 3 in a different hotel (Multi-Tenancy noise)
    for i in range(7):
        adapter.create_booking(
            hotel_id=hotel,
            guest_data={"name": f"Guest-{i}"},
            check_in="2026-12-01",
            check_out="2026-12-02",
        )
    for i in range(3):
        adapter.create_booking(
            hotel_id="other-hotel",
            guest_data={"name": f"Other-{i}"},
            check_in="2026-12-01",
            check_out="2026-12-02",
        )

    # Page 1 with size 3 -> 3 items, has_next True
    p1 = adapter.list_bookings(hotel_id=hotel, page=1, page_size=3)
    assert len(p1["items"]) == 3
    assert p1["total"] == 7
    assert p1["has_next"] is True
    assert p1["page"] == 1
    # Page 2: 3 items
    p2 = adapter.list_bookings(hotel_id=hotel, page=2, page_size=3)
    assert len(p2["items"]) == 3
    assert p2["has_next"] is True
    # Page 3: 1 item, has_next False
    p3 = adapter.list_bookings(hotel_id=hotel, page=3, page_size=3)
    assert len(p3["items"]) == 1
    assert p3["has_next"] is False

    # Multi-Tenancy: only our hotel's bookings appear
    all_items = p1["items"] + p2["items"] + p3["items"]
    assert all(it["hotel_id"] == hotel for it in all_items)
    assert len(all_items) == 7

    # Cross-Hotel-Isolation: querying other-hotel sees only its 3
    p_other = adapter.list_bookings(
        hotel_id="other-hotel", page=1, page_size=50
    )
    assert p_other["total"] == 3
    assert all(it["hotel_id"] == "other-hotel" for it in p_other["items"])


# CRUX-MK
