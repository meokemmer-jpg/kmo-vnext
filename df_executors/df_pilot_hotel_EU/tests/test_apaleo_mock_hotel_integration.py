# [CRUX-MK]
"""Welle-9-zeta Cross-Module Integration: Apaleo-Adapter <-> Mock-Hotel-Server.

Zweck: End-to-End-Verifikation dass beide neue Module zusammenarbeiten.
Pattern: Bridge-Klasse implementiert ApaleoMockServer-Interface, delegiert an
MockHotelStorage + MockHotelStateMachine + MockOAuth2Provider + MockRateLimiter.

Tests:
- E2E Full Lifecycle (PENDING -> CONFIRMED -> CHECKED_IN -> CHECKED_OUT)
- Rate-Limit-Propagation (Mock-Rate-Limiter wirkt durch Apaleo-Layer)
- Token-Refresh-via-MockOAuth2 (Mock-OAuth-Bridge verifiziert)
- Hotel-ID-Isolation Cross-Module (Multi-Tenancy beidseitig enforced)
- Invalid-State-Transition Propagation
- Concurrent-Bookings Race-Safety
"""
from __future__ import annotations

import threading
from typing import Any, Optional

import pytest

from kmo_governance.apaleo_adapter.apaleo_adapter import (
    ApaleoBookingAdapter,
    ApaleoErrorHandler,
    ApaleoMockAuth,
    ApaleoAuthError,
    ApaleoRateLimitError,
)
from kmo_governance.mock_hotel_server.mock_hotel_server import (
    BookingState,
    InvalidStateTransitionError,
    MockHotelStateMachine,
    MockHotelStorage,
    MockOAuth2Provider,
    MockRateLimiter,
    TokenInvalidError,
)


