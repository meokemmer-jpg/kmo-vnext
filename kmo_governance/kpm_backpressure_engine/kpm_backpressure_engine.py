# [CRUX-MK]
"""KPM-Backpressure-Engine Core (Welle-27 Phase-20 Bio-Pattern-Lift).

Baroreflex-on-Order-Flow:
  Order-Flow-Velocity wird gesampled (rolling window). Bei Ueberschreiten der
  Schwellen werden FlowState-Wechsel ausgeloest. Throttle-Aktionen reagieren
  reflexiv: ALLOW (NORMAL/ELEVATED) -> DELAY (THROTTLED) -> REJECT (BLOCKED).

Pattern-Quelle: kmo_governance.backpressure_engine (Welle-9, Hotel-Domain).
Bio-Aequivalent: Karotis-Sinus-Baroreflex (Drucksensoren -> vagale Hemmung).

Komponenten:
- FlowState (Enum): NORMAL, ELEVATED, THROTTLED, BLOCKED
- OrderFlowSample (frozen): single order-record fuer rolling window
- ThrottleAction (frozen): ALLOW/DELAY/REJECT decision
- BackpressureDecision (frozen): tick-result mit Audit-Trail
- KPMBackpressureEngine: Orchestriert Sampling + Evaluation + Action-Dispatch

Konfiguration:
- max_orders_per_second: hard cap fuer Order-Rate (orders/s)
- max_notional_per_minute: hard cap fuer Notional-Velocity (currency/minute)
- history_window: deque-maxlen fuer rolling sample-Behaltung (Default 60)
- elevated_threshold_pct: % der Hard-Caps fuer ELEVATED-Trigger (Default 70%)
- blocked_threshold_pct: % der Hard-Caps fuer BLOCKED-Trigger (Default 95%)

Per-Strategy + Global Flow-State (2-Achsen-Throttling).

CRUX-MK Bindung:
- K_0: Burst-Schutz verhindert Marktorder-Kaskaden bei Vola-Spikes.
- Q_0: Auto-Reject bei BLOCKED-State haelt Strategie-Sanity (kein Geistorder-Loop).
- I_min: ThrottleAction frozen + Audit-Trail (BackpressureDecision Liste).
- W_0: Rolling-Window O(1) (deque maxlen) - kein O(N)-Overhead bei hoher Frequenz.
"""

from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional


# ---------- FlowState ----------


class FlowState(str, enum.Enum):
    """Order-Flow-State (Baroreflex-Tier).

    Pre: aufzaehlbar, immutable, str-enum -> dict-key-tauglich.
    Post: 4 Stufen mit Reflex-Semantik:
        NORMAL:    Flow im Normbereich -> ALLOW
        ELEVATED:  Flow erhoeht (>elevated_threshold) -> ALLOW (warn)
        THROTTLED: Flow nahe Hard-Cap (>cap-Schwelle, <blocked) -> DELAY
        BLOCKED:   Flow ueber Hard-Cap (>blocked_threshold) -> REJECT
    """

    NORMAL = "normal"
    ELEVATED = "elevated"
    THROTTLED = "throttled"
    BLOCKED = "blocked"


# ---------- OrderFlowSample ----------


@dataclass(frozen=True)
class OrderFlowSample:
    """Einzelner Order-Flow-Record fuer rolling window.

    Pre:
      - timestamp > 0
      - strategy_id non-empty
      - instrument_id non-empty
      - order_count >= 1 (mindestens 1 Order pro Sample)
      - notional_value >= 0
    Post: immutable, hashable, audit-ready.
    """

    timestamp: float
    strategy_id: str
    instrument_id: str
    order_count: int
    notional_value: float

    def __post_init__(self) -> None:
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if self.order_count < 1:
            raise ValueError(f"order_count must be >= 1: {self.order_count}")
        if self.notional_value < 0:
            raise ValueError(f"notional_value must be non-negative: {self.notional_value}")


# ---------- ThrottleAction ----------


