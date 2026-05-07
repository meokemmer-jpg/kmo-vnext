# [CRUX-MK]
"""Homeostasis Controller (Welle-25 Phase-18).

Bio-Aequivalent: Thermoregulation (Hypothalamus-basiert).
Setpoint-basierte Feedback-Regelung. Auf System-Metriken: Setpoint = ideale
Latency / CPU / Throughput, Deviation triggert auto-corrective actions ueber/
unter Schwellwerten (PID-aehnlich, Rolling-Average-Smoothing).

Komponenten:
  - HomeostasisState: Enum (NORMAL/MILD_DEVIATION/COOLING_ACTIVE/HEATING_ACTIVE/CRITICAL)
  - MetricSample: Frozen-Dataclass fuer einzelnes Metrik-Sample
  - CorrectiveAction: Frozen-Dataclass fuer Korrektur-Aktion
  - HomeostasisDecision: Frozen-Dataclass fuer Controller-Entscheidung
  - HomeostasisController: Hauptklasse mit Setpoint + Schwellen + History-Window
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
    """Klassifikation des Regulations-Zustands.

    Pre: aufzaehlbar, immutable.
    Post: nutzbar als dict-key (str-enum).
    """

    NORMAL = "normal"
    MILD_DEVIATION = "mild_deviation"
    COOLING_ACTIVE = "cooling_active"
    HEATING_ACTIVE = "heating_active"
    CRITICAL = "critical"


# ---------- MetricSample ----------


@dataclass(frozen=True)
class MetricSample:
    """Einzelnes Metrik-Sample.

    Pre: metric_name non-empty, timestamp > 0.
    Post: immutable, hashable.
    """

    timestamp: float
    metric_name: str
    value: float

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("metric_name must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- CorrectiveAction ----------


@dataclass(frozen=True)
class CorrectiveAction:
    """Korrektur-Aktion bei Setpoint-Deviation.

    Pre:
      - action_type non-empty
      - magnitude finite
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    action_type: str
    magnitude: float
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.action_type:
            raise ValueError("action_type must be non-empty")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- HomeostasisDecision ----------


