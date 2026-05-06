"""KMO backpressure_engine Engine [CRUX-MK].

Welle-13 Phase-8 SUBAGENT-L: Adaptive rate limiting + queue overflow prevention.

Bio-Aequivalent: Baroreflex
  Hohe Druck-Signale (Latenz, Queue-Tiefe, Errors, CPU, Memory) loesen reflexive
  Kapazitaets-Reduktion aus. Niedrige Druck-Signale erlauben Kapazitaets-Expansion
  bis zur Basis-Kapazitaet.

Pattern-Inspiration:
  - mock_hotel_server.MockRateLimiter (statisches Token-Bucket -> hier dynamisch)
  - abs_tier_engine.HormonePool (Dynamic-Adjustment auf gemessene Last)
  - sigma_switch (Schmitt-Trigger-Hysterese gegen Mode-Flapping)

Komponenten:
  - PressureSignal: Frozen-Dataclass fuer einzelnes Druck-Sample
  - SignalType: Enum (QUEUE_DEPTH/LATENCY/ERROR_RATE/CPU/MEMORY)
  - PressureSensor: Multi-Source Sampling + Aggregation (max- oder weighted-pressure)
  - AdaptiveCapacity: Hysterese-basierte Kapazitaets-Anpassung
  - BackpressureController: Orchestriert Sensor + Capacity, liefert Decisions
  - QueueOverflowGuard: Bounded Queue mit FIFO-Drain + Reject-Logik
  - ControllerDecision: Frozen-Dataclass fuer einzelne Controller-Entscheidung
"""

from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------- Signal-Types ----------


class SignalType(str, enum.Enum):
    """Klassifikation des Druck-Signals.

    Pre: aufzaehlbar, immutable.
    Post: nutzbar als dict-key (str-enum).
    """

    QUEUE_DEPTH = "queue_depth"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    CPU = "cpu"
    MEMORY = "memory"


# ---------- PressureSignal ----------


@dataclass(frozen=True)
class PressureSignal:
    """Einzelnes Druck-Sample von einer Quelle.

    Pre:
      - source_id non-empty
      - 0.0 <= level <= 1.0
      - timestamp > 0
      - signal_type in SignalType
    Post: immutable, hashable.
    """

    source_id: str
    level: float
    timestamp: float
    signal_type: SignalType

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id must be non-empty")
        if not (0.0 <= self.level <= 1.0):
            raise ValueError(f"level out of range: {self.level}")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- PressureSensor ----------


class PressureSensor:
    """Multi-Source-Sensor mit registrierten Sample-Funktionen.

    Pre: sample_fn liefert float in [0.0, 1.0].
    Post: thread-safe via internal RLock.
    """

    def __init__(
        self,
        aggregate_mode: str = "max",
        weights: Optional[dict[str, float]] = None,
    ) -> None:
        """Initialisiert Sensor.

        Pre:
          - aggregate_mode in {"max", "weighted"}
          - weights ist None oder dict[source_id -> >0 float]
        """
        if aggregate_mode not in ("max", "weighted"):
            raise ValueError(f"unknown aggregate_mode: {aggregate_mode}")
        self._aggregate_mode = aggregate_mode
        self._weights: dict[str, float] = dict(weights) if weights else {}
        self._sources: dict[str, tuple[Callable[[], float], SignalType]] = {}
        self._last_signals: list[PressureSignal] = []
        self._lock = threading.RLock()

    def register_source(
        self,
        source_id: str,
        sample_fn: Callable[[], float],
        signal_type: SignalType = SignalType.QUEUE_DEPTH,
    ) -> None:
        """Registriert eine Druck-Quelle.

        Pre: source_id non-empty, sample_fn callable.
        Post: bei sample_all() wird sample_fn() aufgerufen.
        """
        if not source_id:
            raise ValueError("source_id must be non-empty")
        if not callable(sample_fn):
            raise TypeError("sample_fn must be callable")
        with self._lock:
            self._sources[source_id] = (sample_fn, signal_type)

    def sample_all(self) -> list[PressureSignal]:
        """Sampelt alle registrierten Quellen.

        Post:
          - Liste von PressureSignals (laenge == anzahl registrierter sources).
          - Werte ausserhalb [0,1] werden geklemmt.
        """
        signals: list[PressureSignal] = []
        now = time.time()
        with self._lock:
            for src_id, (fn, sig_type) in self._sources.items():
                raw = float(fn())
                level = max(0.0, min(1.0, raw))
                signals.append(
                    PressureSignal(
                        source_id=src_id,
                        level=level,
                        timestamp=now,
                        signal_type=sig_type,
                    )
                )
            self._last_signals = signals
        return signals

    def get_aggregate_pressure(self) -> float:
        """Berechnet aggregaten Druck aus letztem Sample.

        Pre: sample_all() wurde aufgerufen ODER ist Trigger fuer Live-Sample.
        Post: 0.0 <= result <= 1.0.

        aggregate_mode="max":      max(level pro Signal)
        aggregate_mode="weighted": sum(weight*level)/sum(weight) (Default-Weight=1.0)
        """
        with self._lock:
            if not self._last_signals:
                self.sample_all()
            signals = list(self._last_signals)

        if not signals:
            return 0.0

        if self._aggregate_mode == "max":
            return max(s.level for s in signals)

        # weighted
        total_w = 0.0
        total_l = 0.0
        for s in signals:
            w = self._weights.get(s.source_id, 1.0)
            if w <= 0:
                continue
            total_w += w
            total_l += w * s.level
        if total_w == 0:
            return 0.0
        return total_l / total_w


