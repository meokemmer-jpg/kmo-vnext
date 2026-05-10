# [CRUX-MK]
"""HeyLou-Chaos-Engineering Implementation (Welle-43 Phase-36)."""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class OTAFaultType(str, Enum):
    OTA_PROVIDER_TIMEOUT = "ota_provider_timeout"
    PRICE_CALCULATION_OVERFLOW = "price_calculation_overflow"
    INVENTORY_DESYNC = "inventory_desync"
    COMPETITOR_PRICE_FETCH_FAIL = "competitor_price_fetch_fail"
    CURRENCY_RATE_STALE = "currency_rate_stale"


class FaultSeverity(str, Enum):
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HeyLouChaosScenario:
    """Pricing-Pipeline-Fault."""
    scenario_id: str
    fault_type: OTAFaultType
    severity: FaultSeverity
    hotel_id: str
    ota_channel: str  # "booking.com", "expedia", "airbnb", etc.
    duration_s: float

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if not self.hotel_id:
            raise ValueError("hotel_id must be non-empty")
        if not self.ota_channel:
            raise ValueError("ota_channel must be non-empty")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if not isinstance(self.fault_type, OTAFaultType):
            raise TypeError("fault_type must be OTAFaultType")


@dataclass(frozen=True)
class HeyLouChaosOutcome:
    """Outcome with pricing-impact metrics."""
    outcome_id: str
    scenario_id: str
    fault_type: OTAFaultType
    success: bool
    actual_recovery_s: float
    failover_to_alt_channel: bool  # OTA-spezifisch: kollateraler-Kreislauf
    revenue_impact_eur: float
    timestamp: float
    error: Optional[str] = None


class HeyLouChaosEngineering:
    """OTA-Pricing-Failover-Stress-Test."""

    def __init__(
        self,
        max_concurrent_chaos: int = 1,
        max_outcomes_history: int = 100,
    ) -> None:
        if max_concurrent_chaos < 1:
            raise ValueError("max_concurrent_chaos must be >= 1")
        if max_outcomes_history < 0:
            raise ValueError("max_outcomes_history must be >= 0")
        self._max_concurrent = max_concurrent_chaos
        self._lock = threading.RLock()
        self._handlers: dict[str, Callable[[HeyLouChaosScenario], dict]] = {}
        self._outcomes: deque = deque(maxlen=max_outcomes_history)
        self._active_chaos = 0
        self._paused = False

    def register_hotel(
        self,
        hotel_id: str,
        handler: Callable[[HeyLouChaosScenario], dict],
    ) -> None:
        if not hotel_id:
            raise ValueError("hotel_id must be non-empty")
        with self._lock:
            self._handlers[hotel_id] = handler

    def pause_chaos(self) -> None:
        with self._lock:
            self._paused = True

    def resume_chaos(self) -> None:
        with self._lock:
            self._paused = False

    def inject(self, scenario: HeyLouChaosScenario) -> HeyLouChaosOutcome:
        with self._lock:
            if self._paused:
                return self._failed_outcome(scenario, "chaos_paused")
            if scenario.hotel_id not in self._handlers:
                return self._failed_outcome(scenario, "hotel_not_registered")
            if self._active_chaos >= self._max_concurrent:
                return self._failed_outcome(scenario, "max_concurrent_reached")
            self._active_chaos += 1
            handler = self._handlers[scenario.hotel_id]

        outcome_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            result = handler(scenario)
            outcome = HeyLouChaosOutcome(
                outcome_id=outcome_id,
                scenario_id=scenario.scenario_id,
                fault_type=scenario.fault_type,
                success=bool(result.get("success", True)),
                actual_recovery_s=time.monotonic() - start,
                failover_to_alt_channel=bool(result.get("failover_to_alt_channel", False)),
                revenue_impact_eur=float(result.get("revenue_impact_eur", 0.0)),
                timestamp=time.time(),
            )
        except Exception as exc:
            outcome = HeyLouChaosOutcome(
                outcome_id=outcome_id,
                scenario_id=scenario.scenario_id,
                fault_type=scenario.fault_type,
                success=False,
                actual_recovery_s=time.monotonic() - start,
                failover_to_alt_channel=False,
                revenue_impact_eur=0.0,
                timestamp=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )

        with self._lock:
            self._active_chaos -= 1
            self._outcomes.append(outcome)
        return outcome

    def _failed_outcome(self, scenario: HeyLouChaosScenario, reason: str) -> HeyLouChaosOutcome:
        outcome = HeyLouChaosOutcome(
            outcome_id=str(uuid.uuid4()),
            scenario_id=scenario.scenario_id,
            fault_type=scenario.fault_type,
            success=False,
            actual_recovery_s=0.0,
            failover_to_alt_channel=False,
            revenue_impact_eur=0.0,
            timestamp=time.time(),
            error=reason,
        )
        with self._lock:
            self._outcomes.append(outcome)
        return outcome

    def get_outcomes(
        self,
        ota_channel: Optional[str] = None,
    ) -> tuple[HeyLouChaosOutcome, ...]:
        with self._lock:
            outcomes = list(self._outcomes)
        return tuple(outcomes)

    def get_total_revenue_impact_eur(self) -> float:
        with self._lock:
            return sum(o.revenue_impact_eur for o in self._outcomes)


# CRUX-MK
