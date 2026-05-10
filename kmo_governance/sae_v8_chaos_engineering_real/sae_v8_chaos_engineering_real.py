# [CRUX-MK]
"""SAE-v8 Chaos-Engineering Implementation (Welle-55, DEMO-only per L34)."""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class SAEv8FaultType(str, Enum):
    TRINITY_VOTE_TIMEOUT = "trinity_vote_timeout"
    SLOT_AGENT_CRASH = "slot_agent_crash"
    COSMOS_VETO_LOOP = "cosmos_veto_loop"
    HAMILTON_OPTIMIZER_DIVERGENCE = "hamilton_optimizer_divergence"
    MYZEL_LAYER_EVENT_LOSS = "myzel_layer_event_loss"


class FaultSeverity(str, Enum):
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SAEv8ChaosScenario:
    scenario_id: str
    fault_type: SAEv8FaultType
    severity: FaultSeverity
    slot_id: str
    duration_s: float

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.slot_id:
            raise ValueError("scenario_id + slot_id non-empty")
        if self.duration_s <= 0:
            raise ValueError("duration_s > 0")
        if not isinstance(self.fault_type, SAEv8FaultType):
            raise TypeError("fault_type must be SAEv8FaultType")


@dataclass(frozen=True)
class SAEv8ChaosOutcome:
    outcome_id: str
    scenario_id: str
    fault_type: SAEv8FaultType
    success: bool
    actual_recovery_s: float
    trinity_consensus_recovered: bool
    timestamp: float
    error: Optional[str] = None


class SAEv8ChaosEngineering:
    def __init__(self, max_concurrent_chaos: int = 1, max_outcomes_history: int = 100) -> None:
        if max_concurrent_chaos < 1:
            raise ValueError("max_concurrent_chaos >= 1")
        self._max_concurrent = max_concurrent_chaos
        self._lock = threading.RLock()
        self._handlers: dict[str, Callable] = {}
        self._outcomes: deque = deque(maxlen=max_outcomes_history)
        self._active_chaos = 0
        self._paused = False

    def register_slot(self, slot_id: str, handler: Callable) -> None:
        if not slot_id:
            raise ValueError("slot_id non-empty")
        with self._lock:
            self._handlers[slot_id] = handler

    def pause_chaos(self) -> None:
        with self._lock:
            self._paused = True

    def inject(self, scenario: SAEv8ChaosScenario) -> SAEv8ChaosOutcome:
        with self._lock:
            if self._paused:
                return self._failed(scenario, "chaos_paused")
            if scenario.slot_id not in self._handlers:
                return self._failed(scenario, "slot_not_registered")
            if self._active_chaos >= self._max_concurrent:
                return self._failed(scenario, "max_concurrent_reached")
            self._active_chaos += 1
            handler = self._handlers[scenario.slot_id]
        outcome_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            result = handler(scenario)
            outcome = SAEv8ChaosOutcome(
                outcome_id=outcome_id,
                scenario_id=scenario.scenario_id,
                fault_type=scenario.fault_type,
                success=bool(result.get("success", True)),
                actual_recovery_s=time.monotonic() - start,
                trinity_consensus_recovered=bool(result.get("trinity_consensus_recovered", True)),
                timestamp=time.time(),
            )
        except Exception as exc:
            outcome = SAEv8ChaosOutcome(
                outcome_id=outcome_id,
                scenario_id=scenario.scenario_id,
                fault_type=scenario.fault_type,
                success=False,
                actual_recovery_s=time.monotonic() - start,
                trinity_consensus_recovered=False,
                timestamp=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
        with self._lock:
            self._active_chaos -= 1
            self._outcomes.append(outcome)
        return outcome

    def _failed(self, scenario: SAEv8ChaosScenario, reason: str) -> SAEv8ChaosOutcome:
        outcome = SAEv8ChaosOutcome(
            outcome_id=str(uuid.uuid4()),
            scenario_id=scenario.scenario_id,
            fault_type=scenario.fault_type,
            success=False,
            actual_recovery_s=0.0,
            trinity_consensus_recovered=False,
            timestamp=time.time(),
            error=reason,
        )
        with self._lock:
            self._outcomes.append(outcome)
        return outcome

    def get_outcomes(self) -> tuple[SAEv8ChaosOutcome, ...]:
        with self._lock:
            return tuple(self._outcomes)


# CRUX-MK
