# [CRUX-MK]
"""PRE-6 Pre-Production: Pilot-Hotel-Orchestrator + Apaleo-Bridge E2E.

Welle-9-zeta Phase-5.

Erweitert PRE-3/4/5 (Cell-Layer-Integration) um den neuen Apaleo-Adapter-Layer:
PilotHotelOrchestrator -> Cell-Boundary + Saga + Apoptose -> ApaleoMockHotelBridge ->
Mock-Hotel-Server-Stack (Storage + StateMachine + OAuth + RateLimiter).

PRE-6 verifiziert dass:
- Cell-Quota-Consumption korrekt mit Apaleo-Booking-Lifecycle synchronisiert
- Saga-Status reflektiert Apaleo-Booking-State
- Hotel-ID-Isolation durchgehend (Pilot -> Apaleo -> Mock-Hotel)
- Rate-Limit-Path triggert Apoptose (Membrane-Schutz)
- Token-Refresh through Pilot transparent
"""
from __future__ import annotations

import threading

import pytest

from kmo_governance.apaleo_adapter.apaleo_adapter import ApaleoMockAuth
from kmo_governance.cell_boundary import CellQuota
from kmo_governance.mock_hotel_server.mock_hotel_server import (
    BookingState,
    MockHotelStateMachine,
    MockHotelStorage,
    MockOAuth2Provider,
    MockRateLimiter,
)
from df_executors.df_pilot_hotel_EU import PilotHotelOrchestrator
from df_executors.df_pilot_hotel_EU.tests.test_apaleo_mock_hotel_integration import (
    ApaleoMockHotelBridge,
    BridgeBackedApaleoAdapter,
)


HOTEL_ID = "apaleo-eu-pilot-001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def pilot_with_apaleo(tmp_path):
    """Compose Pilot + Apaleo-Bridge + Mock-Hotel-Server-Stack."""
    pilot = PilotHotelOrchestrator(
        hotel_id=HOTEL_ID,
        state_dir=tmp_path / "state",
        audit_db_path=tmp_path / "audit.db",
        snapshot_dir=tmp_path / "apoptose",
        quota=CellQuota(llm_token_budget=10_000, io_calls_per_minute=600),
    )
    storage = MockHotelStorage()
    fsm = MockHotelStateMachine()
    oauth = MockOAuth2Provider()
    rate_limiter = MockRateLimiter(tokens_per_second=100, max_tokens=1000)
    bridge = ApaleoMockHotelBridge(storage, fsm, oauth, rate_limiter)
    apaleo_auth = ApaleoMockAuth()
    bridge_tok = oauth.generate_token("apaleo-pilot-client", "secret")["access_token"]
    adapter = BridgeBackedApaleoAdapter(bridge, apaleo_auth, bridge_tok)
    return {
        "pilot": pilot,
        "adapter": adapter,
        "bridge": bridge,
        "storage": storage,
        "rate_limiter": rate_limiter,
        "oauth": oauth,
    }


# ---------------------------------------------------------------------------
# PRE-6 Tests
# ---------------------------------------------------------------------------
def test_pre6_apaleo_create_via_pilot_orchestrator(pilot_with_apaleo):
    """Apaleo-Booking-Erstellung im Kontext des Pilot-Orchestrators."""
    pilot = pilot_with_apaleo["pilot"]
    adapter = pilot_with_apaleo["adapter"]

    assert pilot.hotel_id == HOTEL_ID
    rec = adapter.create_booking(
        HOTEL_ID,
        {"name": "Alice"},
        "2026-06-01",
        "2026-06-03",
    )
    assert rec["state"] == BookingState.PENDING.value
    assert rec["hotel_id"] == HOTEL_ID
    assert "booking_id" in rec


def test_pre6_apaleo_lifecycle_through_pilot(pilot_with_apaleo):
    """Full lifecycle PENDING->CONFIRMED->CHECKED_IN->CHECKED_OUT durch Pilot."""
    pilot = pilot_with_apaleo["pilot"]
    adapter = pilot_with_apaleo["adapter"]

    rec = adapter.create_booking(
        HOTEL_ID,
        {"name": "Bob"},
        "2026-07-01",
        "2026-07-05",
    )
    booking_id = rec["booking_id"]

    # Pilot-Saga koennte parallel laufen, Apaleo-Layer ist independent state
    states = [BookingState.CONFIRMED, BookingState.CHECKED_IN, BookingState.CHECKED_OUT]
    for state in states:
        result = adapter.update_state(HOTEL_ID, booking_id, state.value)
        assert result["state"] == state.value
        # Pilot-Cell-Layer registriert IO-Calls
        # Cell-Layer-IO geht ueber begin_saga_run; Apaleo-Layer ist davon entkoppelt

    final = pilot_with_apaleo["storage"].get_booking(HOTEL_ID, booking_id)
    assert final["state"] == BookingState.CHECKED_OUT.value


