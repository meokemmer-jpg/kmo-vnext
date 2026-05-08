# [CRUX-MK]
"""SAE-v8-Homeostasis-Governance (Welle-34 Phase-27 Bio-Pattern-Lift).

Bio-Aequivalent: Thermoregulation auf SAE-Governance-Tier-Setpoint.
Setpoint-basierte Feedback-Regelung. Auf SAE-v8 Slot-Governance: Setpoint =
ideale q-Norm-Distribution, Deviation triggert Slot-Adjustment-Aktionen
ueber (RELEGATING_SLOT) oder unter (PROMOTING_SLOT) Schwellwerten
(PID-aehnlich, Rolling-Average-Smoothing gegen Whipsaw-Promotion).

Komponenten:
  - GovernanceState: Enum (NORMAL/MILD_DEVIATION/RELEGATING_SLOT/
    PROMOTING_SLOT/CRITICAL)
  - GovernanceSample: Frozen-Dataclass fuer einzelnes q-Norm-Sample
  - SlotAdjustmentAction: Frozen-Dataclass fuer Slot-Adjustment (RELEGATE/
    PROMOTE/HALT)
  - SAEGovernanceDecision: Frozen-Dataclass fuer Controller-Entscheidung
  - SAEv8HomeostasisGovernance: Hauptklasse mit Setpoint + Schwellen +
    History-Window

Domain-Spezifika gegenueber homeostasis_controller (Hotel/System) und
kpm_homeostasis_controller (Trading):
  - critical_threshold_pct Default 30.0 (vs. 25.0 Hotel, 15.0 KPM)
    Begruendung: Governance-Tier volatiler durch Reward-Stream-Sensitivitaet
  - setpoint_q_norm in [-2, +2] (q-Scale-Constraint, SAE-v8 §4 Invariante 1)
  - q_norm-Sample-Validation in [-2, +2] enforced
  - slot_id als Pflicht-Identifikator pro Sample (Audit-Trail per Slot)
  - HALT-Action bei CRITICAL-State (Cliff-Effect-Schutz, kein Slot-Massaker)
  - Threshold-Semantik: Prozent von |q-Range|=4 (q in [-2, +2] hat Range 4)
    Beispiel: mild=10% -> 0.4 Punkte Deviation triggert MILD-Eintritt
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


# ---------- GovernanceState ----------


class GovernanceState(str, Enum):
    """Klassifikation des Governance-Regulations-Zustands.

    Pre: aufzaehlbar, immutable.
    Post: nutzbar als dict-key (str-enum).
    """

    NORMAL = "normal"
    MILD_DEVIATION = "mild_deviation"
    RELEGATING_SLOT = "relegating_slot"
    PROMOTING_SLOT = "promoting_slot"
    CRITICAL = "critical"


# ---------- GovernanceSample ----------


@dataclass(frozen=True)
class GovernanceSample:
    """Einzelnes q-Norm-Governance-Sample.

    Pre:
      - slot_id non-empty
      - q_norm in [-2, +2] (SAE-v8 §4 Invariante 1)
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    timestamp: float
    slot_id: str
    q_norm: float

    def __post_init__(self) -> None:
        if not self.slot_id:
            raise ValueError("slot_id must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")
        if not (-2.0 <= self.q_norm <= 2.0):
            raise ValueError(
                f"q_norm must be in [-2, +2]: {self.q_norm}"
            )


# ---------- SlotAdjustmentAction ----------


@dataclass(frozen=True)
class SlotAdjustmentAction:
    """Slot-Adjustment-Aktion bei Setpoint-Deviation.

    Pre:
      - action_type in {"RELEGATE", "PROMOTE", "HALT"}
      - target_slot_id non-empty
      - magnitude_pct >= 0 (Prozent-Punkte zum Verschieben; HALT hat 0)
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    action_type: str
    target_slot_id: str
    magnitude_pct: float
    reason: str
    timestamp: float

    _ALLOWED_ACTION_TYPES = ("RELEGATE", "PROMOTE", "HALT")

    def __post_init__(self) -> None:
        if self.action_type not in self._ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"action_type must be one of {self._ALLOWED_ACTION_TYPES}: "
                f"{self.action_type}"
            )
        if not self.target_slot_id:
            raise ValueError("target_slot_id must be non-empty")
        if self.magnitude_pct < 0:
            raise ValueError(
                f"magnitude_pct must be >= 0: {self.magnitude_pct}"
            )
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- SAEGovernanceDecision ----------


@dataclass(frozen=True)
class SAEGovernanceDecision:
    """Single tick decision aus SAEv8HomeostasisGovernance.

    Pre:
      - state in GovernanceState
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    state: GovernanceState
    current_q_norm: float
    setpoint_q_norm: float
    deviation_pct: float
    action: Optional[SlotAdjustmentAction]
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- SAEv8HomeostasisGovernance ----------


