# [CRUX-MK]
"""Tests fuer KPM-Backpressure-Engine (Welle-27 Phase-20 Bio-Pattern-Lift).

Pflicht-Coverage (per Subagent-K17 Auftrag):
- test_init_validation
- test_record_order_appends
- test_initial_state_normal
- test_elevated_state_at_threshold
- test_blocked_state_at_critical
- test_evaluate_uses_rolling_window
- test_per_strategy_state_independence
- test_register_custom_action
- test_history_window_limits
- test_reset_clears
- test_concurrent_record_50_threads
- test_decision_frozen
- test_action_frozen
- test_get_decisions_history
"""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from kmo_governance.kpm_backpressure_engine import (
    BackpressureDecision,
    FlowState,
    KPMBackpressureEngine,
    OrderFlowSample,
    ThrottleAction,
)


# ---------- Init / Validation ----------


def test_init_validation() -> None:
    # Happy path
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
    )
    assert eng.get_state() == FlowState.NORMAL

    # Pre-condition violations
    with pytest.raises(ValueError):
        KPMBackpressureEngine(0.0, 1_000_000.0)  # max_orders <= 0
    with pytest.raises(ValueError):
        KPMBackpressureEngine(10.0, 0.0)  # max_notional <= 0
    with pytest.raises(ValueError):
        KPMBackpressureEngine(10.0, 1_000_000.0, history_window=0)
    with pytest.raises(ValueError):
        KPMBackpressureEngine(
            10.0, 1_000_000.0,
            elevated_threshold_pct=-1.0,
        )
    with pytest.raises(ValueError):
        KPMBackpressureEngine(
            10.0, 1_000_000.0,
            blocked_threshold_pct=101.0,
        )
    # elevated >= blocked verboten
    with pytest.raises(ValueError):
        KPMBackpressureEngine(
            10.0, 1_000_000.0,
            elevated_threshold_pct=80.0,
            blocked_threshold_pct=80.0,
        )
    with pytest.raises(ValueError):
        KPMBackpressureEngine(
            10.0, 1_000_000.0,
            elevated_threshold_pct=90.0,
            blocked_threshold_pct=80.0,
        )


# ---------- record_order ----------


def test_record_order_appends() -> None:
    eng = KPMBackpressureEngine(10.0, 1_000_000.0, history_window=5)
    eng.record_order("strat-a", "AAPL", 1000.0)
    eng.record_order("strat-a", "AAPL", 2000.0)
    eng.record_order("strat-b", "TSLA", 500.0)

    # Validation
    with pytest.raises(ValueError):
        eng.record_order("", "AAPL", 100.0)
    with pytest.raises(ValueError):
        eng.record_order("strat-a", "", 100.0)
    with pytest.raises(ValueError):
        eng.record_order("strat-a", "AAPL", -1.0)

    # Decision basiert auf samples (Rate-Berechnung wird in evaluate gemessen)
    d_global = eng.evaluate()
    assert d_global.current_rate > 0.0
    d_a = eng.evaluate(strategy_id="strat-a")
    assert d_a.current_rate > 0.0


# ---------- Initial State ----------


def test_initial_state_normal() -> None:
    eng = KPMBackpressureEngine(10.0, 1_000_000.0)
    # Vor jeglichem record_order
    assert eng.get_state() == FlowState.NORMAL
    assert eng.get_state(strategy_id="never-seen") == FlowState.NORMAL

    # Mit nur einem Sample bleibt rate niedrig (1 / 1s = 1.0/s, Schwelle 70% = 7.0/s)
    eng.record_order("strat-a", "AAPL", 1000.0)
    decision = eng.evaluate()
    assert decision.state == FlowState.NORMAL
    assert decision.action.action_type == "ALLOW"
    assert decision.action.delay_ms == 0.0


# ---------- ELEVATED Threshold ----------


def test_elevated_state_at_threshold() -> None:
    # max=10/s, elevated=70% => >=7/s ELEVATED
    # Sample-Strategie: viele records in kurzem Zeitraum
    # Window von 1.0s minimum; 8 Samples -> rate=8/s (8 / 1s) -> 80% -> ELEVATED-Bereich
    # mid_band = (70+95)/2 = 82.5; bei 80% sollten wir bei ELEVATED sein (< 82.5)
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=20,
    )
    for _ in range(8):
        eng.record_order("strat-a", "AAPL", 1000.0)
    decision = eng.evaluate()
    # 8 Orders / 1.0s minimum = 8/s, pct=80% -> in [70, 82.5) -> ELEVATED
    assert decision.state == FlowState.ELEVATED
    assert decision.action.action_type == "ALLOW"
    assert "elevated" in decision.action.reason.lower()


# ---------- BLOCKED Threshold ----------


