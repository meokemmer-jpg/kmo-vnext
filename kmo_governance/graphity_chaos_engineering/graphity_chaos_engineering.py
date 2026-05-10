# [CRUX-MK]
"""Graphity-Chaos-Engineering Implementation (Welle-38 Phase-31).

Bio-Pattern-Lift von kmo_governance.chaos_engineering (Welle-9 Hotel-Domain)
auf Verlag-Edit-Pipeline-Domain. Fault-Injection auf Manuscript-Stages,
Recovery-Time-Messung, editorial_consensus_recovered Tracking.

Stdlib-only. Frozen-Dataclasses. RLock-protected.
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# Severity-Multipliers (Verlag-Domain-Default-Skala fuer Manuscript-Recovery)
SEVERITY_RECOVERY_MULTIPLIER: dict[str, float] = {
    "minor": 1.0,
    "moderate": 3.0,
    "severe": 8.0,
    "critical": 20.0,  # Verlag hat laengere Recovery (manuelle Editor-Reviews)
}


class VerlagFaultType(str, Enum):
    """Verlag-Domain-Fault-Klassen."""

    AUTHOR_BURNOUT = "author_burnout"
    EDITOR_REVIEW_BLOCK = "editor_review_block"
    TYPESETTING_ERROR = "typesetting_error"
    DEADLINE_MISS = "deadline_miss"
    VG_WORT_QUOTA_EXCEEDED = "vg_wort_quota_exceeded"


class FaultSeverity(str, Enum):
    """Severity-Stufen (Verlag-Domain-spezifisch hoehere Multiplier)."""

    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


@dataclass(frozen=True)
class GraphityChaosScenario:
    """Immutable Fault-Profil fuer Verlag-Manuscript-Stage.

    Pre-Conditions:
    - scenario_id non-empty
    - manuscript_id non-empty
    - editor_role non-empty (author/editor/reviewer/typesetter/corrector)
    - duration_s > 0, expected_recovery_s > 0
    - params: tuple-of-tuples (frozen, hashable)
    """

    scenario_id: str
    fault_type: VerlagFaultType
    severity: FaultSeverity
    manuscript_id: str
    editor_role: str
    duration_s: float
    params: tuple[tuple[str, object], ...] = field(default_factory=tuple)
    expected_recovery_s: float = 1.0

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if not self.manuscript_id:
            raise ValueError("manuscript_id must be non-empty")
        if not self.editor_role:
            raise ValueError("editor_role must be non-empty")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if self.expected_recovery_s <= 0:
            raise ValueError("expected_recovery_s must be > 0")
        if not isinstance(self.fault_type, VerlagFaultType):
            raise TypeError("fault_type must be VerlagFaultType")
        if not isinstance(self.severity, FaultSeverity):
            raise TypeError("severity must be FaultSeverity")


@dataclass(frozen=True)
class GraphityChaosOutcome:
    """Immutable Outcome eines Fault-Injection-Runs.

    Pre-Conditions:
    - outcome_id non-empty, scenario_id non-empty
    - actual_recovery_s >= 0
    - manuscripts_blocked >= 0
    """

    outcome_id: str
    scenario_id: str
    fault_type: VerlagFaultType
    success: bool
    actual_recovery_s: float
    expected_recovery_s: float
    editorial_consensus_recovered: bool
    manuscripts_blocked: int
    editor_role: str
    timestamp: float
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.outcome_id:
            raise ValueError("outcome_id must be non-empty")
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if self.actual_recovery_s < 0:
            raise ValueError("actual_recovery_s must be >= 0")
        if self.manuscripts_blocked < 0:
            raise ValueError("manuscripts_blocked must be >= 0")


class GraphityChaosEngineering:
    """Verlag-Chaos-Orchestrator: kontrollierte Fault-Injection.

    Pre:
      - max_concurrent_chaos >= 1
      - max_outcomes_history >= 0
    """

    def __init__(
        self,
        default_severity: FaultSeverity = FaultSeverity.MODERATE,
        max_concurrent_chaos: int = 1,
        max_outcomes_history: int = 100,
    ) -> None:
        if max_concurrent_chaos < 1:
            raise ValueError("max_concurrent_chaos must be >= 1")
        if max_outcomes_history < 0:
            raise ValueError("max_outcomes_history must be >= 0")
        self._default_severity = default_severity
        self._max_concurrent = max_concurrent_chaos
        self._lock = threading.RLock()
        self._handlers: dict[str, Callable[[GraphityChaosScenario], dict]] = {}
        self._outcomes: deque = deque(maxlen=max_outcomes_history)
        self._active_chaos = 0
        self._paused = False
        # Stability-Score per manuscript_id: 1.0 = perfect, decay bei Faults
        self._stability: dict[str, float] = {}

    def register_manuscript(
        self,
        manuscript_id: str,
        handler: Callable[[GraphityChaosScenario], dict],
    ) -> None:
        """Register Manuscript + Fault-Handler."""
        if not manuscript_id:
            raise ValueError("manuscript_id must be non-empty")
        with self._lock:
            self._handlers[manuscript_id] = handler
            self._stability.setdefault(manuscript_id, 1.0)

    def pause_chaos(self) -> None:
        """Kill-Switch: blockiert weitere inject()-Calls (K_0-Schutz)."""
        with self._lock:
            self._paused = True

    def resume_chaos(self) -> None:
        """Re-Enable: erlaubt inject()-Calls wieder."""
        with self._lock:
            self._paused = False

    def inject(
        self,
        scenario: GraphityChaosScenario,
    ) -> GraphityChaosOutcome:
        """Fuehre Fault-Injection durch.

        Pre:
          - scenario.manuscript_id ist registered
          - !paused
          - active_chaos < max_concurrent_chaos
        """
        with self._lock:
            if self._paused:
                return self._failed_outcome(scenario, "chaos_paused")
            if scenario.manuscript_id not in self._handlers:
                return self._failed_outcome(scenario, "manuscript_not_registered")
            if self._active_chaos >= self._max_concurrent:
                return self._failed_outcome(scenario, "max_concurrent_reached")
            self._active_chaos += 1

        outcome_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            handler = self._handlers[scenario.manuscript_id]
            result = handler(scenario)
            actual_recovery_s = time.monotonic() - start
            consensus_recovered = bool(result.get("editorial_consensus_recovered", True))
            blocked = int(result.get("manuscripts_blocked", 0))
            success = bool(result.get("success", True))
            outcome = GraphityChaosOutcome(
                outcome_id=outcome_id,
                scenario_id=scenario.scenario_id,
                fault_type=scenario.fault_type,
                success=success,
                actual_recovery_s=actual_recovery_s,
                expected_recovery_s=scenario.expected_recovery_s,
                editorial_consensus_recovered=consensus_recovered,
                manuscripts_blocked=blocked,
                editor_role=scenario.editor_role,
                timestamp=time.time(),
            )
        except Exception as exc:
            actual_recovery_s = time.monotonic() - start
            outcome = GraphityChaosOutcome(
                outcome_id=outcome_id,
                scenario_id=scenario.scenario_id,
                fault_type=scenario.fault_type,
                success=False,
                actual_recovery_s=actual_recovery_s,
                expected_recovery_s=scenario.expected_recovery_s,
                editorial_consensus_recovered=False,
                manuscripts_blocked=1,
                editor_role=scenario.editor_role,
                timestamp=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )

        with self._lock:
            self._active_chaos -= 1
            self._outcomes.append(outcome)
            # Stability-Decay: severity-multiplier * 0.05
            multiplier = SEVERITY_RECOVERY_MULTIPLIER[scenario.severity.value]
            decay = multiplier * 0.05
            current = self._stability.get(scenario.manuscript_id, 1.0)
            self._stability[scenario.manuscript_id] = max(0.0, current - decay)
            if outcome.success and outcome.editorial_consensus_recovered:
                # Recovery-Bonus
                self._stability[scenario.manuscript_id] = min(
                    1.0,
                    self._stability[scenario.manuscript_id] + 0.02,
                )

        return outcome

    def _failed_outcome(
        self,
        scenario: GraphityChaosScenario,
        reason: str,
    ) -> GraphityChaosOutcome:
        """Internal: build failure-outcome ohne Lock-Held."""
        return GraphityChaosOutcome(
            outcome_id=str(uuid.uuid4()),
            scenario_id=scenario.scenario_id,
            fault_type=scenario.fault_type,
            success=False,
            actual_recovery_s=0.0,
            expected_recovery_s=scenario.expected_recovery_s,
            editorial_consensus_recovered=False,
            manuscripts_blocked=0,
            editor_role=scenario.editor_role,
            timestamp=time.time(),
            error=reason,
        )

    def get_stability_score(self, manuscript_id: str) -> float:
        """Stability [0.0-1.0] fuer Manuscript (1.0 = perfect)."""
        with self._lock:
            return self._stability.get(manuscript_id, 1.0)

    def get_outcomes(
        self,
        editor_role: Optional[str] = None,
        fault_type: Optional[VerlagFaultType] = None,
    ) -> tuple[GraphityChaosOutcome, ...]:
        """Filtered outcomes-history (immutable copy)."""
        with self._lock:
            outcomes = list(self._outcomes)
        filtered = [
            o for o in outcomes
            if (editor_role is None or o.editor_role == editor_role)
            and (fault_type is None or o.fault_type == fault_type)
        ]
        return tuple(filtered)

    def get_aggregate_score(self) -> dict[str, float]:
        """Aggregate-Stats: success_rate + avg_recovery + consensus_recovery_rate."""
        with self._lock:
            outcomes = list(self._outcomes)
        if not outcomes:
            return {"success_rate": 0.0, "avg_recovery_s": 0.0, "consensus_rate": 0.0, "total": 0.0}
        success_count = sum(1 for o in outcomes if o.success)
        consensus_count = sum(1 for o in outcomes if o.editorial_consensus_recovered)
        total_recovery = sum(o.actual_recovery_s for o in outcomes)
        return {
            "success_rate": success_count / len(outcomes),
            "avg_recovery_s": total_recovery / len(outcomes),
            "consensus_rate": consensus_count / len(outcomes),
            "total": float(len(outcomes)),
        }


# CRUX-MK