@dataclass(frozen=True)
class HomeostasisDecision:
    """Single tick decision aus HomeostasisController.

    Pre:
      - state in HomeostasisState
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    state: HomeostasisState
    current_value: float
    setpoint: float
    deviation_pct: float
    action: Optional[CorrectiveAction]
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- HomeostasisController ----------


class HomeostasisController:
    """Setpoint-basierter Feedback-Regler mit PID-aehnlichem Smoothing.

    Pre:
      - mild_threshold_pct > 0
      - critical_threshold_pct > mild_threshold_pct
      - history_window >= 1
    Post: thread-safe; State-Machine NORMAL/MILD/COOLING/HEATING/CRITICAL
          basiert auf Rolling-Average ueber history_window-Samples.

    Default-Aktionen:
      - COOLING wenn avg_value > setpoint + mild_threshold (relative %)
      - HEATING wenn avg_value < setpoint - mild_threshold (relative %)
      - CRITICAL wenn |deviation| >= critical_threshold (relative %)
      - MILD_DEVIATION wenn |deviation| zwischen mild und critical aber kein
        Custom-Action registriert (informativ ohne CorrectiveAction)

    Custom-Actions koennen per register_action(state, fn) hinterlegt werden;
    fn(deviation_pct) -> CorrectiveAction wird im evaluate() aufgerufen.
    """

    def __init__(
        self,
        setpoint: float,
        mild_threshold_pct: float = 5.0,
        critical_threshold_pct: float = 25.0,
        history_window: int = 50,
    ) -> None:
        if mild_threshold_pct <= 0:
            raise ValueError("mild_threshold_pct must be > 0")
        if critical_threshold_pct <= mild_threshold_pct:
            raise ValueError(
                "critical_threshold_pct must be > mild_threshold_pct"
            )
        if history_window < 1:
            raise ValueError("history_window must be >= 1")

        self._setpoint = float(setpoint)
        self._mild_pct = float(mild_threshold_pct)
        self._critical_pct = float(critical_threshold_pct)
        self._history_window = int(history_window)
        self._history: deque[MetricSample] = deque(maxlen=history_window)
        self._decisions: list[HomeostasisDecision] = []
        self._actions: dict[
            HomeostasisState, Callable[[float], CorrectiveAction]
        ] = {}
        self._lock = threading.RLock()

    @property
    def setpoint(self) -> float:
        return self._setpoint

    @property
    def mild_threshold_pct(self) -> float:
        return self._mild_pct

    @property
    def critical_threshold_pct(self) -> float:
        return self._critical_pct

    @property
    def history_window(self) -> int:
        return self._history_window

    def record_metric(self, metric_name: str, value: float) -> None:
        """Append metric sample to history (bounded by history_window).

        Pre: metric_name non-empty.
        Post: history depth <= history_window (deque maxlen enforces).
        """
        sample = MetricSample(
            timestamp=time.time(),
            metric_name=metric_name,
            value=float(value),
        )
        with self._lock:
            self._history.append(sample)

    def register_action(
        self,
        state: HomeostasisState,
        action_fn: Callable[[float], CorrectiveAction],
    ) -> None:
        """Registriert Custom-CorrectiveAction-Factory fuer einen State.

        Pre: state in HomeostasisState, action_fn callable.
        Post: bei evaluate() wird action_fn(deviation_pct) aufgerufen und
              das Resultat im HomeostasisDecision.action abgelegt.
        """
        if not isinstance(state, HomeostasisState):
            raise TypeError("state must be HomeostasisState")
        if not callable(action_fn):
            raise TypeError("action_fn must be callable")
        with self._lock:
            self._actions[state] = action_fn

    def evaluate(self) -> HomeostasisDecision:
        """Compute current state + optional CorrectiveAction.

        Pre: history nicht zwingend non-empty (leere History -> NORMAL).
        Post: HomeostasisDecision wird zurueckgegeben + im Audit-Trail abgelegt.

        State-Machine (basiert auf Rolling-Average):
          deviation_pct = (avg_value - setpoint) / setpoint * 100  (oder
                           absolute Differenz wenn setpoint == 0)

          |deviation_pct| < mild              -> NORMAL
          mild <= |deviation_pct| < critical  -> COOLING_ACTIVE (>0) oder
                                                  HEATING_ACTIVE (<0)
          |deviation_pct| >= critical         -> CRITICAL
        """
        with self._lock:
            now = time.time()
            if not self._history:
                decision = HomeostasisDecision(
                    state=HomeostasisState.NORMAL,
                    current_value=self._setpoint,
                    setpoint=self._setpoint,
                    deviation_pct=0.0,
                    action=None,
                    reason="no metrics recorded",
                    timestamp=now,
                )
                self._decisions.append(decision)
                return decision

            avg_value = sum(s.value for s in self._history) / len(self._history)

            if self._setpoint == 0.0:
                # Absolute deviation when setpoint is zero (avoid div-by-zero)
                deviation_pct = avg_value * 100.0
            else:
                deviation_pct = (
                    (avg_value - self._setpoint) / abs(self._setpoint) * 100.0
                )

            abs_dev = abs(deviation_pct)

            if abs_dev >= self._critical_pct:
                state = HomeostasisState.CRITICAL
                reason = (
                    f"|deviation|={abs_dev:.2f}% >= critical={self._critical_pct}%"
                )
            elif abs_dev >= self._mild_pct:
                if deviation_pct > 0:
                    state = HomeostasisState.COOLING_ACTIVE
                    reason = (
                        f"deviation={deviation_pct:.2f}% > mild={self._mild_pct}%"
                        f" (cooling)"
                    )
                else:
                    state = HomeostasisState.HEATING_ACTIVE
                    reason = (
                        f"deviation={deviation_pct:.2f}% < -mild={-self._mild_pct}%"
                        f" (heating)"
                    )
            else:
                state = HomeostasisState.NORMAL
                reason = (
                    f"|deviation|={abs_dev:.2f}% < mild={self._mild_pct}%"
                )

            action: Optional[CorrectiveAction] = None
            if state in (
                HomeostasisState.COOLING_ACTIVE,
                HomeostasisState.HEATING_ACTIVE,
                HomeostasisState.CRITICAL,
            ):
                custom = self._actions.get(state)
                if custom is not None:
                    action = custom(deviation_pct)
                else:
                    # Default action
                    if state == HomeostasisState.COOLING_ACTIVE:
                        action_type = "cooling"
                    elif state == HomeostasisState.HEATING_ACTIVE:
                        action_type = "heating"
                    else:
                        action_type = "critical_alarm"
                    action = CorrectiveAction(
                        action_type=action_type,
                        magnitude=abs_dev,
                        reason=reason,
                        timestamp=now,
                    )

            decision = HomeostasisDecision(
                state=state,
                current_value=avg_value,
                setpoint=self._setpoint,
                deviation_pct=deviation_pct,
                action=action,
                reason=reason,
                timestamp=now,
            )
            self._decisions.append(decision)
            return decision

    def get_history(self) -> list[MetricSample]:
        """Read-only Snapshot der bisherigen Samples."""
        with self._lock:
            return list(self._history)

    def get_decisions(self) -> list[HomeostasisDecision]:
        """Read-only Audit-Trail aller bisherigen Decisions."""
        with self._lock:
            return list(self._decisions)

    def reset(self) -> None:
        """Loeschen von History + Decisions (Actions bleiben registriert)."""
        with self._lock:
            self._history.clear()
            self._decisions.clear()


# CRUX-MK