@dataclass(frozen=True)
class ThrottleAction:
    """Throttle-Aktion fuer eine Order.

    Pre:
      - action_type in {"ALLOW", "DELAY", "REJECT"}
      - delay_ms >= 0 (DELAY benoetigt > 0)
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    action_type: str
    delay_ms: float
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if self.action_type not in ("ALLOW", "DELAY", "REJECT"):
            raise ValueError(f"unknown action_type: {self.action_type}")
        if self.delay_ms < 0:
            raise ValueError(f"delay_ms must be non-negative: {self.delay_ms}")
        if self.action_type == "DELAY" and self.delay_ms <= 0:
            raise ValueError("DELAY requires delay_ms > 0")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- BackpressureDecision ----------


@dataclass(frozen=True)
class BackpressureDecision:
    """Backpressure-Decision pro evaluate()-Call.

    Pre:
      - state in FlowState
      - current_rate >= 0
      - max_rate > 0
      - action: ThrottleAction
      - reason non-empty
      - timestamp > 0
    Post: immutable, audit-ready.
    """

    state: FlowState
    current_rate: float
    max_rate: float
    action: ThrottleAction
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if self.current_rate < 0:
            raise ValueError(f"current_rate must be non-negative: {self.current_rate}")
        if self.max_rate <= 0:
            raise ValueError(f"max_rate must be positive: {self.max_rate}")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- KPMBackpressureEngine ----------


class KPMBackpressureEngine:
    """Order-Flow-Backpressure-Controller mit Per-Strategy + Global FlowState.

    Pre:
      - max_orders_per_second > 0
      - max_notional_per_minute > 0
      - history_window > 0
      - 0 <= elevated_threshold_pct < blocked_threshold_pct <= 100
    Post: thread-safe via RLock; rolling samples in O(1) via deque(maxlen).

    Default-Action-Map (kann via register_action() ueberschrieben werden):
      NORMAL    -> ALLOW (delay_ms=0)
      ELEVATED  -> ALLOW (delay_ms=0, reason mentions elevated)
      THROTTLED -> DELAY (delay_ms scaled by overage)
      BLOCKED   -> REJECT (delay_ms=0)
    """

    def __init__(
        self,
        max_orders_per_second: float,
        max_notional_per_minute: float,
        history_window: int = 60,
        elevated_threshold_pct: float = 70.0,
        blocked_threshold_pct: float = 95.0,
    ) -> None:
        if max_orders_per_second <= 0:
            raise ValueError("max_orders_per_second must be positive")
        if max_notional_per_minute <= 0:
            raise ValueError("max_notional_per_minute must be positive")
        if history_window <= 0:
            raise ValueError("history_window must be positive")
        if not (0.0 <= elevated_threshold_pct <= 100.0):
            raise ValueError(
                f"elevated_threshold_pct out of range: {elevated_threshold_pct}"
            )
        if not (0.0 <= blocked_threshold_pct <= 100.0):
            raise ValueError(
                f"blocked_threshold_pct out of range: {blocked_threshold_pct}"
            )
        if elevated_threshold_pct >= blocked_threshold_pct:
            raise ValueError(
                "require elevated_threshold_pct < blocked_threshold_pct"
            )

        self._max_orders_per_second = float(max_orders_per_second)
        self._max_notional_per_minute = float(max_notional_per_minute)
        self._history_window = int(history_window)
        self._elevated_pct = float(elevated_threshold_pct)
        self._blocked_pct = float(blocked_threshold_pct)

        # Global rolling buffer of all samples (across all strategies)
        self._samples_global: deque[OrderFlowSample] = deque(maxlen=history_window)
        # Per-strategy rolling buffers
        self._samples_per_strat: dict[str, deque[OrderFlowSample]] = {}

        # FlowState tracking (Achse 1 = Global, Achse 2 = Per-Strategy)
        self._global_state: FlowState = FlowState.NORMAL
        self._per_strat_state: dict[str, FlowState] = {}

        # Custom action handlers per FlowState
        self._action_handlers: dict[
            FlowState, Callable[[float], ThrottleAction]
        ] = {}

        # Audit-Trail
        self._decisions: list[BackpressureDecision] = []

        self._lock = threading.RLock()

    # ---------- Public API ----------

    def record_order(
        self,
        strategy_id: str,
        instrument_id: str,
        notional: float,
    ) -> None:
        """Records single order in rolling window (1 order per call).

        Pre:
          - strategy_id non-empty
          - instrument_id non-empty
          - notional >= 0
        Post:
          - sample appended to global + per-strategy deque
          - older samples auto-evicted via maxlen
        """
        if not strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if notional < 0:
            raise ValueError(f"notional must be non-negative: {notional}")

        sample = OrderFlowSample(
            timestamp=time.time(),
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            order_count=1,
            notional_value=float(notional),
        )

        with self._lock:
            self._samples_global.append(sample)
            buf = self._samples_per_strat.get(strategy_id)
            if buf is None:
                buf = deque(maxlen=self._history_window)
                self._samples_per_strat[strategy_id] = buf
            buf.append(sample)

    def evaluate(
        self,
        strategy_id: Optional[str] = None,
    ) -> BackpressureDecision:
        """Computes current rate + state + action.

        Pre: register_order() vorher mind. 1x aufgerufen ODER returnt NORMAL/ALLOW.
        Post:
          - Rolling rate = order_count / window-duration (in seconds)
          - State berechnet aus rate / max_rate (Schwellen elevated/blocked)
          - State per_strat aktualisiert wenn strategy_id gegeben, sonst global
          - BackpressureDecision in Audit-Trail abgelegt
        """
        with self._lock:
            now = time.time()

            # Wahl der Sample-Quelle
            if strategy_id is None:
                buf = self._samples_global
            else:
                buf = self._samples_per_strat.get(strategy_id)
                if buf is None:
                    buf = deque(maxlen=self._history_window)
                    self._samples_per_strat[strategy_id] = buf

            # Rate berechnen: orders / window-duration
            current_rate = self._compute_rate(buf, now)
            max_rate = self._max_orders_per_second

            # State bestimmen anhand pct-Schwellen
            pct = (current_rate / max_rate) * 100.0 if max_rate > 0 else 0.0
            new_state = self._classify_state(pct)

            # Per-Strategy oder global Update
            if strategy_id is None:
                prev_state = self._global_state
                self._global_state = new_state
            else:
                prev_state = self._per_strat_state.get(strategy_id, FlowState.NORMAL)
                self._per_strat_state[strategy_id] = new_state

            # Action ableiten (custom handler oder default)
            action = self._dispatch_action(new_state, current_rate, max_rate, now)

            reason = (
                f"rate={current_rate:.2f}/s ({pct:.1f}% of max={max_rate:.2f}/s) "
                f"state={prev_state.value}->{new_state.value}"
            )

            decision = BackpressureDecision(
                state=new_state,
                current_rate=current_rate,
                max_rate=max_rate,
                action=action,
                reason=reason,
                timestamp=now,
            )
            self._decisions.append(decision)
            return decision

    def register_action(
        self,
        state: FlowState,
        action_fn: Callable[[float], ThrottleAction],
    ) -> None:
        """Registers custom action-handler for a given FlowState.

        Pre:
          - state in FlowState
          - action_fn callable, takes (current_rate) -> ThrottleAction
        Post: bei evaluate() wird action_fn(current_rate) aufgerufen statt Default.
        """
        if not isinstance(state, FlowState):
            raise TypeError("state must be FlowState")
        if not callable(action_fn):
            raise TypeError("action_fn must be callable")
        with self._lock:
            self._action_handlers[state] = action_fn

    def get_state(
        self,
        strategy_id: Optional[str] = None,
    ) -> FlowState:
        """Returns current FlowState.

        Pre: -
        Post:
          - strategy_id is None -> global state
          - strategy_id given -> per-strategy state (NORMAL falls keine Samples)
        """
        with self._lock:
            if strategy_id is None:
                return self._global_state
            return self._per_strat_state.get(strategy_id, FlowState.NORMAL)

    def get_decisions(self) -> tuple[BackpressureDecision, ...]:
        """Read-only Audit-Trail aller bisherigen Decisions (immutable Snapshot).

        Post: tuple in Insertion-Order, len = Anzahl evaluate()-Calls.
        """
        with self._lock:
            return tuple(self._decisions)

    def reset(self) -> None:
        """Loescht alle Samples + States + Decisions (kompletter Reset).

        Post:
          - Global + per-strategy buffers leer
          - States auf NORMAL
          - Decision-Trail leer
        """
        with self._lock:
            self._samples_global.clear()
            self._samples_per_strat.clear()
            self._global_state = FlowState.NORMAL
            self._per_strat_state.clear()
            self._decisions.clear()

    # ---------- Internals ----------

    def _compute_rate(
        self,
        buf: deque[OrderFlowSample],
        now: float,
    ) -> float:
        """Computes orders/second als rolling-window-rate.

        Pre: buf ist deque[OrderFlowSample], now > 0.
        Post:
          - empty buf -> 0.0
          - sonst sum(order_count) / window_duration_seconds
          - window_duration = max(1.0, now - oldest_sample_ts) (min 1s damit Rate stabil)
        """
        if not buf:
            return 0.0

        # Snapshot to avoid mutation during iteration
        snapshot = list(buf)
        oldest_ts = snapshot[0].timestamp
        duration_s = max(1.0, now - oldest_ts)

        total_orders = sum(s.order_count for s in snapshot)
        return total_orders / duration_s

    def _classify_state(self, pct: float) -> FlowState:
        """Maps Pct-of-Cap -> FlowState (Schmitt-Trigger ohne Hysterese).

        Pre: pct >= 0.
        Post:
          - pct < elevated_pct       -> NORMAL
          - pct < blocked_pct        -> ELEVATED (oder THROTTLED ab elevated)
          - pct >= blocked_pct       -> BLOCKED

        Schwellen-Mapping:
          [0, elevated)             = NORMAL
          [elevated, mid_band)      = ELEVATED
          [mid_band, blocked)       = THROTTLED
          [blocked, ...)            = BLOCKED
        wo mid_band = (elevated + blocked) / 2
        """
        if pct >= self._blocked_pct:
            return FlowState.BLOCKED
        mid_band = (self._elevated_pct + self._blocked_pct) / 2.0
        if pct >= mid_band:
            return FlowState.THROTTLED
        if pct >= self._elevated_pct:
            return FlowState.ELEVATED
        return FlowState.NORMAL

    def _dispatch_action(
        self,
        state: FlowState,
        current_rate: float,
        max_rate: float,
        now: float,
    ) -> ThrottleAction:
        """Dispatches ThrottleAction (custom handler oder Default).

        Pre: state in FlowState, current_rate >= 0, max_rate > 0, now > 0.
        Post: returnt ThrottleAction (immutable).

        Default-Map:
          NORMAL    -> ALLOW (delay_ms=0)
          ELEVATED  -> ALLOW (delay_ms=0, reason warns)
          THROTTLED -> DELAY (delay_ms = 100 * (rate/max - 1) ... gerundet, min 1ms)
          BLOCKED   -> REJECT (delay_ms=0)
        """
        # Custom handler hat Vorrang
        handler = self._action_handlers.get(state)
        if handler is not None:
            return handler(current_rate)

        # Default-Map
        if state == FlowState.NORMAL:
            return ThrottleAction(
                action_type="ALLOW",
                delay_ms=0.0,
                reason="flow normal",
                timestamp=now,
            )
        if state == FlowState.ELEVATED:
            return ThrottleAction(
                action_type="ALLOW",
                delay_ms=0.0,
                reason="flow elevated (warn-only)",
                timestamp=now,
            )
        if state == FlowState.THROTTLED:
            # Linear scaling: ueber max_rate -> staerker drosseln
            overage_factor = max(0.0, (current_rate / max_rate) - 1.0)
            delay = max(1.0, 100.0 * (1.0 + overage_factor))
            return ThrottleAction(
                action_type="DELAY",
                delay_ms=delay,
                reason=f"flow throttled (overage_factor={overage_factor:.2f})",
                timestamp=now,
            )
        # BLOCKED
        return ThrottleAction(
            action_type="REJECT",
            delay_ms=0.0,
            reason="flow blocked (cap exceeded)",
            timestamp=now,
        )


# CRUX-MK
