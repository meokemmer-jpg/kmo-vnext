# [CRUX-MK]
"""KPM-Homeostasis-Controller (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Aequivalent: Thermoregulation auf Portfolio-Drift-Setpoint.
Setpoint-basierte Feedback-Regelung. Auf Portfolio-Allocation: Setpoint =
ideale Asset-Allocation, Deviation triggert Rebalance-Aktionen ueber
(REDUCING_POSITION) oder unter (INCREASING_POSITION) Schwellwerten
(PID-aehnlich, Rolling-Average-Smoothing gegen Whipsaw).

Komponenten:
  - HomeostasisState: Enum (NORMAL/MILD_DEVIATION/REDUCING_POSITION/
    INCREASING_POSITION/CRITICAL)
  - AllocationSample: Frozen-Dataclass fuer einzelnes Allocation-Sample
  - RebalanceAction: Frozen-Dataclass fuer Rebalance-Aktion (REDUCE/
    INCREASE/HALT)
  - KPMHomeostasisDecision: Frozen-Dataclass fuer Controller-Entscheidung
  - KPMHomeostasisController: Hauptklasse mit Setpoint + Schwellen +
    History-Window

Domain-Spezifika gegenueber homeostasis_controller (Hotel/System):
  - critical_threshold_pct Default 15.0 statt 25.0 (Trading-Volatilitaet)
  - setpoint_pct in [0, 100] (Allocation-Prozente, nicht Temperatur)
  - asset_class als Pflicht-Identifikator pro Allocation-Sample
  - HALT-Action bei CRITICAL-State (Cliff-Effect-Schutz K_0)
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


# ---------- HomeostasisState ----------


class HomeostasisState(str, Enum):
    """Klassifikation des Portfolio-Regulations-Zustands.

    Pre: aufzaehlbar, immutable.
    Post: nutzbar als dict-key (str-enum).
    """

    NORMAL = "normal"
    MILD_DEVIATION = "mild_deviation"
    REDUCING_POSITION = "reducing_position"
    INCREASING_POSITION = "increasing_position"
    CRITICAL = "critical"


# ---------- AllocationSample ----------


@dataclass(frozen=True)
class AllocationSample:
    """Einzelnes Portfolio-Allocation-Sample.

    Pre:
      - asset_class non-empty
      - allocation_pct in [0, 100]
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    timestamp: float
    asset_class: str
    allocation_pct: float

    def __post_init__(self) -> None:
        if not self.asset_class:
            raise ValueError("asset_class must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")
        if not (0.0 <= self.allocation_pct <= 100.0):
            raise ValueError(
                f"allocation_pct must be in [0, 100]: {self.allocation_pct}"
            )


# ---------- RebalanceAction ----------


@dataclass(frozen=True)
class RebalanceAction:
    """Rebalance-Aktion bei Setpoint-Deviation.

    Pre:
      - action_type in {"REDUCE", "INCREASE", "HALT"}
      - target_asset_class non-empty
      - magnitude_pct >= 0 (Prozent-Punkte zum Verschieben; HALT hat 0)
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    action_type: str
    target_asset_class: str
    magnitude_pct: float
    reason: str
    timestamp: float

    _ALLOWED_ACTION_TYPES = ("REDUCE", "INCREASE", "HALT")

    def __post_init__(self) -> None:
        if self.action_type not in self._ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"action_type must be one of {self._ALLOWED_ACTION_TYPES}: "
                f"{self.action_type}"
            )
        if not self.target_asset_class:
            raise ValueError("target_asset_class must be non-empty")
        if self.magnitude_pct < 0:
            raise ValueError(
                f"magnitude_pct must be >= 0: {self.magnitude_pct}"
            )
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- KPMHomeostasisDecision ----------


@dataclass(frozen=True)
class KPMHomeostasisDecision:
    """Single tick decision aus KPMHomeostasisController.

    Pre:
      - state in HomeostasisState
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    state: HomeostasisState
    current_allocation_pct: float
    setpoint_pct: float
    deviation_pct: float
    action: Optional[RebalanceAction]
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- KPMHomeostasisController ----------