class SAEv8HomeostasisGovernance:
    """Setpoint-basierter SAE-v8-Governance-Tier-Drift-Regler mit Rolling-Avg.

    Pre:
      - setpoint_q_norm in [-2, +2] (q-Scale-Constraint)
      - mild_threshold_pct > 0
      - critical_threshold_pct > mild_threshold_pct
      - history_window >= 1
    Post: thread-safe; State-Machine NORMAL/MILD/RELEGATING/PROMOTING/CRITICAL
          basiert auf Rolling-Average ueber history_window-Samples.

    Default-Aktionen:
      - RELEGATING_SLOT wenn avg_q_norm > setpoint + mild_threshold (relative %
        von |q-Range|=4)
      - PROMOTING_SLOT wenn avg_q_norm < setpoint - mild_threshold
      - CRITICAL wenn |deviation| >= critical_threshold (relative %), mit
        HALT-Action (Cliff-Effect-Schutz, kein massenhaftes Slot-Massaker)
      - MILD_DEVIATION wenn |deviation| zwischen mild und critical aber kein
        Custom-Action registriert (informativ ohne SlotAdjustmentAction)

    Hinweis Threshold-Semantik:
      Da q_norm-Range = 4 (von -2 bis +2), werden mild und critical Schwellen
      als Prozent-von-Range interpretiert. Beispiel: mild_threshold_pct=10
      entspricht 0.4 q-Norm-Punkten Deviation-Eintritt.

    Custom-Actions koennen per register_action(state, fn) hinterlegt werden;
    fn(deviation_pct) -> SlotAdjustmentAction wird im evaluate() aufgerufen.

    Bio-Aequivalent: Thermoregulation Setpoint 37C + Schwellen 5% / 25%.
    Trading-KPM-Defaults: 60% Equities + Schwellen 5pp / 15pp.
    SAE-v8-Defaults: q_norm 0.0 + Schwellen 10% / 30% (volatiler durch
    Reward-Stream-Sensitivitaet).
    """

    Q_NORM_RANGE = 4.0  # q in [-2, +2] hat Range = 4

    def __init__(
        self,
        setpoint_q_norm: float = 0.0,
        mild_threshold_pct: float = 10.0,
        critical_threshold_pct: float = 30.0,
        history_window: int = 50,
    ) -> None:
        if not (-2.0 <= setpoint_q_norm <= 2.0):
            raise ValueError(
                f"setpoint_q_norm must be in [-2, +2]: {setpoint_q_norm}"
            )
        if mild_threshold_pct <= 0:
            raise ValueError("mild_threshold_pct must be > 0")
        if critical_threshold_pct <= mild_threshold_pct:
            raise ValueError(
                "critical_threshold_pct must be > mild_threshold_pct"
            )
        if history_window < 1:
            raise ValueError("history_window must be >= 1")

        self._setpoint_q_norm = float(setpoint_q_norm)
        self._mild_pct = float(mild_threshold_pct)
        self._critical_pct = float(critical_threshold_pct)
        self._history_window = int(history_window)
        self._history: deque[GovernanceSample] = deque(maxlen=history_window)
        self._decisions: list[SAEGovernanceDecision] = []
        self._actions: dict[
            GovernanceState, Callable[[float], SlotAdjustmentAction]
        ] = {}
        self._lock = threading.RLock()

    @property
    def setpoint_q_norm(self) -> float:
        return self._setpoint_q_norm

    @property
    def mild_threshold_pct(self) -> float:
        return self._mild_pct

    @property
    def critical_threshold_pct(self) -> float:
        return self._critical_pct

    @property
    def history_window(self) -> int:
        return self._history_window

    def record_governance(self, slot_id: str, q_norm: float) -> None:
        """Append governance sample to history (bounded by history_window).

        Pre: slot_id non-empty, q_norm in [-2, +2].
        Post: history depth <= history_window (deque maxlen enforces).

        Hinweis: slot_id wird im Sample mitgespeichert (Audit-Trail).
        Der Controller selbst bewertet entweder alle Samples (slot_id=None
        in evaluate) oder nur Samples eines bestimmten slot_id (Filter
        in evaluate).
        """
        sample = GovernanceSample(
            timestamp=time.time(),
            slot_id=str(slot_id),
            q_norm=float(q_norm),
        )
        with self._lock:
            self._history.append(sample)

    def register_action(
        self,
        state: GovernanceState,
        action_fn: Callable[[float], SlotAdjustmentAction],
    ) -> None:
        """Registriert Custom-SlotAdjustmentAction-Factory fuer einen State.

        Pre: state in GovernanceState, action_fn callable.
        Post: bei evaluate() wird action_fn(deviation_pct) aufgerufen und
              das Resultat im SAEGovernanceDecision.action abgelegt.
        """
        if not isinstance(state, GovernanceState):
            raise TypeError("state must be GovernanceState")
        if not callable(action_fn):
            raise TypeError("action_fn must be callable")
        with self._lock:
            self._actions[state] = action_fn

    def evaluate(
        self, slot_id: Optional[str] = None
    ) -> SAEGovernanceDecision:
        """Compute current state + optional SlotAdjustmentAction.

        Args:
          slot_id: Optional Slot-Filter. Wenn None, alle Samples aggregiert.
                   Wenn gesetzt, nur Samples mit matching slot_id.

        Pre: history nicht zwingend non-empty (leere History -> NORMAL).
        Post: SAEGovernanceDecision wird zurueckgegeben + im Audit-Trail
              abgelegt.

        State-Machine (basiert auf Rolling-Average):
          deviation_pct = (avg_q_norm - setpoint_q_norm) / Q_NORM_RANGE * 100
                          (Prozent-von-q-Range)

          |deviation_pct| < mild              -> NORMAL
          mild <= |deviation_pct| < critical  -> RELEGATING_SLOT (>0) oder
                                                  PROMOTING_SLOT (<0)
          |deviation_pct| >= critical         -> CRITICAL (mit HALT-Action)
        """
        with self._lock:
            now = time.time()
            # Filter: optional auf slot_id
            if slot_id is None:
                relevant = list(self._history)
                target_id = "ALL_SLOTS"
            else:
                relevant = [
                    s for s in self._history if s.slot_id == slot_id
                ]
                target_id = slot_id

            if not relevant:
                decision = SAEGovernanceDecision(
                    state=GovernanceState.NORMAL,
                    current_q_norm=self._setpoint_q_norm,
                    setpoint_q_norm=self._setpoint_q_norm,
                    deviation_pct=0.0,
                    action=None,
                    reason="no governance samples recorded",
                    timestamp=now,
                )
                self._decisions.append(decision)
                return decision

            avg_q_norm = sum(s.q_norm for s in relevant) / len(relevant)
            # Prozent-von-q-Range: deviation auf 4-Punkte-Range normiert
            deviation_pct = (
                (avg_q_norm - self._setpoint_q_norm) / self.Q_NORM_RANGE
                * 100.0
            )
            abs_dev = abs(deviation_pct)

            if abs_dev >= self._critical_pct:
                state = GovernanceState.CRITICAL
                reason = (
                    f"|deviation|={abs_dev:.2f}% >= critical="
                    f"{self._critical_pct}%"
                )
            elif abs_dev >= self._mild_pct:
                if deviation_pct > 0:
                    state = GovernanceState.RELEGATING_SLOT
                    reason = (
                        f"deviation={deviation_pct:.2f}% > mild="
                        f"{self._mild_pct}% (relegate slot)"
                    )
                else:
                    state = GovernanceState.PROMOTING_SLOT
                    reason = (
                        f"deviation={deviation_pct:.2f}% < -mild="
                        f"{-self._mild_pct}% (promote slot)"
                    )
            else:
                state = GovernanceState.NORMAL
                reason = (
                    f"|deviation|={abs_dev:.2f}% < mild="
                    f"{self._mild_pct}%"
                )

            action: Optional[SlotAdjustmentAction] = None
            if state in (
                GovernanceState.RELEGATING_SLOT,
                GovernanceState.PROMOTING_SLOT,
                GovernanceState.CRITICAL,
            ):
                custom = self._actions.get(state)
                if custom is not None:
                    action = custom(deviation_pct)
                else:
                    # Default action
                    if state == GovernanceState.RELEGATING_SLOT:
                        action_type = "RELEGATE"
                        magnitude = abs_dev
                    elif state == GovernanceState.PROMOTING_SLOT:
                        action_type = "PROMOTE"
                        magnitude = abs_dev
                    else:
                        # CRITICAL -> HALT (Cliff-Effect-Schutz, kein
                        # Slot-Massaker bei Reward-Stream-Schock)
                        action_type = "HALT"
                        magnitude = 0.0
                    action = SlotAdjustmentAction(
                        action_type=action_type,
                        target_slot_id=target_id,
                        magnitude_pct=magnitude,
                        reason=reason,
                        timestamp=now,
                    )

            decision = SAEGovernanceDecision(
                state=state,
                current_q_norm=avg_q_norm,
                setpoint_q_norm=self._setpoint_q_norm,
                deviation_pct=deviation_pct,
                action=action,
                reason=reason,
                timestamp=now,
            )
            self._decisions.append(decision)
            return decision

    def get_history(self) -> tuple[GovernanceSample, ...]:
        """Read-only Snapshot der bisherigen Samples (immutable tuple)."""
        with self._lock:
            return tuple(self._history)

    def get_decisions(self) -> tuple[SAEGovernanceDecision, ...]:
        """Read-only Audit-Trail aller Decisions (immutable tuple)."""
        with self._lock:
            return tuple(self._decisions)

    def reset(self) -> None:
        """Loeschen von History + Decisions (Actions bleiben registriert)."""
        with self._lock:
            self._history.clear()
            self._decisions.clear()


# CRUX-MK
