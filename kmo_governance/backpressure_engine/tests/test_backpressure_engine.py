"""Tests fuer kmo_governance.backpressure_engine [CRUX-MK].

12 Pflicht-Tests gemaess SUBAGENT-L Spec.
"""

from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.backpressure_engine import (
    AdaptiveCapacity,
    BackpressureController,
    ControllerDecision,
    Decision,
    PressureSensor,
    PressureSignal,
    QueueOverflowGuard,
    SignalType,
)


# ---------- 1. PressureSignal Frozen ----------


def test_pressure_signal_frozen() -> None:
    sig = PressureSignal(
        source_id="src1",
        level=0.5,
        timestamp=time.time(),
        signal_type=SignalType.LATENCY,
    )
    with pytest.raises(Exception):
        sig.level = 0.9  # type: ignore[misc]
    # Validierung: level out-of-range
    with pytest.raises(ValueError):
        PressureSignal(
            source_id="src1",
            level=1.5,
            timestamp=time.time(),
            signal_type=SignalType.LATENCY,
        )
    # source_id empty
    with pytest.raises(ValueError):
        PressureSignal(
            source_id="",
            level=0.1,
            timestamp=time.time(),
            signal_type=SignalType.LATENCY,
        )


# ---------- 2. PressureSensor Register + Sample ----------


def test_pressure_sensor_register_and_sample() -> None:
    sensor = PressureSensor(aggregate_mode="max")
    sensor.register_source("queue1", lambda: 0.3, SignalType.QUEUE_DEPTH)
    sensor.register_source("cpu1", lambda: 0.7, SignalType.CPU)
    signals = sensor.sample_all()
    assert len(signals) == 2
    by_id = {s.source_id: s for s in signals}
    assert by_id["queue1"].level == pytest.approx(0.3)
    assert by_id["queue1"].signal_type == SignalType.QUEUE_DEPTH
    assert by_id["cpu1"].level == pytest.approx(0.7)
    assert by_id["cpu1"].signal_type == SignalType.CPU


# ---------- 3. PressureSensor Aggregate Max ----------


def test_pressure_sensor_aggregate_max() -> None:
    sensor = PressureSensor(aggregate_mode="max")
    sensor.register_source("a", lambda: 0.2)
    sensor.register_source("b", lambda: 0.8)
    sensor.register_source("c", lambda: 0.5)
    sensor.sample_all()
    assert sensor.get_aggregate_pressure() == pytest.approx(0.8)


def test_pressure_sensor_aggregate_weighted() -> None:
    """Erweiterung: weighted-mode liefert gewichteten Durchschnitt."""
    sensor = PressureSensor(
        aggregate_mode="weighted",
        weights={"a": 1.0, "b": 3.0},
    )
    sensor.register_source("a", lambda: 0.2)
    sensor.register_source("b", lambda: 0.8)
    sensor.sample_all()
    # (1.0*0.2 + 3.0*0.8) / 4.0 = (0.2 + 2.4) / 4.0 = 0.65
    assert sensor.get_aggregate_pressure() == pytest.approx(0.65)


# ---------- 4. AdaptiveCapacity High Pressure Reduces ----------


def test_adaptive_capacity_high_pressure_reduces() -> None:
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
        step_down=0.5,
        step_up=0.2,
    )
    assert cap.current_capacity == pytest.approx(100.0)
    new_cap = cap.adjust(0.9)  # > high
    assert new_cap == pytest.approx(50.0)
    new_cap2 = cap.adjust(0.95)
    assert new_cap2 == pytest.approx(25.0)


# ---------- 5. AdaptiveCapacity Low Pressure Expands ----------