# ---------------------------------------------------------------------------
# Bridge: ApaleoMockServer-Interface ueber Mock-Hotel-Server-Stack
# ---------------------------------------------------------------------------
class ApaleoMockHotelBridge:
    """Bridge implements ApaleoMockServer-Interface using Mock-Hotel-Server.

    Delegates CRUD to MockHotelStorage, OAuth to MockOAuth2Provider,
    Rate-Limiting to MockRateLimiter, State-Transitions to MockHotelStateMachine.

    Pre:
        storage: MockHotelStorage instance
        state_machine: MockHotelStateMachine instance
        oauth: MockOAuth2Provider instance (validates Apaleo-Mock-Tokens)
        rate_limiter: MockRateLimiter instance
    Post:
        - All booking responses contain hotel_id, booking_id, state
        - Auth-Validation via MockOAuth2Provider
        - Rate-Limit returns ApaleoRateLimitError (429-equivalent)
        - State transitions enforced
    """

    def __init__(
        self,
        storage: MockHotelStorage,
        state_machine: MockHotelStateMachine,
        oauth: MockOAuth2Provider,
        rate_limiter: MockRateLimiter,
    ) -> None:
        self.storage = storage
        self.state_machine = state_machine
        self.oauth = oauth
        self.rate_limiter = rate_limiter

    def _check_auth(self, access_token: str) -> None:
        """Validate token via MockOAuth2Provider; raise ApaleoAuthError on failure."""
        if not access_token:
            raise ApaleoAuthError("no token provided")
        if not self.oauth.validate_token(access_token):
            raise ApaleoAuthError(f"invalid token: {access_token[:8]}...")

    def _check_rate(self, hotel_id: str) -> None:
        """Consume 1 token from rate-limiter; raise ApaleoRateLimitError on exhaustion."""
        ok, retry_after_ms = self.rate_limiter.try_consume(hotel_id, 1)
        if not ok:
            raise ApaleoRateLimitError(
                f"rate-limited for {hotel_id}, retry in {retry_after_ms}ms"
            )

    def create_booking(
        self,
        access_token: str,
        hotel_id: str,
        guest_data: dict,
        check_in: str,
        check_out: str,
    ) -> dict:
        self._check_auth(access_token)
        self._check_rate(hotel_id)
        booking_id = self.storage.create_booking(
            hotel_id,
            {
                "guest_data": dict(guest_data),
                "check_in": check_in,
                "check_out": check_out,
                "state": BookingState.PENDING.value,
            },
        )
        rec = self.storage.get_booking(hotel_id, booking_id)
        return {
            "booking_id": booking_id,
            "hotel_id": hotel_id,
            "state": rec["state"],
            "guest_data": dict(rec["guest_data"]),
            "check_in": rec["check_in"],
            "check_out": rec["check_out"],
        }

    def read_booking(self, access_token: str, hotel_id: str, booking_id: str) -> dict:
        self._check_auth(access_token)
        rec = self.storage.get_booking(hotel_id, booking_id)
        if rec is None:
            raise KeyError(f"booking {booking_id} not found in {hotel_id}")
        return {
            "booking_id": booking_id,
            "hotel_id": hotel_id,
            "state": rec["state"],
            "guest_data": dict(rec["guest_data"]),
            "check_in": rec["check_in"],
            "check_out": rec["check_out"],
        }

    def update_booking(
        self,
        access_token: str,
        hotel_id: str,
        booking_id: str,
        updates: dict,
    ) -> dict:
        self._check_auth(access_token)
        self._check_rate(hotel_id)
        # State-Transition check
        if "state" in updates:
            current = self.storage.get_booking(hotel_id, booking_id)
            if current is None:
                raise KeyError(f"booking {booking_id} not found in {hotel_id}")
            current_state = BookingState(current["state"])
            new_state = BookingState(updates["state"])
            if not self.state_machine.validate_transition(current_state, new_state):
                raise InvalidStateTransitionError(current_state, new_state, booking_id)
        success = self.storage.update_booking(hotel_id, booking_id, updates)
        if not success:
            raise KeyError(f"booking {booking_id} not found")
        rec = self.storage.get_booking(hotel_id, booking_id)
        return {
            "booking_id": booking_id,
            "hotel_id": hotel_id,
            "state": rec["state"],
            "guest_data": dict(rec["guest_data"]),
            "check_in": rec["check_in"],
            "check_out": rec["check_out"],
        }

    def delete_booking(self, access_token: str, hotel_id: str, booking_id: str) -> dict:
        self._check_auth(access_token)
        success = self.storage.delete_booking(hotel_id, booking_id)
        if not success:
            raise KeyError(f"booking {booking_id} not found")
        return {"booking_id": booking_id, "hotel_id": hotel_id, "deleted": True}

    def list_bookings(
        self,
        access_token: str,
        hotel_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> dict:
        self._check_auth(access_token)
        result = self.storage.list_bookings(hotel_id, page=page, page_size=page_size)
        items = []
        for rec in result.get("items", []):
            items.append(
                {
                    "booking_id": rec.get("booking_id", ""),
                    "hotel_id": hotel_id,
                    "state": rec["state"],
                    "guest_data": dict(rec.get("guest_data", {})),
                    "check_in": rec.get("check_in", ""),
                    "check_out": rec.get("check_out", ""),
                }
            )
        return {
            "hotel_id": hotel_id,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": result.get("total", len(items)),
        }


# ---------------------------------------------------------------------------
# ApaleoBookingAdapter-Shim fuer Bridge (anstelle echtem ApaleoMockServer)
# ---------------------------------------------------------------------------
class BridgeBackedApaleoAdapter:
    """Subset des ApaleoBookingAdapter-Interface, ueber Bridge."""

    def __init__(
        self,
        bridge: ApaleoMockHotelBridge,
        auth: ApaleoMockAuth,
        bridge_token: str,
    ) -> None:
        self.bridge = bridge
        self.auth = auth
        # bridge_token: pre-issued via MockOAuth2Provider (one-time-bridge-Auth)
        self.bridge_token = bridge_token

    def create_booking(
        self,
        hotel_id: str,
        guest_data: dict,
        check_in: str,
        check_out: str,
    ) -> dict:
        # Apaleo-Layer authentication still consumed (lifecycle-test)
        self.auth.get_token()
        return self.bridge.create_booking(
            self.bridge_token, hotel_id, guest_data, check_in, check_out
        )

    def update_state(self, hotel_id: str, booking_id: str, new_state: str) -> dict:
        self.auth.get_token()
        return self.bridge.update_booking(
            self.bridge_token, hotel_id, booking_id, {"state": new_state}
        )

    def read(self, hotel_id: str, booking_id: str) -> dict:
        self.auth.get_token()
        return self.bridge.read_booking(self.bridge_token, hotel_id, booking_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def stack():
    """Compose Mock-Hotel-Server-Stack + Apaleo-Auth + Bridge."""
    storage = MockHotelStorage()
    fsm = MockHotelStateMachine()
    oauth = MockOAuth2Provider()
    rate_limiter = MockRateLimiter(tokens_per_second=100, max_tokens=100)
    bridge = ApaleoMockHotelBridge(storage, fsm, oauth, rate_limiter)
    apaleo_auth = ApaleoMockAuth()
    # Pre-issue bridge token (simulates Apaleo<->Hotel-OAuth-Federation)
    bridge_tok = oauth.generate_token("apaleo-client", "secret")["access_token"]
    adapter = BridgeBackedApaleoAdapter(bridge, apaleo_auth, bridge_tok)
    return {
        "storage": storage,
        "fsm": fsm,
        "oauth": oauth,
        "rate_limiter": rate_limiter,
        "bridge": bridge,
        "auth": apaleo_auth,
        "bridge_token": bridge_tok,
        "adapter": adapter,
    }


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------
def test_e2e_full_booking_lifecycle(stack):
    """PENDING -> CONFIRMED -> CHECKED_IN -> CHECKED_OUT through both layers."""
    adapter = stack["adapter"]
    rec = adapter.create_booking(
        "hotel-A",
        {"name": "Alice"},
        "2026-06-01",
        "2026-06-03",
    )
    booking_id = rec["booking_id"]
    assert rec["state"] == BookingState.PENDING.value

    rec2 = adapter.update_state("hotel-A", booking_id, BookingState.CONFIRMED.value)
    assert rec2["state"] == BookingState.CONFIRMED.value

    rec3 = adapter.update_state("hotel-A", booking_id, BookingState.CHECKED_IN.value)
    assert rec3["state"] == BookingState.CHECKED_IN.value

    rec4 = adapter.update_state("hotel-A", booking_id, BookingState.CHECKED_OUT.value)
    assert rec4["state"] == BookingState.CHECKED_OUT.value

    final = adapter.read("hotel-A", booking_id)
    assert final["state"] == BookingState.CHECKED_OUT.value


def test_e2e_rate_limit_propagation(stack):
    """Mock-Hotel-RateLimiter exhausts -> ApaleoRateLimitError propagiert."""
    bridge = stack["bridge"]
    rate_limiter = stack["rate_limiter"]
    bridge_tok = stack["bridge_token"]

    # Drain bucket (max_tokens=100)
    for _ in range(100):
        rate_limiter.try_consume("hotel-A", 1)

    with pytest.raises(ApaleoRateLimitError):
        bridge.create_booking(
            bridge_tok,
            "hotel-A",
            {"name": "Bob"},
            "2026-06-01",
            "2026-06-03",
        )


def test_e2e_invalid_token_raises_apaleo_auth_error(stack):
    """Invalid token to Bridge -> ApaleoAuthError (not silent)."""
    bridge = stack["bridge"]
    with pytest.raises(ApaleoAuthError):
        bridge.create_booking(
            "invalid-token-xyz",
            "hotel-A",
            {"name": "Charlie"},
            "2026-06-01",
            "2026-06-03",
        )


def test_e2e_hotel_id_isolation_cross_module(stack):
    """hotel-A booking unsichtbar fuer hotel-B Read."""
    adapter = stack["adapter"]
    bridge = stack["bridge"]
    bridge_tok = stack["bridge_token"]

    rec_a = adapter.create_booking(
        "hotel-A",
        {"name": "Diana"},
        "2026-06-01",
        "2026-06-03",
    )
    booking_id = rec_a["booking_id"]

    # Cross-Read attempt: hotel-B sucht hotel-A booking
    with pytest.raises(KeyError):
        bridge.read_booking(bridge_tok, "hotel-B", booking_id)


def test_e2e_invalid_state_transition_propagates(stack):
    """CHECKED_OUT (terminal) -> CONFIRMED ist InvalidStateTransitionError."""
    adapter = stack["adapter"]

    rec = adapter.create_booking(
        "hotel-A",
        {"name": "Eve"},
        "2026-06-01",
        "2026-06-03",
    )
    booking_id = rec["booking_id"]
    adapter.update_state("hotel-A", booking_id, BookingState.CONFIRMED.value)
    adapter.update_state("hotel-A", booking_id, BookingState.CHECKED_IN.value)
    adapter.update_state("hotel-A", booking_id, BookingState.CHECKED_OUT.value)

    with pytest.raises(InvalidStateTransitionError):
        adapter.update_state("hotel-A", booking_id, BookingState.CONFIRMED.value)


def test_e2e_concurrent_bookings_race_safety(stack):
    """50 threads creating concurrent bookings -> alle distinct, kein Daten-Loss."""
    adapter = stack["adapter"]
    rate_limiter = stack["rate_limiter"]
    rate_limiter.tokens_per_second = 1000  # raise to allow burst
    rate_limiter.max_tokens = 1000

    booking_ids = []
    booking_ids_lock = threading.Lock()
    errors: list[Exception] = []

    def worker(n: int):
        try:
            rec = adapter.create_booking(
                "hotel-A",
                {"name": f"thread-{n}"},
                "2026-06-01",
                "2026-06-03",
            )
            with booking_ids_lock:
                booking_ids.append(rec["booking_id"])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"thread errors: {errors[:3]}"
    assert len(booking_ids) == 50
    assert len(set(booking_ids)) == 50, "duplicate booking_ids found"


def test_e2e_oauth_token_lifecycle_via_bridge(stack):
    """OAuth-Token von MockOAuth2Provider -> Bridge -> Adapter validiert."""
    oauth = stack["oauth"]
    bridge_tok = stack["bridge_token"]

    # Token initially valid
    assert oauth.validate_token(bridge_tok)

    # Revoke -> further calls fail
    oauth.revoke_token(bridge_tok)
    assert not oauth.validate_token(bridge_tok)

    bridge = stack["bridge"]
    with pytest.raises(ApaleoAuthError):
        bridge.create_booking(
            bridge_tok,
            "hotel-A",
            {"name": "Frank"},
            "2026-06-01",
            "2026-06-03",
        )


def test_e2e_bridge_pagination_metadata(stack):
    """List-Bookings paginiert: 25 inserts, page_size=10, 3 pages."""
    bridge = stack["bridge"]
    bridge_tok = stack["bridge_token"]

    for i in range(25):
        bridge.create_booking(
            bridge_tok,
            "hotel-A",
            {"name": f"guest-{i}"},
            "2026-06-01",
            "2026-06-03",
        )

    page0 = bridge.list_bookings(bridge_tok, "hotel-A", page=0, page_size=10)
    assert len(page0["items"]) == 10
    assert page0["total"] == 25

    page2 = bridge.list_bookings(bridge_tok, "hotel-A", page=2, page_size=10)
    assert len(page2["items"]) == 5  # rest
    assert page2["total"] == 25