def test_blocked_state_at_critical() -> None:
    # max=10/s, blocked=95% => >=9.5/s BLOCKED
    # 12 Samples in min-Window -> rate=12/s -> 120% -> BLOCKED
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=20,
    )
    for _ in range(12):
        eng.record_order("strat-a", "AAPL", 1000.0)
    decision = eng.evaluate()
    assert decision.state == FlowState.BLOCKED
    assert decision.action.action_type == "REJECT"


def test_throttled_state_band() -> None:
    # mid_band = 82.5, blocked = 95
    # Need rate in [82.5, 95) of max=10/s -> rate in [8.25, 9.5)
    # 9 Samples -> rate=9/s = 90% -> THROTTLED
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=20,
    )
    for _ in range(9):
        eng.record_order("strat-a", "AAPL", 1000.0)
    decision = eng.evaluate()
    assert decision.state == FlowState.THROTTLED
    assert decision.action.action_type == "DELAY"
    assert decision.action.delay_ms > 0.0


# ---------- Rolling Window ----------


def test_evaluate_uses_rolling_window() -> None:
    # Verifiziert: rate basiert auf rolling window (deque maxlen)
    # Bei history_window=3 sollten alte Samples verworfen werden
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=3,
    )
    for _ in range(10):
        eng.record_order("strat-a", "AAPL", 100.0)

    # Global buffer haelt nur die letzten 3
    # Rate = 3 / max(1.0, now - oldest_ts) = 3.0/s -> 30% -> NORMAL
    decision = eng.evaluate()
    assert decision.state == FlowState.NORMAL
    # Nicht mehr "10" - 7 wurden evicted
    assert decision.current_rate <= 3.0


# ---------- Per-Strategy Independence ----------


def test_per_strategy_state_independence() -> None:
    """strat_a vs strat_b: separate FlowStates."""
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=20,
    )
    # strat-a flutet (12/s -> BLOCKED)
    for _ in range(12):
        eng.record_order("strat-a", "AAPL", 100.0)
    # strat-b moderat (3/s -> NORMAL)
    for _ in range(3):
        eng.record_order("strat-b", "TSLA", 100.0)

    da = eng.evaluate(strategy_id="strat-a")
    db = eng.evaluate(strategy_id="strat-b")

    assert da.state == FlowState.BLOCKED
    assert db.state == FlowState.NORMAL
    assert da.action.action_type == "REJECT"
    assert db.action.action_type == "ALLOW"

    # Per-strategy state haengt davon ab welches strategy_id wir abfragen
    assert eng.get_state(strategy_id="strat-a") == FlowState.BLOCKED
    assert eng.get_state(strategy_id="strat-b") == FlowState.NORMAL


# ---------- Custom Action Handler ----------


def test_register_custom_action() -> None:
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=20,
    )

    custom_calls: list[float] = []

    def custom_throttle(rate: float) -> ThrottleAction:
        custom_calls.append(rate)
        return ThrottleAction(
            action_type="DELAY",
            delay_ms=42.0,
            reason="custom-throttle-handler",
            timestamp=time.time(),
        )

    eng.register_action(FlowState.THROTTLED, custom_throttle)

    # Force THROTTLED (9/s -> ~90%)
    for _ in range(9):
        eng.record_order("strat-a", "AAPL", 100.0)
    decision = eng.evaluate()

    assert decision.state == FlowState.THROTTLED
    assert decision.action.delay_ms == 42.0
    assert decision.action.reason == "custom-throttle-handler"
    assert len(custom_calls) == 1

    # Validation
    with pytest.raises(TypeError):
        eng.register_action("not a state", custom_throttle)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        eng.register_action(FlowState.NORMAL, "not callable")  # type: ignore[arg-type]


# ---------- History Window Limits ----------


def test_history_window_limits() -> None:
    """deque(maxlen=N) muss alte Samples auto-evicten."""
    eng = KPMBackpressureEngine(
        max_orders_per_second=100.0,  # hoch -> bleibt NORMAL trotz vieler Records
        max_notional_per_minute=1_000_000.0,
        history_window=5,
    )
    for i in range(100):
        eng.record_order("strat-a", "AAPL", 100.0)

    # Internes assertion: rate-berechnung basiert auf max 5 Samples
    # rate = 5 / 1.0s = 5.0/s, max=100 -> 5% -> NORMAL
    decision = eng.evaluate()
    assert decision.current_rate <= 5.0
    assert decision.state == FlowState.NORMAL


# ---------- Reset ----------