class KPMHomeostasisController:
    """Setpoint-basierter Portfolio-Drift-Regler mit Rolling-Average.

    Pre:
      - setpoint_pct in [0, 100]
      - asset_class non-empty
      - mild_threshold_pct > 0
      - critical_threshold_pct > mild_threshold_pct
      - history_window >= 1
    Post: thread-safe; State-Machine NORMAL/MILD/REDUCING/INCREASING/CRITICAL
          basiert auf Rolling-Average ueber history_window-Samples.

    Default-Aktionen:
      - REDUCING_POSITION wenn avg > setpoint + mild_threshold (absolute pp)
      - INCREASING_POSITION wenn avg < setpoint - mild_threshold (absolute pp)
      - CRITICAL wenn |deviation| >= critical_threshold (absolute pp), mit
        HALT-Action (Cliff-Effect-Schutz, K_0-Sicherheit)
      - MILD_DEVIATION wenn |deviation| zwischen mild und critical aber kein
        Custom-Action registriert (informativ ohne RebalanceAction)

    Hinweis Threshold-Semantik:
      Da setpoint_pct + allocation_pct selbst Prozente sind, werden mild und
      critical Schwellen als absolute Prozent-Punkte (pp) interpretiert
      (deviation = avg_allocation_pct - setpoint_pct). Das vermeidet
      Doppel-Prozentuierung und passt zur Allocation-Domaene.

    Custom-Actions koennen per register_action(state, fn) hinterlegt werden;
    fn(deviation_pct) -> RebalanceAction wird im evaluate() aufgerufen.

    Bio-Aequivalent: Thermoregulation Setpoint 37C + Schwellen 5% / 15%.
    Trading-Defaults: 60% Equities + Schwellen 5pp / 15pp.
    """

    def __init__(
        self,
        setpoint_pct: float,
        asset_class: str,
        mild_threshold_pct: float = 5.0,
        critical_threshold_pct: float = 15.0,
        history_window: int = 20,
    ) -> None:
        if not (0.0 <= setpoint_pct <= 100.0):
            raise ValueError(
                f"setpoint_pct must be in [0, 100]: {setpoint_pct}"
            )
        if not asset_class:
            raise ValueError("asset_class must be non-empty")
        if mild_threshold_pct <= 0:
            raise ValueError("mild_threshold_pct must be > 0")
        if critical_threshold_pct <= mild_threshold_pct:
            raise ValueError(
                "critical_threshold_pct must be > mild_threshold_pct"
            )
        if history_window < 1:
            raise ValueError("history_window must be >= 1")

        self._setpoint_pct = float(setpoint_pct)
        self._asset_class = str(asset_class)
        self._mild_pct = float(mild_threshold_pct)
        self._critical_pct = float(critical_threshold_pct)
        self._history_window = int(history_window)
        self._history: deque[AllocationSample] = deque(maxlen=history_window)
        self._decisions: list[KPMHomeostasisDecision] = []
        self._actions: dict[
            HomeostasisState, Callable[[float], RebalanceAction]
        ] = {}
        self._lock = threading.RLock()

    @property
    def setpoint_pct(self) -> float:
        return self._setpoint_pct

    @property
    def asset_class(self) -> str:
        return self._asset_class

    @property
    def mild_threshold_pct(self) -> float:
        return self._mild_pct

    @property
    def critical_threshold_pct(self) -> float:
        return self._critical_pct

    @property
    def history_window(self) -> int:
        return self._history_window

    def record_allocation(
        self, asset_class: str, allocation_pct: float
    ) -> None:
        """Append allocation sample to history (bounded by history_window).

        Pre: asset_class non-empty, allocation_pct in [0, 100].
        Post: history depth <= history_window (deque maxlen enforces).

        Hinweis: asset_class wird im Sample mitgespeichert (Audit-Trail).
        Der Controller selbst bewertet allerdings nur Samples seiner eigenen
        asset_class beim Rolling-Average (Filterung im evaluate()).
        """
        sample = AllocationSample(
            timestamp=time.time(),
            asset_class=str(asset_class),
            allocation_pct=float(allocation_pct),
        )
        with self._lock:
            self._history.append(sample)

    def register_action(
        self,
        state: HomeostasisState,
        action_fn: Callable[[float], RebalanceAction],
    ) -> None:
        """Registriert Custom-RebalanceAction-Factory fuer einen State.

        Pre: state in HomeostasisState, action_fn callable.
        Post: bei evaluate() wird action_fn(deviation_pct) aufgerufen und
              das Resultat im KPMHomeostasisDecision.action abgelegt.
        """
        if not isinstance(state, HomeostasisState):
            raise TypeError("state must be HomeostasisState")
        if not callable(action_fn):
            raise TypeError("action_fn must be callable")
        with self._lock:
            self._actions[state] = action_fn

    def evaluate(self) -> KPMHomeostasisDecision:
        """Compute current state + optional RebalanceAction.

        Pre: history nicht zwingend non-empty (leere History -> NORMAL).
        Post: KPMHomeostasisDecision wird zurueckgegeben + im Audit-Trail
              abgelegt.

        State-Machine (basiert auf Rolling-Average ueber Samples
        derselben asset_class):
          deviation_pct = avg_allocation_pct - setpoint_pct  (absolute pp)

          |deviation_pct| < mild              -> NORMAL
          mild <= |deviation_pct| < critical  -> REDUCING_POSITION (>0) oder
                                                  INCREASING_POSITION (<0)
          |deviation_pct| >= critical         -> CRITICAL (mit HALT-Action)
        """
        with self._lock:
            now = time.time()
            # Filter: nur Samples der eigenen asset_class
            relevant = [
                s for s in self._history if s.asset_class == self._asset_class
            ]
            if not relevant:
                decision = KPMHomeostasisDecision(
                    state=HomeostasisState.NORMAL,
                    current_allocation_pct=self._setpoint_pct,
                    setpoint_pct=self._setpoint_pct,
                    deviation_pct=0.0,
                    action=None,
                    reason="no allocations recorded",
                    timestamp=now,
                )
                self._decisions.append(decision)
                return decision

            avg_alloc = sum(s.allocation_pct for s in relevant) / len(relevant)
            # Absolute Prozent-Punkte (pp), keine Doppel-Prozentuierung
            deviation_pct = avg_alloc - self._setpoint_pct
            abs_dev = abs(deviation_pct)

            if abs_dev >= self._critical_pct:
                state = HomeostasisState.CRITICAL
                reason = (
                    f"|deviation|={abs_dev:.2f}pp >= critical="
                    f"{self._critical_pct}pp"
                )
            elif abs_dev >= self._mild_pct:
                if deviation_pct > 0:
                    state = HomeostasisState.REDUCING_POSITION
                    reason = (
                        f"deviation={deviation_pct:.2f}pp > mild="
                        f"{self._mild_pct}pp (reduce)"
                    )
                else:
                    state = HomeostasisState.INCREASING_POSITION
                    reason = (
                        f"deviation={deviation_pct:.2f}pp < -mild="
                        f"{-self._mild_pct}pp (increase)"
                    )
            else:
                state = HomeostasisState.NORMAL
                reason = (
                    f"|deviation|={abs_dev:.2f}pp < mild="
                    f"{self._mild_pct}pp"
                )

            action: Optional[RebalanceAction] = None
            if state in (
                HomeostasisState.REDUCING_POSITION,
                HomeostasisState.INCREASING_POSITION,
                HomeostasisState.CRITICAL,
            ):
                custom = self._actions.get(state)
                if custom is not None:
                    action = custom(deviation_pct)
                else:
                    # Default action
                    if state == HomeostasisState.REDUCING_POSITION:
                        action_type = "REDUCE"
                        magnitude = abs_dev
                    elif state == HomeostasisState.INCREASING_POSITION:
                        action_type = "INCREASE"
                        magnitude = abs_dev
                    else:
                        # CRITICAL -> HALT (Cliff-Effect-Schutz, K_0)
                        action_type = "HALT"
                        magnitude = 0.0
                    action = RebalanceAction(
                        action_type=action_type,
                        target_asset_class=self._asset_class,
                        magnitude_pct=magnitude,
                        reason=reason,
                        timestamp=now,
                    )

            decision = KPMHomeostasisDecision(
                state=state,
                current_allocation_pct=avg_alloc,
                setpoint_pct=self._setpoint_pct,
                deviation_pct=deviation_pct,
                action=action,
                reason=reason,
                timestamp=now,
            )
            self._decisions.append(decision)
            return decision

    def get_history(self) -> tuple[AllocationSample, ...]:
        """Read-only Snapshot der bisherigen Samples (immutable tuple)."""
        with self._lock:
            return tuple(self._history)

    def get_decisions(self) -> tuple[KPMHomeostasisDecision, ...]:
        """Read-only Audit-Trail aller Decisions (immutable tuple)."""
        with self._lock:
            return tuple(self._decisions)

    def reset(self) -> None:
        """Loeschen von History + Decisions (Actions bleiben registriert)."""
        with self._lock:
            self._history.clear()
            self._decisions.clear()


# CRUX-MK