# ---------- AdaptiveCapacity ----------


class AdaptiveCapacity:
    """Hysterese-basierte Kapazitaets-Anpassung.

    Pre:
      - base_capacity > 0
      - 0 < min_factor < 1 (z.B. 0.2 = max-Reduktion auf 20%)
      - 0 < threshold_low < threshold_high <= 1.0
      - 0 < step_down <= 1.0 (Reduktions-Schritt)
      - 0 < step_up <= 1.0  (Expansions-Schritt)
    Post: thread-safe, current_capacity ∈ [min_factor*base, base].

    Schmitt-Trigger:
      pressure > high  -> reduce by step_down (multiplikativ)
      pressure < low   -> expand by step_up
      low <= p <= high -> hold (Hysterese-Band, Anti-Flapping)
    """

    def __init__(
        self,
        base_capacity: float,
        min_factor: float = 0.2,
        threshold_high: float = 0.8,
        threshold_low: float = 0.4,
        step_down: float = 0.5,
        step_up: float = 0.2,
    ) -> None:
        if base_capacity <= 0:
            raise ValueError("base_capacity must be positive")
        if not (0.0 < min_factor < 1.0):
            raise ValueError(f"min_factor out of range: {min_factor}")
        if not (0.0 < threshold_low < threshold_high <= 1.0):
            raise ValueError("require 0 < threshold_low < threshold_high <= 1")
        if not (0.0 < step_down <= 1.0):
            raise ValueError(f"step_down out of range: {step_down}")
        if not (0.0 < step_up <= 1.0):
            raise ValueError(f"step_up out of range: {step_up}")

        self._base = float(base_capacity)
        self._min = float(min_factor) * self._base
        self._high = float(threshold_high)
        self._low = float(threshold_low)
        self._step_down = float(step_down)
        self._step_up = float(step_up)
        self._current = float(base_capacity)
        self._lock = threading.RLock()

    @property
    def base_capacity(self) -> float:
        return self._base

    @property
    def current_capacity(self) -> float:
        with self._lock:
            return self._current

    @property
    def threshold_high(self) -> float:
        return self._high

    @property
    def threshold_low(self) -> float:
        return self._low

    def adjust(self, pressure: float) -> float:
        """Adjustiert current_capacity basierend auf pressure.

        Pre: 0.0 <= pressure <= 1.0.
        Post: returnt neue current_capacity.

        Hysterese:
          pressure > high -> current *= (1 - step_down), clamped to [min, base]
          pressure < low  -> current += step_up * (base - current), clamped to base
          else            -> hold (kein Wechsel)
        """
        if not (0.0 <= pressure <= 1.0):
            raise ValueError(f"pressure out of range: {pressure}")
        with self._lock:
            if pressure > self._high:
                # reduce
                new_cap = self._current * (1.0 - self._step_down)
                if new_cap < self._min:
                    new_cap = self._min
                self._current = new_cap
            elif pressure < self._low:
                # expand toward base
                new_cap = self._current + self._step_up * (self._base - self._current)
                if new_cap > self._base:
                    new_cap = self._base
                self._current = new_cap
            # else: hold, kein change
            return self._current


# ---------- ControllerDecision ----------


class Decision(str, enum.Enum):
    APPLY_PRESSURE = "apply_pressure"
    RELEASE = "release"
    HOLD = "hold"


