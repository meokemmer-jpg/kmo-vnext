# [CRUX-MK]
"""Tests fuer HomeostasisController (Welle-25 Phase-18).

Bio-Aequivalent: Thermoregulation. Setpoint-basierte Feedback-Regelung mit
Cooling/Heating-Mechanismen ueber/unter Schwellen, PID-aehnliches Smoothing.
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.homeostasis_controller import (
    CorrectiveAction,
    HomeostasisController,
    HomeostasisDecision,
    HomeostasisState,
    MetricSample,
)


# ---------- 1. Init Validation ----------


def test_init_validation():
    # mild_threshold_pct must be > 0
    with pytest.raises(ValueError):
        HomeostasisController(setpoint=37.0, mild_threshold_pct=0.0)
    with pytest.raises(ValueError):
        HomeostasisController(setpoint=37.0, mild_threshold_pct=-1.0)

    # critical_threshold_pct must be > mild_threshold_pct
    with pytest.raises(ValueError):
        HomeostasisController(
            setpoint=37.0, mild_threshold_pct=5.0, critical_threshold_pct=5.0
        )
    with pytest.raises(ValueError):
        HomeostasisController(
            setpoint=37.0, mild_threshold_pct=10.0, critical_threshold_pct=5.0
        )

    # history_window must be >= 1
    with pytest.raises(ValueError):
        HomeostasisController(setpoint=37.0, history_window=0)
    with pytest.raises(ValueError):
        HomeostasisController(setpoint=37.0, history_window=-1)

    # Valid construction
    ctrl = HomeostasisController(
        setpoint=37.0,
        mild_threshold_pct=5.0,
        critical_threshold_pct=25.0,
        history_window=50,
    )
    assert ctrl.setpoint == 37.0
    assert ctrl.mild_threshold_pct == 5.0
    assert ctrl.critical_threshold_pct == 25.0
    assert ctrl.history_window == 50


# ---------- 2. Initial State NORMAL ----------


def test_initial_state_normal():
    ctrl = HomeostasisController(setpoint=37.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.NORMAL
    assert decision.current_value == 37.0
    assert decision.setpoint == 37.0
    assert decision.deviation_pct == 0.0
    assert decision.action is None
    assert "no metrics" in decision.reason


# ---------- 3. record_metric appends to history ----------


def test_record_metric_appends_history():
    ctrl = HomeostasisController(setpoint=37.0, history_window=10)
    ctrl.record_metric("cpu", 36.8)
    ctrl.record_metric("cpu", 37.0)
    ctrl.record_metric("cpu", 37.2)
    history = ctrl.get_history()
    assert len(history) == 3
    assert all(isinstance(s, MetricSample) for s in history)
    assert history[0].metric_name == "cpu"
    assert history[0].value == 36.8
    assert history[2].value == 37.2


# ---------- 4. Within setpoint -> NORMAL ----------


def test_evaluate_within_setpoint_returns_normal():
    ctrl = HomeostasisController(
        setpoint=100.0, mild_threshold_pct=5.0, critical_threshold_pct=25.0
    )
    # 100 +/- 4% (under 5% mild)
    for v in [100.0, 101.0, 99.0, 102.0, 98.0]:
        ctrl.record_metric("latency", v)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.NORMAL
    assert decision.action is None
    assert abs(decision.deviation_pct) < 5.0


# ---------- 5. Above mild threshold -> COOLING_ACTIVE ----------


def test_evaluate_above_mild_threshold_triggers_cooling():
    ctrl = HomeostasisController(
        setpoint=100.0, mild_threshold_pct=5.0, critical_threshold_pct=25.0
    )
    # Avg ~ 110 (10% > setpoint, between mild=5% and critical=25%)
    for _ in range(10):
        ctrl.record_metric("latency", 110.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.COOLING_ACTIVE
    assert decision.action is not None
    assert decision.action.action_type == "cooling"
    assert decision.deviation_pct > 5.0
    assert decision.deviation_pct < 25.0


# ---------- 6. Below mild threshold -> HEATING_ACTIVE ----------


def test_evaluate_below_mild_threshold_triggers_heating():
    ctrl = HomeostasisController(
        setpoint=100.0, mild_threshold_pct=5.0, critical_threshold_pct=25.0
    )
    # Avg ~ 90 (-10% from setpoint)
    for _ in range(10):
        ctrl.record_metric("latency", 90.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.HEATING_ACTIVE
    assert decision.action is not None
    assert decision.action.action_type == "heating"
    assert decision.deviation_pct < -5.0
    assert decision.deviation_pct > -25.0


# ---------- 7. Above critical threshold -> CRITICAL ----------


def test_evaluate_above_critical_threshold_returns_critical():
    ctrl = HomeostasisController(
        setpoint=100.0, mild_threshold_pct=5.0, critical_threshold_pct=25.0
    )
    # Avg ~ 130 (30% > setpoint, > critical=25%)
    for _ in range(10):
        ctrl.record_metric("latency", 130.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.CRITICAL
    assert decision.action is not None
    assert decision.action.action_type == "critical_alarm"
    assert abs(decision.deviation_pct) >= 25.0


# ---------- 8. Rolling average smoothing (single spike does not trigger) ----------


def test_evaluate_uses_rolling_average():
    ctrl = HomeostasisController(
        setpoint=100.0,
        mild_threshold_pct=5.0,
        critical_threshold_pct=25.0,
        history_window=20,
    )
    # 19 samples in normal range, 1 spike -> avg should still be normal
    for _ in range(19):
        ctrl.record_metric("latency", 100.0)
    ctrl.record_metric("latency", 200.0)  # huge spike
    decision = ctrl.evaluate()
    # avg = (19*100 + 200) / 20 = 105 -> 5% deviation, MILD edge case
    # We expect state to be either NORMAL (4.x%) or just-barely COOLING
    # The point: a SINGLE spike of +100% must NOT trigger CRITICAL.
    assert decision.state != HomeostasisState.CRITICAL
    # avg = 105 -> 5% exactly is mild threshold; should NOT exceed critical
    assert decision.deviation_pct < 25.0


# ---------- 9. Custom action registration ----------


def test_register_custom_action():
    ctrl = HomeostasisController(
        setpoint=100.0, mild_threshold_pct=5.0, critical_threshold_pct=25.0
    )

    custom_calls: list[float] = []

    def custom_cooling(deviation: float) -> CorrectiveAction:
        custom_calls.append(deviation)
        return CorrectiveAction(
            action_type="custom_aircon_boost",
            magnitude=abs(deviation) * 2.0,
            reason="custom action triggered",
            timestamp=time.time(),
        )

    ctrl.register_action(HomeostasisState.COOLING_ACTIVE, custom_cooling)

    for _ in range(10):
        ctrl.record_metric("temp", 110.0)
    decision = ctrl.evaluate()

    assert decision.state == HomeostasisState.COOLING_ACTIVE
    assert decision.action is not None
    assert decision.action.action_type == "custom_aircon_boost"
    assert len(custom_calls) == 1
    assert custom_calls[0] > 5.0


# ---------- 10. history_window limits storage ----------


def test_history_window_limits_storage():
    ctrl = HomeostasisController(setpoint=100.0, history_window=10)
    for i in range(100):
        ctrl.record_metric("metric", float(i))
    history = ctrl.get_history()
    assert len(history) == 10
    # Should be the LAST 10 (90..99)
    values = [s.value for s in history]
    assert values == [float(i) for i in range(90, 100)]


# ---------- 11. reset clears state ----------


def test_reset_clears_state():
    ctrl = HomeostasisController(setpoint=100.0)
    for v in [100.0, 110.0, 105.0]:
        ctrl.record_metric("m", v)
    ctrl.evaluate()
    assert len(ctrl.get_history()) == 3
    assert len(ctrl.get_decisions()) == 1

    ctrl.reset()
    assert len(ctrl.get_history()) == 0
    assert len(ctrl.get_decisions()) == 0

    # Custom actions should NOT be cleared by reset
    def custom(d: float) -> CorrectiveAction:
        return CorrectiveAction(
            action_type="x",
            magnitude=d,
            reason="x",
            timestamp=time.time(),
        )

    ctrl.register_action(HomeostasisState.COOLING_ACTIVE, custom)
    ctrl.reset()
    # action still registered: trigger COOLING and check
    for _ in range(5):
        ctrl.record_metric("m", 110.0)
    decision = ctrl.evaluate()
    if decision.state == HomeostasisState.COOLING_ACTIVE:
        assert decision.action is not None
        assert decision.action.action_type == "x"


# ---------- 12. Concurrent record (50 threads) ----------


def test_concurrent_record_50_threads():
    ctrl = HomeostasisController(setpoint=100.0, history_window=1000)

    def worker(idx: int) -> None:
        for j in range(20):
            ctrl.record_metric(f"m{idx}", 100.0 + idx + j)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    history = ctrl.get_history()
    # 50 threads * 20 samples = 1000 expected (within window)
    assert len(history) == 1000

    # Concurrently call evaluate too
    decisions: list[HomeostasisDecision] = []

    def evaluator() -> None:
        decisions.append(ctrl.evaluate())

    eval_threads = [threading.Thread(target=evaluator) for _ in range(20)]
    for t in eval_threads:
        t.start()
    for t in eval_threads:
        t.join()
    assert len(decisions) == 20
    assert len(ctrl.get_decisions()) == 20


# ---------- 13. HomeostasisDecision frozen / immutable ----------


def test_decision_frozen_immutability():
    decision = HomeostasisDecision(
        state=HomeostasisState.NORMAL,
        current_value=37.0,
        setpoint=37.0,
        deviation_pct=0.0,
        action=None,
        reason="ok",
        timestamp=time.time(),
    )
    with pytest.raises((AttributeError, Exception)):
        decision.state = HomeostasisState.CRITICAL  # type: ignore[misc]
    with pytest.raises((AttributeError, Exception)):
        decision.current_value = 99.0  # type: ignore[misc]


# ---------- 14. CorrectiveAction frozen / immutable ----------


def test_action_frozen_immutability():
    action = CorrectiveAction(
        action_type="cooling",
        magnitude=10.0,
        reason="too hot",
        timestamp=time.time(),
    )
    with pytest.raises((AttributeError, Exception)):
        action.action_type = "heating"  # type: ignore[misc]
    with pytest.raises((AttributeError, Exception)):
        action.magnitude = 99.0  # type: ignore[misc]

    # Validation
    with pytest.raises(ValueError):
        CorrectiveAction(
            action_type="",
            magnitude=0.0,
            reason="x",
            timestamp=time.time(),
        )
    with pytest.raises(ValueError):
        CorrectiveAction(
            action_type="x",
            magnitude=0.0,
            reason="",
            timestamp=time.time(),
        )
    with pytest.raises(ValueError):
        CorrectiveAction(
            action_type="x",
            magnitude=0.0,
            reason="x",
            timestamp=0.0,
        )


# ---------- 15. get_history returns snapshot (copy) ----------


def test_get_history_snapshot():
    ctrl = HomeostasisController(setpoint=100.0)
    ctrl.record_metric("m", 100.0)
    ctrl.record_metric("m", 101.0)

    snapshot = ctrl.get_history()
    assert len(snapshot) == 2

    # Mutating the snapshot must NOT affect controller's internal state
    snapshot.clear()
    assert len(ctrl.get_history()) == 2

    # MetricSample validation
    with pytest.raises(ValueError):
        MetricSample(timestamp=time.time(), metric_name="", value=0.0)
    with pytest.raises(ValueError):
        MetricSample(timestamp=0.0, metric_name="x", value=0.0)


# CRUX-MK
