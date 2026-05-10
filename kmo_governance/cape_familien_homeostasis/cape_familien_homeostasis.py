# [CRUX-MK]
"""Cape-Familien-Homeostasis Implementation (Welle-38 Phase-31 W38-T2 + W39-P2)."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# W39-P2 (Codex V19 W19-I3): Real-L13-Trigger via Audit-Bus.
# CRITICAL-state publishes l13_phronesis_required event in audit_bus.
from ..cape_familien_audit_bus import (
    CapeFamilienAuditBus,
    ComplianceTag,
    FamilienDecisionType,
)


class FamilienState(str, Enum):
    """Mental-Load-Zustand der Familie."""

    NORMAL = "normal"                  # within tolerance
    MILD_DEVIATION = "mild_deviation"  # 5-10% off setpoint
    ENGAGE_RELIEF = "engage_relief"    # >10% high (Q_0-Risiko)
    ENABLE_PROGRESS = "enable_progress"  # >10% low (Familien underutilized)
    CRITICAL = "critical"              # >20% off, L13-Phronesis-Pflicht


class FamilienActionType(str, Enum):
    REDUCE_LOAD = "reduce_load"      # external help, pause
    INCREASE_LOAD = "increase_load"  # take on more decisions
    HALT = "halt"                    # emergency stop


@dataclass(frozen=True)
class MentalLoadSample:
    """Single Mental-Load-Beobachtung (e.g. weekly assessment).

    Pre:
      - family_member_id non-empty
      - mental_load_score in [0.0, 1.0]
    """
    sample_id: str
    family_member_id: str
    mental_load_score: float
    timestamp: float

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id must be non-empty")
        if not self.family_member_id:
            raise ValueError("family_member_id must be non-empty")
        if not 0.0 <= self.mental_load_score <= 1.0:
            raise ValueError("mental_load_score must be in [0.0, 1.0]")


@dataclass(frozen=True)
class FamilienRebalanceAction:
    """Rebalance-Aktion (recommended)."""
    action_type: FamilienActionType
    target_member: str
    delta_score: float
    reason: str

    def __post_init__(self) -> None:
        if not self.target_member:
            raise ValueError("target_member must be non-empty")


@dataclass(frozen=True)
class FamilienHomeostasisDecision:
    """Controller-Decision."""
    state: FamilienState
    current_score: float
    setpoint: float
    deviation_pct: float
    action: Optional[FamilienRebalanceAction]
    samples_evaluated: int
    timestamp: float


class CapeFamilienHomeostasis:
    """Familien-Mental-Load Homeostasis-Controller.

    Pre:
      - setpoint in [0.0, 1.0]
      - history_window >= 1
      - mild_threshold_pct + critical_threshold_pct in [0, 100]
    """

    def __init__(
        self,
        setpoint: float = 0.5,
        history_window: int = 5,
        mild_threshold_pct: float = 10.0,
        critical_threshold_pct: float = 20.0,
        audit_bus: Optional[CapeFamilienAuditBus] = None,
    ) -> None:
        if not 0.0 <= setpoint <= 1.0:
            raise ValueError("setpoint must be in [0.0, 1.0]")
        if history_window < 1:
            raise ValueError("history_window must be >= 1")
        if mild_threshold_pct < 0 or critical_threshold_pct < 0:
            raise ValueError("thresholds must be non-negative")
        if mild_threshold_pct >= critical_threshold_pct:
            raise ValueError("mild_threshold_pct must be < critical_threshold_pct")
        self._setpoint = setpoint
        self._mild_pct = mild_threshold_pct
        self._critical_pct = critical_threshold_pct
        self._lock = threading.RLock()
        self._history: deque = deque(maxlen=history_window)
        self._samples_total = 0
        # W39-P2: optional audit_bus for L13-Phronesis-Trigger publication
        self._audit_bus = audit_bus

    def record_sample(self, sample: MentalLoadSample) -> FamilienHomeostasisDecision:
        """Add sample + return current Decision.

        W39-P2: bei CRITICAL-state publish audit_event via audit_bus
        (real L13-Phronesis-Trigger statt nur reason-string).
        """
        with self._lock:
            self._history.append(sample)
            self._samples_total += 1
            current_score = self._rolling_avg()
            deviation_pct = abs(current_score - self._setpoint) * 100.0 / max(0.001, self._setpoint)
            state = self._classify(current_score, deviation_pct)
            action = self._build_action(state, current_score, sample.family_member_id)
            decision = FamilienHomeostasisDecision(
                state=state,
                current_score=current_score,
                setpoint=self._setpoint,
                deviation_pct=deviation_pct,
                action=action,
                samples_evaluated=len(self._history),
                timestamp=time.time(),
            )
        # W39-P2: ausserhalb _lock publishen (audit_bus hat eigenen Lock, deadlock-Schutz)
        if state == FamilienState.CRITICAL and self._audit_bus is not None:
            try:
                self._audit_bus.publish(
                    decision_type=FamilienDecisionType.DECISION_FAMILIAL,
                    family_member_role=sample.family_member_id,
                    context=f"l13_phronesis_required: deviation={deviation_pct:.1f}% score={current_score:.2f}",
                    compliance_tags=frozenset({ComplianceTag.FAMILIAL, ComplianceTag.PERSONAL_DATA}),
                    metadata=(
                        ("event_type", "l13_phronesis_required"),
                        ("setpoint", str(self._setpoint)),
                        ("current_score", str(current_score)),
                    ),
                )
            except Exception:
                # Audit-Bus-Failure darf record_sample NICHT killen
                pass
        return decision

    def _rolling_avg(self) -> float:
        if not self._history:
            return self._setpoint
        return sum(s.mental_load_score for s in self._history) / len(self._history)

    def _classify(self, current: float, deviation_pct: float) -> FamilienState:
        if deviation_pct >= self._critical_pct:
            return FamilienState.CRITICAL
        if deviation_pct >= self._mild_pct:
            if current > self._setpoint:
                return FamilienState.ENGAGE_RELIEF
            return FamilienState.ENABLE_PROGRESS
        if deviation_pct >= self._mild_pct / 2:
            return FamilienState.MILD_DEVIATION
        return FamilienState.NORMAL

    def _build_action(
        self,
        state: FamilienState,
        current: float,
        target_member: str,
    ) -> Optional[FamilienRebalanceAction]:
        if state == FamilienState.NORMAL or state == FamilienState.MILD_DEVIATION:
            return None
        if state == FamilienState.CRITICAL:
            return FamilienRebalanceAction(
                action_type=FamilienActionType.HALT,
                target_member=target_member,
                delta_score=current - self._setpoint,
                reason="critical_deviation_l13_pflicht",
            )
        if state == FamilienState.ENGAGE_RELIEF:
            return FamilienRebalanceAction(
                action_type=FamilienActionType.REDUCE_LOAD,
                target_member=target_member,
                delta_score=current - self._setpoint,
                reason="mental_load_high_engage_external_help",
            )
        # ENABLE_PROGRESS
        return FamilienRebalanceAction(
            action_type=FamilienActionType.INCREASE_LOAD,
            target_member=target_member,
            delta_score=self._setpoint - current,
            reason="capacity_underused",
        )

    def get_setpoint(self) -> float:
        with self._lock:
            return self._setpoint

    def get_samples_total(self) -> int:
        with self._lock:
            return self._samples_total

    def reset(self) -> None:
        """Clear history (e.g. after Cape-Coral-Relocation-Phase change)."""
        with self._lock:
            self._history.clear()
            self._samples_total = 0


# CRUX-MK