@dataclass(frozen=True)
class ControllerDecision:
    """Single tick decision from BackpressureController.

    Pre:
      - decision in Decision enum
      - new_capacity > 0
      - reason non-empty
    Post: immutable, hashable, audit-ready.
    """

    decision: Decision
    new_capacity: float
    reason: str
    timestamp: float
    pressure: float = 0.0

    def __post_init__(self) -> None:
        if self.new_capacity <= 0:
            raise ValueError("new_capacity must be positive")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")
        if not (0.0 <= self.pressure <= 1.0):
            raise ValueError(f"pressure out of range: {self.pressure}")


# ---------- BackpressureController ----------


class BackpressureController:
    """Orchestriert Sensor + AdaptiveCapacity, generiert Decisions pro tick().

    Pre:
      - rate_per_s > 0 (max ticks/sec, dient als Soft-Rate-Limit)
    Post: thread-safe via RLock.
    """

    def __init__(self, rate_per_s: int = 10) -> None:
        if rate_per_s <= 0:
            raise ValueError("rate_per_s must be positive")
        self._rate_per_s = int(rate_per_s)
        self._sensor: Optional[PressureSensor] = None
        self._capacity: Optional[AdaptiveCapacity] = None
        self._decisions: list[ControllerDecision] = []
        self._lock = threading.RLock()

    @property
    def rate_per_s(self) -> int:
        return self._rate_per_s

    def register_sensor(self, sensor: PressureSensor) -> None:
        if not isinstance(sensor, PressureSensor):
            raise TypeError("sensor must be PressureSensor")
        with self._lock:
            self._sensor = sensor

    def register_capacity(self, capacity: AdaptiveCapacity) -> None:
        if not isinstance(capacity, AdaptiveCapacity):
            raise TypeError("capacity must be AdaptiveCapacity")
        with self._lock:
            self._capacity = capacity

    def tick(self) -> ControllerDecision:
        """Eine Controller-Iteration.

        Pre: register_sensor + register_capacity vorher aufgerufen.
        Post:
          - Sensor wird gesampled
          - Capacity wird justiert
          - ControllerDecision wird zurueckgegeben + im Audit-Trail abgelegt.
        """
        with self._lock:
            if self._sensor is None:
                raise RuntimeError("sensor not registered")
            if self._capacity is None:
                raise RuntimeError("capacity not registered")

            self._sensor.sample_all()
            pressure = self._sensor.get_aggregate_pressure()
            prev_cap = self._capacity.current_capacity
            new_cap = self._capacity.adjust(pressure)

            if new_cap < prev_cap:
                decision = Decision.APPLY_PRESSURE
                reason = f"pressure={pressure:.3f} > high={self._capacity.threshold_high}"
            elif new_cap > prev_cap:
                decision = Decision.RELEASE
                reason = f"pressure={pressure:.3f} < low={self._capacity.threshold_low}"
            else:
                decision = Decision.HOLD
                reason = (
                    f"pressure={pressure:.3f} in band "
                    f"[{self._capacity.threshold_low}, {self._capacity.threshold_high}]"
                )

            cd = ControllerDecision(
                decision=decision,
                new_capacity=new_cap,
                reason=reason,
                timestamp=time.time(),
                pressure=pressure,
            )
            self._decisions.append(cd)
            return cd

    def history(self) -> list[ControllerDecision]:
        """Read-only Audit-Trail aller bisherigen Decisions."""
        with self._lock:
            return list(self._decisions)


# ---------- QueueOverflowGuard ----------


class QueueOverflowGuard:
    """Bounded queue with overflow rejection + FIFO drain.

    Pre: max_depth > 0.
    Post: thread-safe via RLock.
    """

    def __init__(self, max_depth: int) -> None:
        if max_depth <= 0:
            raise ValueError("max_depth must be positive")
        self._max = int(max_depth)
        self._q: deque[Any] = deque()
        self._lock = threading.RLock()

    @property
    def max_depth(self) -> int:
        return self._max

    def try_enqueue(self, item: Any) -> tuple[bool, int]:
        """Versucht Enqueue.

        Post:
          - (True, depth) wenn depth < max_depth nach insert.
          - (False, depth) wenn queue voll, item NICHT eingefuegt.
        """
        with self._lock:
            if len(self._q) >= self._max:
                return (False, len(self._q))
            self._q.append(item)
            return (True, len(self._q))

    def drain_one(self) -> Optional[Any]:
        """FIFO-Drain ein Element.

        Post: None wenn leer, sonst aeltestes Element.
        """
        with self._lock:
            if not self._q:
                return None
            return self._q.popleft()

    def depth(self) -> int:
        with self._lock:
            return len(self._q)