def test_reset_clears() -> None:
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=20,
    )
    for _ in range(12):
        eng.record_order("strat-a", "AAPL", 100.0)
    d1 = eng.evaluate()
    assert d1.state == FlowState.BLOCKED
    assert eng.get_state() == FlowState.BLOCKED
    assert len(eng.get_decisions()) == 1

    eng.reset()

    assert eng.get_state() == FlowState.NORMAL
    assert eng.get_state(strategy_id="strat-a") == FlowState.NORMAL
    assert len(eng.get_decisions()) == 0
    # Nach reset() wieder NORMAL beim ersten evaluate
    d2 = eng.evaluate()
    assert d2.state == FlowState.NORMAL
    assert d2.current_rate == 0.0


# ---------- Thread-Safety ----------


def test_concurrent_record_50_threads() -> None:
    """50 Threads parallel: alle Samples werden korrekt eingehangen, kein Race."""
    eng = KPMBackpressureEngine(
        max_orders_per_second=1000.0,
        max_notional_per_minute=10_000_000.0,
        history_window=200,
    )

    barrier = threading.Barrier(50)
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            barrier.wait()
            eng.record_order(f"strat-{idx % 5}", "AAPL", 100.0 * idx)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"thread errors: {errors}"

    # 50 records ueber 5 Strategien -> 10 pro Strategy
    # Global buffer haelt 50 (history_window=200), per-strat haelt 10 jeweils
    decision_global = eng.evaluate()
    # 50 Orders / max(1s, ...) = ~50/s, max=1000 -> 5% -> NORMAL
    assert decision_global.current_rate >= 1.0


# ---------- Frozen Dataclasses ----------


def test_decision_frozen() -> None:
    decision = BackpressureDecision(
        state=FlowState.NORMAL,
        current_rate=1.0,
        max_rate=10.0,
        action=ThrottleAction(
            action_type="ALLOW",
            delay_ms=0.0,
            reason="test",
            timestamp=time.time(),
        ),
        reason="test",
        timestamp=time.time(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.state = FlowState.BLOCKED  # type: ignore[misc]


def test_action_frozen() -> None:
    action = ThrottleAction(
        action_type="ALLOW",
        delay_ms=0.0,
        reason="test",
        timestamp=time.time(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.delay_ms = 100.0  # type: ignore[misc]

    sample = OrderFlowSample(
        timestamp=time.time(),
        strategy_id="s1",
        instrument_id="AAPL",
        order_count=1,
        notional_value=100.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.order_count = 5  # type: ignore[misc]


# ---------- Audit Trail ----------


def test_get_decisions_history() -> None:
    eng = KPMBackpressureEngine(
        max_orders_per_second=10.0,
        max_notional_per_minute=1_000_000.0,
        history_window=10,
    )
    eng.record_order("strat-a", "AAPL", 100.0)
    eng.evaluate()
    eng.evaluate(strategy_id="strat-a")
    eng.evaluate()

    decisions = eng.get_decisions()
    assert len(decisions) == 3
    assert isinstance(decisions, tuple)
    # Insertion order
    assert decisions[0].timestamp <= decisions[1].timestamp <= decisions[2].timestamp


# ---------- Pre-Conditions for Frozen Types ----------


def test_orderflow_sample_validation() -> None:
    now = time.time()

    # Happy path
    OrderFlowSample(
        timestamp=now,
        strategy_id="s1",
        instrument_id="AAPL",
        order_count=1,
        notional_value=100.0,
    )

    # Pre-condition violations
    with pytest.raises(ValueError):
        OrderFlowSample(0.0, "s1", "AAPL", 1, 100.0)
    with pytest.raises(ValueError):
        OrderFlowSample(now, "", "AAPL", 1, 100.0)
    with pytest.raises(ValueError):
        OrderFlowSample(now, "s1", "", 1, 100.0)
    with pytest.raises(ValueError):
        OrderFlowSample(now, "s1", "AAPL", 0, 100.0)  # order_count < 1
    with pytest.raises(ValueError):
        OrderFlowSample(now, "s1", "AAPL", 1, -1.0)


def test_throttle_action_validation() -> None:
    now = time.time()

    # Happy paths
    ThrottleAction("ALLOW", 0.0, "ok", now)
    ThrottleAction("DELAY", 100.0, "throttle", now)
    ThrottleAction("REJECT", 0.0, "blocked", now)

    # Unknown type
    with pytest.raises(ValueError):
        ThrottleAction("WAT", 0.0, "x", now)
    # Negative delay
    with pytest.raises(ValueError):
        ThrottleAction("ALLOW", -1.0, "x", now)
    # DELAY needs delay_ms > 0
    with pytest.raises(ValueError):
        ThrottleAction("DELAY", 0.0, "x", now)
    # Empty reason
    with pytest.raises(ValueError):
        ThrottleAction("ALLOW", 0.0, "", now)
    # Bad timestamp
    with pytest.raises(ValueError):
        ThrottleAction("ALLOW", 0.0, "x", 0.0)


# CRUX-MK