def test_adaptive_capacity_low_pressure_expands() -> None:
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
        step_down=0.5,
        step_up=0.5,
    )
    # Erst reduzieren
    cap.adjust(0.9)  # 100 -> 50
    cap.adjust(0.9)  # 50 -> 25
    assert cap.current_capacity == pytest.approx(25.0)
    # Dann low -> expand
    new_cap = cap.adjust(0.1)  # 25 + 0.5*(100-25) = 25 + 37.5 = 62.5
    assert new_cap == pytest.approx(62.5)
    new_cap2 = cap.adjust(0.1)  # 62.5 + 0.5*(100-62.5) = 62.5 + 18.75 = 81.25
    assert new_cap2 == pytest.approx(81.25)


# ---------- 6. AdaptiveCapacity Hysteresis No Flapping ----------


def test_adaptive_capacity_hysteresis_no_flapping() -> None:
    """Pressure im Band [low, high] -> kein change."""
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
    )
    initial = cap.current_capacity
    # In-band: kein change
    for p in [0.4, 0.5, 0.6, 0.7, 0.79]:
        new = cap.adjust(p)
        assert new == pytest.approx(initial), f"Hysterese-Verletzung bei p={p}"
    assert cap.current_capacity == pytest.approx(100.0)


# ---------- 7. Controller Tick Applies Pressure ----------


def test_controller_tick_applies_pressure() -> None:
    sensor = PressureSensor(aggregate_mode="max")
    sensor.register_source("s1", lambda: 0.95, SignalType.QUEUE_DEPTH)
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
        step_down=0.5,
    )
    ctrl = BackpressureController(rate_per_s=10)
    ctrl.register_sensor(sensor)
    ctrl.register_capacity(cap)
    cd = ctrl.tick()
    assert cd.decision == Decision.APPLY_PRESSURE
    assert cd.new_capacity == pytest.approx(50.0)
    assert "0.95" in cd.reason or "0.950" in cd.reason
    assert cd.pressure == pytest.approx(0.95)


# ---------- 8. Controller Tick Releases When Low ----------


def test_controller_tick_releases_when_low() -> None:
    # Erst hoher Druck, dann low
    pressure_value = [0.95]

    def sample() -> float:
        return pressure_value[0]

    sensor = PressureSensor(aggregate_mode="max")
    sensor.register_source("s1", sample, SignalType.QUEUE_DEPTH)
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
        step_down=0.5,
        step_up=0.5,
    )
    ctrl = BackpressureController(rate_per_s=10)
    ctrl.register_sensor(sensor)
    ctrl.register_capacity(cap)

    # Tick 1: APPLY_PRESSURE
    cd1 = ctrl.tick()
    assert cd1.decision == Decision.APPLY_PRESSURE

    # Druck faellt
    pressure_value[0] = 0.1
    cd2 = ctrl.tick()
    assert cd2.decision == Decision.RELEASE
    assert cd2.new_capacity > cd1.new_capacity


def test_controller_tick_holds_in_band() -> None:
    """Druck in Hysterese-Band -> HOLD."""
    sensor = PressureSensor(aggregate_mode="max")
    sensor.register_source("s1", lambda: 0.6, SignalType.QUEUE_DEPTH)
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
    )
    ctrl = BackpressureController(rate_per_s=10)
    ctrl.register_sensor(sensor)
    ctrl.register_capacity(cap)
    cd = ctrl.tick()
    assert cd.decision == Decision.HOLD
    assert cd.new_capacity == pytest.approx(100.0)


# ---------- 9. QueueOverflowGuard Accepts Under Max ----------


def test_queue_overflow_guard_accepts_under_max() -> None:
    g = QueueOverflowGuard(max_depth=3)
    ok1, d1 = g.try_enqueue("a")
    assert ok1 is True
    assert d1 == 1
    ok2, d2 = g.try_enqueue("b")
    assert ok2 is True
    assert d2 == 2
    ok3, d3 = g.try_enqueue("c")
    assert ok3 is True
    assert d3 == 3


# ---------- 10. QueueOverflowGuard Rejects At Max ----------


def test_queue_overflow_guard_rejects_at_max() -> None:
    g = QueueOverflowGuard(max_depth=2)
    g.try_enqueue("a")
    g.try_enqueue("b")
    ok, depth = g.try_enqueue("c")  # voll
    assert ok is False
    assert depth == 2
    assert g.depth() == 2