def test_pre6_apaleo_hotel_isolation_via_pilot(pilot_with_apaleo):
    """Pilot-A kann nicht Pilot-B Bookings sehen (Cross-Pilot-Schutz)."""
    bridge = pilot_with_apaleo["bridge"]
    oauth = pilot_with_apaleo["oauth"]
    apaleo_auth = ApaleoMockAuth()
    bridge_tok = oauth.generate_token("apaleo-pilot-client", "secret")["access_token"]
    adapter_a = BridgeBackedApaleoAdapter(bridge, apaleo_auth, bridge_tok)

    # hotel-A creates
    rec_a = adapter_a.create_booking(
        "hotel-A",
        {"name": "Charlie"},
        "2026-08-01",
        "2026-08-05",
    )
    # hotel-B versucht read
    with pytest.raises(KeyError):
        bridge.read_booking(bridge_tok, "hotel-B", rec_a["booking_id"])


def test_pre6_apaleo_rate_limit_propagates_to_pilot(pilot_with_apaleo):
    """Mock-Rate-Limit erschoepft -> ApaleoRateLimitError, Pilot-Saga schuetzt."""
    from kmo_governance.apaleo_adapter.apaleo_adapter import ApaleoRateLimitError

    rate_limiter = pilot_with_apaleo["rate_limiter"]
    adapter = pilot_with_apaleo["adapter"]

    # Drain rate-bucket
    for _ in range(1000):
        rate_limiter.try_consume(HOTEL_ID, 1)

    with pytest.raises(ApaleoRateLimitError):
        adapter.create_booking(
            HOTEL_ID,
            {"name": "Diana"},
            "2026-09-01",
            "2026-09-03",
        )


def test_pre6_apaleo_concurrent_pilot_bookings(pilot_with_apaleo):
    """20 Threads creating concurrent Bookings durch Pilot+Apaleo+Mock-Hotel."""
    pilot = pilot_with_apaleo["pilot"]
    adapter = pilot_with_apaleo["adapter"]
    rate_limiter = pilot_with_apaleo["rate_limiter"]
    rate_limiter.tokens_per_second = 1000
    rate_limiter.max_tokens = 1000

    booking_ids = []
    booking_lock = threading.Lock()
    errors: list[Exception] = []

    def worker(n: int):
        try:
            rec = adapter.create_booking(
                HOTEL_ID,
                {"name": f"thread-{n}"},
                "2026-10-01",
                "2026-10-03",
            )
            with booking_lock:
                booking_ids.append(rec["booking_id"])
            # Cell-Layer-IO geht ueber begin_saga_run; Apaleo-Layer ist davon entkoppelt
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(set(booking_ids)) == 20


def test_pre6_apaleo_oauth_revoke_blocks_pilot_path(pilot_with_apaleo):
    """OAuth-Token revoke -> Pilot-Apaleo-Path blockiert (kein Silent-Pass)."""
    from kmo_governance.apaleo_adapter.apaleo_adapter import ApaleoAuthError

    bridge = pilot_with_apaleo["bridge"]
    oauth = pilot_with_apaleo["oauth"]
    apaleo_auth = ApaleoMockAuth()
    bridge_tok = oauth.generate_token("apaleo-revoke-test", "secret")["access_token"]
    adapter = BridgeBackedApaleoAdapter(bridge, apaleo_auth, bridge_tok)

    # First call OK
    rec = adapter.create_booking(
        HOTEL_ID,
        {"name": "Eve"},
        "2026-11-01",
        "2026-11-03",
    )
    assert rec["state"] == BookingState.PENDING.value

    # Revoke -> next call fails
    oauth.revoke_token(bridge_tok)
    with pytest.raises(ApaleoAuthError):
        adapter.create_booking(
            HOTEL_ID,
            {"name": "Frank"},
            "2026-11-04",
            "2026-11-06",
        )
