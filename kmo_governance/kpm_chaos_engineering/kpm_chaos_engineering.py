# [CRUX-MK]
"""KPM-Chaos-Engineering (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Pattern-Lift von kmo_governance.chaos_engineering (Welle-9, Hotel-Domain)
in KPM-Trading-Domain. Kontrollierte Strategy-Faults (Latenz/Order-Reject/
Quote-Hole/Slippage/Exchange-Disconnect) injizieren, Recovery-Time + P&L-Impact
messen, Resilience-Score aggregieren.

Pattern-Isomorphie:
- Hotel-Service           -> Trading-Strategy (target_strategy_id)
- ChaosScenario(steps)    -> ChaosScenario(fault_type, severity, params)
- FailureInjector         -> fault_handler_fn (per-strategy, simuliert Fault)
- ChaosMonkey             -> KPMChaosEngineering (Orchestrator)
- ChaosOutcome (success/failure/recovered) -> ChaosOutcome (success + recovery_time + pnl_impact)
- ResilienceScore         -> get_resilience_score(strategy_id)
- Bio: Innate-Immunity-Stress-Test (Antigen-Exposition + Lymphocyte-Recovery)

Stdlib only (random, time, threading, dataclasses, enum, uuid, typing).
Pattern-Demo, no real money. Kill-Switch via pause_chaos()/resume_chaos().

K_0-Schutz:
- max_concurrent_chaos limitiert parallele Fault-Injections (Default 1)
- pause_chaos blockiert weitere inject()-Calls
- ChaosScenario.params als tuple-of-tuples (frozen, hashable)
- ChaosOutcome frozen (Audit-Trail-Integritaet)
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# Severity-Multipliers (Trading-Domain-Default-Skala)
SEVERITY_LATENCY_MULTIPLIER: dict[str, float] = {
    "minor": 1.0,
    "moderate": 2.5,
    "severe": 6.0,
    "critical": 15.0,
}


class FaultType(str, Enum):
    """Trading-Domain-Fault-Klassen (was kann eine Strategy aushebeln)."""

    LATENCY_SPIKE = "latency_spike"          # Order-Submission-Latenz explodiert
    ORDER_REJECT = "order_reject"            # Broker lehnt Orders ab
    QUOTE_HOLE = "quote_hole"                # Marktdaten-Stream haengt
    SLIPPAGE_BURST = "slippage_burst"        # Realisiertes Fill weit von Quote
    EXCHANGE_DISCONNECT = "exchange_disconnect"  # Voll-Outage des Exchange


class FaultSeverity(str, Enum):
    """Schweregrade der Fault-Injection (skaliert Recovery-Erwartung)."""

    MINOR = "minor"          # transient, Strategy sollte robust durchkommen
    MODERATE = "moderate"    # spuerbar, Recovery in Sekunden erwartet
    SEVERE = "severe"        # signifikant, Recovery in 10s+ erwartet
    CRITICAL = "critical"    # potential-K_0-Risiko, Strategy darf failen


@dataclass(frozen=True)
class ChaosScenario:
    """Immutable Fault-Profil fuer eine kontrollierte Injection.

    Frozen + tuple-params -> hashable + Audit-Trail-fest.

    Pre-Conditions:
    - scenario_id non-empty
    - target_strategy_id non-empty
    - duration_s > 0
    - expected_recovery_s >= 0
    - params: tuple-of-tuples (jeder inner-tuple = (key, value))
    """

    scenario_id: str
    fault_type: FaultType
    severity: FaultSeverity
    target_strategy_id: str
    duration_s: float
    params: tuple[tuple[str, object], ...] = field(default_factory=tuple)
    expected_recovery_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if not self.target_strategy_id:
            raise ValueError("target_strategy_id must be non-empty")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if self.expected_recovery_s < 0:
            raise ValueError("expected_recovery_s must be >= 0")
        if not isinstance(self.fault_type, FaultType):
            raise TypeError("fault_type must be FaultType")
        if not isinstance(self.severity, FaultSeverity):
            raise TypeError("severity must be FaultSeverity")
        if not isinstance(self.params, tuple):
            raise TypeError("params must be a tuple of (key, value) tuples")
        for entry in self.params:
            if not (isinstance(entry, tuple) and len(entry) == 2):
                raise TypeError(
                    "each params entry must be a 2-tuple (key, value)"
                )


@dataclass(frozen=True)
class ChaosOutcome:
    """Immutable Resultat einer Chaos-Injection.

    Frozen -> Audit-Trail kann nicht ex-post manipuliert werden.

    Felder:
    - scenario_id: Verknuepfung zu ChaosScenario
    - success: True wenn Strategy ueberlebte und Recovery innerhalb expected_recovery_s
    - actual_recovery_s: Real gemessene Recovery-Zeit (0.0 wenn nie failed)
    - pnl_impact: Geschaetzter P&L-Hit (kann negativ sein, Pattern-Demo only)
    - observations: Tuple of str (Audit-Notizen aus Handler)
    - timestamp: time.time() bei Outcome-Erstellung
    """

    scenario_id: str
    success: bool
    actual_recovery_s: float
    pnl_impact: float
    observations: tuple[str, ...] = field(default_factory=tuple)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if self.actual_recovery_s < 0:
            raise ValueError("actual_recovery_s must be >= 0")
        if not isinstance(self.observations, tuple):
            raise TypeError("observations must be a tuple of strings")
        for obs in self.observations:
            if not isinstance(obs, str):
                raise TypeError("each observation must be a string")


class KPMChaosEngineering:
    """Orchestrator fuer Trading-Strategy-Chaos-Engineering.

    Pre-Conditions:
    - default_severity: FaultSeverity (Default fuer inject_random)
    - max_concurrent_chaos: int >= 1 (limitiert parallele Injections,
      K_0-Schutz vor Mehrfach-Fault-Storm)

    Post-Conditions:
    - thread-safe (RLock)
    - register_strategy() bindet handler fn an strategy_id
    - inject(scenario) ruft handler synchron auf (innerhalb max_concurrent-Limit)
    - inject_random() generiert zufaelligen Scenario auf bekannter Strategy
    - get_outcomes(strategy_id?) liefert Audit-Trail (immutable tuple)
    - get_resilience_score(strategy_id) liefert success-rate in [0,1] oder 1.0 default
    - pause_chaos() / resume_chaos() globaler Kill-Switch
    """

    def __init__(
        self,
        default_severity: FaultSeverity = FaultSeverity.MINOR,
        max_concurrent_chaos: int = 1,
    ) -> None:
        if not isinstance(default_severity, FaultSeverity):
            raise TypeError("default_severity must be FaultSeverity")
        if max_concurrent_chaos < 1:
            raise ValueError("max_concurrent_chaos must be >= 1")

        self.default_severity = default_severity
        self.max_concurrent_chaos = int(max_concurrent_chaos)

        self._lock = threading.RLock()
        self._strategies: dict[
            str, Callable[[ChaosScenario], ChaosOutcome]
        ] = {}
        self._outcomes: list[ChaosOutcome] = []
        self._scenarios_by_outcome: dict[str, ChaosScenario] = {}
        self._paused: bool = False
        self._active_chaos_count: int = 0
        self._rng = random.Random()

    # -------------- Registration --------------

    def register_strategy(
        self,
        strategy_id: str,
        fault_handler_fn: Callable[[ChaosScenario], ChaosOutcome],
    ) -> None:
        """Bind a fault handler to a strategy_id.

        Handler signature: (ChaosScenario) -> ChaosOutcome.
        Handler is responsible for simulating the fault impact and producing
        a ChaosOutcome with measured recovery_time + pnl_impact.
        """
        if not strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not callable(fault_handler_fn):
            raise TypeError("fault_handler_fn must be callable")
        with self._lock:
            self._strategies[strategy_id] = fault_handler_fn

    # -------------- Injection --------------

    def inject(self, scenario: ChaosScenario) -> ChaosOutcome:
        """Inject scenario via the registered handler. Returns ChaosOutcome.

        Pre-Conditions:
        - scenario.target_strategy_id is registered
        - chaos is not paused
        - active_chaos_count < max_concurrent_chaos

        Post-Conditions:
        - outcome appended to internal audit trail
        - active_chaos_count incremented during call (decremented on return)
        - on handler exception: synthetic failed-outcome recorded with observation
        """
        if not isinstance(scenario, ChaosScenario):
            raise TypeError("scenario must be ChaosScenario")

        with self._lock:
            if self._paused:
                raise RuntimeError("chaos is paused; resume via resume_chaos()")
            if scenario.target_strategy_id not in self._strategies:
                raise KeyError(
                    f"strategy '{scenario.target_strategy_id}' not registered"
                )
            if self._active_chaos_count >= self.max_concurrent_chaos:
                raise RuntimeError(
                    f"max_concurrent_chaos ({self.max_concurrent_chaos}) exceeded"
                )
            self._active_chaos_count += 1
            handler = self._strategies[scenario.target_strategy_id]

        # Call handler outside lock to avoid handler-induced deadlocks.
        # active_chaos_count is still bumped, so concurrent inject() respects cap.
        try:
            outcome = handler(scenario)
            if not isinstance(outcome, ChaosOutcome):
                # Handler protocol violation: treat as critical failure
                outcome = ChaosOutcome(
                    scenario_id=scenario.scenario_id,
                    success=False,
                    actual_recovery_s=0.0,
                    pnl_impact=0.0,
                    observations=(
                        f"handler returned non-ChaosOutcome: "
                        f"{type(outcome).__name__}",
                    ),
                    timestamp=time.time(),
                )
        except Exception as exc:
            outcome = ChaosOutcome(
                scenario_id=scenario.scenario_id,
                success=False,
                actual_recovery_s=0.0,
                pnl_impact=0.0,
                observations=(f"handler raised {type(exc).__name__}: {exc}",),
                timestamp=time.time(),
            )
        finally:
            with self._lock:
                self._active_chaos_count -= 1

        with self._lock:
            self._outcomes.append(outcome)
            self._scenarios_by_outcome[outcome.scenario_id] = scenario
        return outcome

    def inject_random(
        self,
        strategy_id: str,
        fault_type: Optional[FaultType] = None,
        severity: Optional[FaultSeverity] = None,
    ) -> ChaosOutcome:
        """Generate a randomized scenario and inject it.

        Picks a random fault_type if not provided; uses default_severity if
        severity not provided. Returns the resulting ChaosOutcome.
        """
        with self._lock:
            if strategy_id not in self._strategies:
                raise KeyError(f"strategy '{strategy_id}' not registered")

            chosen_fault = (
                fault_type
                if fault_type is not None
                else self._rng.choice(list(FaultType))
            )
            chosen_severity = (
                severity if severity is not None else self.default_severity
            )

            base_latency_ms = 50.0
            multiplier = SEVERITY_LATENCY_MULTIPLIER.get(
                chosen_severity.value, 1.0
            )
            params = (
                ("base_latency_ms", base_latency_ms),
                ("multiplier", multiplier),
                ("rng_seed", self._rng.random()),
            )
            scenario_id = f"random-{uuid.uuid4().hex[:8]}"
            scenario = ChaosScenario(
                scenario_id=scenario_id,
                fault_type=chosen_fault,
                severity=chosen_severity,
                target_strategy_id=strategy_id,
                duration_s=max(1.0, multiplier),
                params=params,
                expected_recovery_s=multiplier,
            )

        return self.inject(scenario)

    # -------------- Inspection --------------

    def get_outcomes(
        self, strategy_id: Optional[str] = None
    ) -> tuple[ChaosOutcome, ...]:
        """Return outcomes (filtered by strategy_id if given) as immutable tuple."""
        with self._lock:
            if strategy_id is None:
                return tuple(self._outcomes)
            filtered = tuple(
                outcome
                for outcome in self._outcomes
                if self._scenarios_by_outcome.get(
                    outcome.scenario_id
                )
                and self._scenarios_by_outcome[
                    outcome.scenario_id
                ].target_strategy_id
                == strategy_id
            )
            return filtered

    def get_resilience_score(self, strategy_id: str) -> float:
        """Return success-rate in [0.0, 1.0] for strategy_id.

        Default 1.0 when no outcomes recorded (vacuously resilient).
        """
        if not strategy_id:
            raise ValueError("strategy_id must be non-empty")
        with self._lock:
            if strategy_id not in self._strategies:
                raise KeyError(f"strategy '{strategy_id}' not registered")
            outcomes = self.get_outcomes(strategy_id)
            if not outcomes:
                return 1.0
            successes = sum(1 for outcome in outcomes if outcome.success)
            return successes / len(outcomes)

    # -------------- Kill-Switch --------------

    def pause_chaos(self) -> None:
        """Block further inject()-calls (K_0-Sicherheit)."""
        with self._lock:
            self._paused = True

    def resume_chaos(self) -> None:
        """Resume inject()-calls."""
        with self._lock:
            self._paused = False

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def active_chaos_count(self) -> int:
        with self._lock:
            return self._active_chaos_count

    @property
    def registered_strategies(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._strategies.keys())


# CRUX-MK
