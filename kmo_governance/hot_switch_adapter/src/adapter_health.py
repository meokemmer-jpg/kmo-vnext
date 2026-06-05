# Adapter-Health-Monitor [CRUX-MK]
"""
Adapter-Health pro PMS-Adapter (Apaleo, Mews, Cloudbeds).

Health-Status:
- HEALTHY: alle Checks PASS
- DEGRADED: einzelne Checks FAIL, Adapter funktional
- UNHEALTHY: kritische Checks FAIL, Adapter nicht nutzbar
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class AdapterStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class CircuitState(str, Enum):
    """Circuit-Breaker-State (LC3 Pattern)."""
    CLOSED = "CLOSED"      # alles ok
    OPEN = "OPEN"          # Adapter abgeschaltet
    HALF_OPEN = "HALF_OPEN"  # Test-Call erlaubt


@dataclass
class HealthCheckResult:
    adapter_name: str
    status: AdapterStatus
    latency_ms: float = 0.0
    last_error: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AdapterHealthMonitor:
    """Health-Monitor mit Circuit-Breaker-Logic.

    Pre-Conditions:
        - adapter_name nicht leer
        - threshold_open_after_n_fails >= 1
    """

    def __init__(self, adapter_name: str,
                 threshold_open_after_n_fails: int = 3,
                 half_open_test_interval_s: int = 30) -> None:
        if not adapter_name.strip():
            raise ValueError("adapter_name nicht leer")
        if threshold_open_after_n_fails < 1:
            raise ValueError("threshold >= 1")
        self.adapter_name = adapter_name
        self.threshold = threshold_open_after_n_fails
        self.half_open_interval = half_open_test_interval_s
        self.consecutive_fails = 0
        self.consecutive_successes = 0
        self.circuit_state = CircuitState.CLOSED
        self.last_state_change_ts = time.monotonic()
        self.history: list[HealthCheckResult] = []

    def record_success(self, latency_ms: float = 0.0) -> None:
        """Wird nach erfolgreichem API-Call aufgerufen."""
        self.consecutive_fails = 0
        self.consecutive_successes += 1
        result = HealthCheckResult(
            adapter_name=self.adapter_name,
            status=AdapterStatus.HEALTHY,
            latency_ms=latency_ms,
        )
        self.history.append(result)
        # Half-Open -> Closed nach 1 Erfolg
        if self.circuit_state == CircuitState.HALF_OPEN:
            self.circuit_state = CircuitState.CLOSED
            self.last_state_change_ts = time.monotonic()

    def record_failure(self, error: str = "") -> None:
        self.consecutive_fails += 1
        self.consecutive_successes = 0
        status = AdapterStatus.DEGRADED
        if self.consecutive_fails >= self.threshold:
            status = AdapterStatus.UNHEALTHY
            if self.circuit_state != CircuitState.OPEN:
                self.circuit_state = CircuitState.OPEN
                self.last_state_change_ts = time.monotonic()
        result = HealthCheckResult(
            adapter_name=self.adapter_name,
            status=status, last_error=error,
        )
        self.history.append(result)

    def is_available(self) -> bool:
        """True wenn Adapter benutzbar (CLOSED oder HALF_OPEN)."""
        if self.circuit_state == CircuitState.CLOSED:
            return True
        if self.circuit_state == CircuitState.OPEN:
            # Pruefe ob HALF_OPEN-Zeit erreicht
            elapsed = time.monotonic() - self.last_state_change_ts
            if elapsed >= self.half_open_interval:
                self.circuit_state = CircuitState.HALF_OPEN
                self.last_state_change_ts = time.monotonic()
                return True
            return False
        # HALF_OPEN
        return True

    def force_close(self) -> None:
        """Manueller Reset (z.B. nach Wartung)."""
        self.consecutive_fails = 0
        self.consecutive_successes = 0
        self.circuit_state = CircuitState.CLOSED
        self.last_state_change_ts = time.monotonic()

    def get_status(self) -> AdapterStatus:
        if not self.history:
            return AdapterStatus.UNKNOWN
        return self.history[-1].status
