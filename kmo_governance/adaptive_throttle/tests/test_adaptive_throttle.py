# [CRUX-MK]
"""Adaptive Throttle Tests."""
from __future__ import annotations

import threading

import pytest

from kmo_governance.adaptive_throttle import (
    AdaptiveThrottle,
    ThrottleDecision,
    ThrottleMetric,
)
from kmo_governance.adaptive_throttle.adaptive_throttle import ThrottleAction


def test_throttle_metric_frozen():
    m = ThrottleMetric(latency_ms=10.0, error_rate=0.01, timestamp=1.0)
    with pytest.raises(Exception):
        m.latency_ms = 999.0


def test_throttle_metric_validation():
    with pytest.raises(ValueError):
        ThrottleMetric(latency_ms=-1.0, error_rate=0.0, timestamp=1.0)
    with pytest.raises(ValueError):
        ThrottleMetric(latency_ms=0, error_rate=1.5, timestamp=1.0)


def test_throttle_init_validation():
    with pytest.raises(ValueError):
        AdaptiveThrottle(base_rate=0)
    with pytest.raises(ValueError):
        AdaptiveThrottle(min_rate=0)
    with pytest.raises(ValueError):
        AdaptiveThrottle(base_rate=100, max_rate=50)
    with pytest.raises(ValueError):
        AdaptiveThrottle(target_latency_ms=0)
    with pytest.raises(ValueError):
        AdaptiveThrottle(error_threshold=1.5)
    with pytest.raises(ValueError):
        AdaptiveThrottle(increase_factor=0.9)
    with pytest.raises(ValueError):
        AdaptiveThrottle(decrease_factor=1.5)
    with pytest.raises(ValueError):
        AdaptiveThrottle(window_size=0)


def test_throttle_initial_rate_is_base():
    t = AdaptiveThrottle(base_rate=100.0)
    assert t.current_rate == 100.0


def test_throttle_no_metrics_returns_hold():
    t = AdaptiveThrottle()
    decision = t.adjust()
    assert decision.action == ThrottleAction.HOLD


def test_throttle_high_error_decreases_aggressive():
    t = AdaptiveThrottle(
        base_rate=100.0,
        error_threshold=0.05,
        decrease_factor=0.5,
    )
    for _ in range(10):
        t.record_metric(latency_ms=50.0, error_rate=0.20)
    decision = t.adjust()
    assert decision.action == ThrottleAction.DECREASE
    assert t.current_rate == 50.0


def test_throttle_high_latency_decreases_moderate():
    t = AdaptiveThrottle(
        base_rate=100.0,
        target_latency_ms=100.0,
        error_threshold=0.05,
        decrease_factor=0.5,
    )
    for _ in range(10):
        t.record_metric(latency_ms=200.0, error_rate=0.01)  # low error, high latency
    decision = t.adjust()
    assert decision.action == ThrottleAction.DECREASE
    assert t.current_rate < 100.0
    # Moderate (factor 0.75) NOT aggressive (0.5)
    assert t.current_rate >= 50.0


def test_throttle_low_pressure_increases():
    t = AdaptiveThrottle(
        base_rate=100.0,
        target_latency_ms=100.0,
        error_threshold=0.05,
        increase_factor=1.1,
    )
    for _ in range(10):
        t.record_metric(latency_ms=10.0, error_rate=0.001)  # very low pressure
    decision = t.adjust()
    assert decision.action == ThrottleAction.INCREASE
    assert t.current_rate > 100.0


def test_throttle_in_band_holds():
    t = AdaptiveThrottle(
        base_rate=100.0,
        target_latency_ms=100.0,
        error_threshold=0.05,
    )
    for _ in range(10):
        t.record_metric(latency_ms=80.0, error_rate=0.02)  # in target band
    decision = t.adjust()
    assert decision.action == ThrottleAction.HOLD


def test_throttle_max_rate_clamped():
    t = AdaptiveThrottle(
        base_rate=100.0,
        max_rate=120.0,
        increase_factor=1.5,
    )
    for _ in range(10):
        t.record_metric(latency_ms=1.0, error_rate=0.0)
    for _ in range(20):
        t.adjust()  # repeated increase
    assert t.current_rate <= 120.0


def test_throttle_min_rate_clamped():
    t = AdaptiveThrottle(
        base_rate=100.0,
        min_rate=10.0,
        error_threshold=0.05,
        decrease_factor=0.3,
    )
    for _ in range(10):
        t.record_metric(latency_ms=500.0, error_rate=0.5)
    for _ in range(20):
        t.adjust()  # repeated decrease
    assert t.current_rate >= 10.0


def test_throttle_reset_returns_to_base():
    t = AdaptiveThrottle(base_rate=100.0)
    t.record_metric(latency_ms=500.0, error_rate=0.3)
    t.adjust()
    assert t.current_rate != 100.0
    t.reset()
    assert t.current_rate == 100.0
    assert t.metric_count() == 0


def test_throttle_get_decisions_accumulates():
    t = AdaptiveThrottle()
    for i in range(5):
        t.record_metric(latency_ms=50.0, error_rate=0.01)
        t.adjust()
    assert len(t.get_decisions()) == 5


def test_throttle_window_size_limits_metrics():
    t = AdaptiveThrottle(window_size=3)
    for i in range(10):
        t.record_metric(latency_ms=float(i), error_rate=0.01)
    assert t.metric_count() == 3


def test_throttle_concurrent_metrics_50_threads():
    t = AdaptiveThrottle(window_size=10000)

    def worker():
        for _ in range(20):
            t.record_metric(latency_ms=50.0, error_rate=0.01)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for thr in threads:
        thr.start()
    for thr in threads:
        thr.join()

    assert t.metric_count() == 1000


def test_throttle_decision_frozen():
    t = AdaptiveThrottle()
    decision = t.adjust()
    with pytest.raises(Exception):
        decision.action = ThrottleAction.DECREASE
