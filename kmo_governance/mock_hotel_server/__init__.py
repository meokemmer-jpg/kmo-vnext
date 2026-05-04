"""KMO Mock-Hotel-Server [CRUX-MK].

Welle-9zeta E2E Pre-Production: In-Process Mock-Server fuer hotel-PMS-API-Simulation.

Bio-Aequivalent: Synthetisches Tissue-Sample fuer In-Vitro-Tests. Verhaelt sich
wie echtes Tissue (real-Apaleo / real-Mews), aber kontrolliert + observable.

Anorg-Mapping: A-19 Phantom-Substrat (Test-Wafer fuer Lithografie). Disposable
Probe-Konfiguration mit deterministischer Seed-Reproduzierbarkeit.

Komponenten:
  - MockHotelStateMachine: Booking-Lifecycle-Transitions (PENDING->...->terminal)
  - MockHotelStorage: In-Memory Multi-Tenant-Storage mit hotel_id-Isolation
  - MockOAuth2Provider: OAuth2-Token-Lifecycle (generate/validate/refresh/revoke)
  - MockRateLimiter: Token-Bucket-Algorithmus pro hotel_id

Verwendung:
  Apaleo-Auth-Adapter (Subagent-A) ruft Mock-Hotel-Server-API auf,
  Apaleo-Layer ist nur Translation. Kein HTTP-Server (in-Process via Function-Calls).

Pre-Conditions:
  - Keine externen Dependencies (stdlib only)
  - Race-safe (threading.Lock fuer alle State-Mutations)
  - GDPR-konform (data_minimization)

Post-Conditions:
  - 305+ bestehende Tests bleiben passing (Backwards-Compat)
  - 10 neue Tests passing
"""

from __future__ import annotations

from .mock_hotel_server import (
    BookingState,
    InvalidStateTransitionError,
    MockHotelStateMachine,
    MockHotelStorage,
    MockOAuth2Provider,
    MockRateLimiter,
    RateLimitExceededError,
    TokenInvalidError,
)

__all__ = [
    "BookingState",
    "InvalidStateTransitionError",
    "MockHotelStateMachine",
    "MockHotelStorage",
    "MockOAuth2Provider",
    "MockRateLimiter",
    "RateLimitExceededError",
    "TokenInvalidError",
]

# CRUX-MK
