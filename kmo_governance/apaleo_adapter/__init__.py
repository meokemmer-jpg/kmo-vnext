"""KMO Apaleo-Adapter Module [CRUX-MK].

Welle-9-zeta Phase-5 Modul 5.1: External-Hotel-Stack-Anbindung (SKELETON).

NUR Mock-Pattern + Skeleton fuer E2E-Pre-Production. KEINE Real-Apaleo-Credentials.
Phronesis-Sperr-Liste P6 #5 (Cross-System-Architektur-Wechsel mit Rollback >4h).

Komponenten:
  - ApaleoMockAuth: Mock-OAuth2-Token-Lifecycle
  - ApaleoBookingAdapter: CRUD against Mock-Hotel-Server (hotel_id-scoped)
  - ApaleoErrorHandler: 5xx-Retry + Rate-Limit-Backoff
  - ApaleoMockServer: in-Memory-Mock fuer Tests
  - ApaleoTokenState: Frozen-Dataclass-Auth-State
"""

from .apaleo_adapter import (
    ApaleoAuthError,
    ApaleoBookingAdapter,
    ApaleoErrorHandler,
    ApaleoMockAuth,
    ApaleoMockServer,
    ApaleoNetworkError,
    ApaleoRateLimitError,
    ApaleoTokenState,
)

__all__ = [
    "ApaleoAuthError",
    "ApaleoBookingAdapter",
    "ApaleoErrorHandler",
    "ApaleoMockAuth",
    "ApaleoMockServer",
    "ApaleoNetworkError",
    "ApaleoRateLimitError",
    "ApaleoTokenState",
]

# CRUX-MK