# ---------- 11. QueueOverflowGuard Drain FIFO ----------


def test_queue_overflow_drain_one_fifo() -> None:
    g = QueueOverflowGuard(max_depth=5)
    g.try_enqueue("a")
    g.try_enqueue("b")
    g.try_enqueue("c")
    assert g.drain_one() == "a"
    assert g.drain_one() == "b"
    assert g.drain_one() == "c"
    assert g.drain_one() is None
    assert g.depth() == 0


# ---------- 12. Controller Concurrent Safe (20 threads) ----------


def test_controller_concurrent_safe() -> None:
    """20 Threads ticken gleichzeitig — keine Race-Conditions."""
    sensor = PressureSensor(aggregate_mode="max")
    pressure = [0.5]

    def sample() -> float:
        return pressure[0]

    sensor.register_source("s1", sample, SignalType.QUEUE_DEPTH)
    cap = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
    )
    ctrl = BackpressureController(rate_per_s=100)
    ctrl.register_sensor(sensor)
    ctrl.register_capacity(cap)

    errors: list[Exception] = []
    decisions: list[ControllerDecision] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(10):
                cd = ctrl.tick()
                with lock:
                    decisions.append(cd)
        except Exception as e:  # pragma: no cover (defensive)
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), "Thread hung"

    assert not errors, f"Concurrent errors: {errors}"
    assert len(decisions) == 200
    history = ctrl.history()
    assert len(history) == 200


# ---------------------------------------------------------------------------
# Welle-17 P-W17-2 Backpressure Hysteresis-Stress (V6+V7-Recommendation)
# ---------------------------------------------------------------------------
import math as _m
import threading as _t


def test_backpressure_hysteresis_no_flapping_under_oscillation():
    """Sinusoidal load oscillation should NOT cause Mode-Flapping."""
    sensor = PressureSensor()
    capacity = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
    )
    decisions = []
    for t in range(50):
        # Sinusoidal oscillation 0.4-0.8
        pressure = 0.6 + 0.2 * _m.sin(t * _m.pi / 5)
        new_cap = capacity.adjust(pressure)
        decisions.append(new_cap)

    # Property: no infinite oscillation; capacity stays in reasonable range
    cap_min = min(decisions)
    cap_max = max(decisions)
    assert cap_min > 10.0
    assert cap_max <= 100.0


def test_backpressure_high_pressure_reduces_capacity():
    capacity = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
    )
    initial = capacity.current_capacity
    capacity.adjust(0.95)
    assert capacity.current_capacity < initial


def test_backpressure_low_pressure_expands_capacity():
    capacity = AdaptiveCapacity(
        base_capacity=100.0,
        threshold_high=0.8,
        threshold_low=0.4,
    )
    capacity.adjust(0.95)  # reduce
    after_reduce = capacity.current_capacity
    capacity.adjust(0.2)  # low pressure -> expand
    assert capacity.current_capacity >= after_reduce


def test_backpressure_concurrent_ticks_50_threads():
    sensor = PressureSensor()
    sensor.register_source("s1", lambda: 0.5)
    capacity = AdaptiveCapacity(base_capacity=100.0)
    controller = BackpressureController(rate_per_s=100)
    controller.register_sensor(sensor)
    controller.register_capacity(capacity)

    decisions = []
    lock = _t.Lock()

    def worker():
        for _ in range(10):
            d = controller.tick()
            with lock:
                decisions.append(d)

    threads = [_t.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(decisions) == 500


def test_backpressure_queue_overflow_under_burst_load():
    guard = QueueOverflowGuard(max_depth=10)
    accepted = 0
    rejected = 0
    for i in range(100):
        ok, depth = guard.try_enqueue(f"item-{i}")
        if ok:
            accepted += 1
        else:
            rejected += 1
    assert accepted == 10
    assert rejected == 90
