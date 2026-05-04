# [CRUX-MK]
"""Observability-Layer Tests (Welle-10 Phase-6.1)."""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.observability_layer import (
    Counter,
    Gauge,
    HealthCheckRegistry,
    HealthStatus,
    Histogram,
    MetricsRegistry,
    Tracer,
)


# ---------------------------------------------------------------------------
# Counter Tests
# ---------------------------------------------------------------------------
def test_counter_starts_at_zero():
    c = Counter("test_counter")
    assert c.get() == 0


def test_counter_inc_increments():
    c = Counter("test_counter")
    c.inc()
    c.inc(5)
    assert c.get() == 6


def test_counter_negative_inc_raises():
    c = Counter("test_counter")
    with pytest.raises(ValueError):
        c.inc(-1)


def test_counter_concurrent_inc_thread_safe():
    c = Counter("test_counter")

    def worker():
        for _ in range(1000):
            c.inc()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert c.get() == 10_000


def test_counter_to_prometheus_no_labels():
    c = Counter("requests_total")
    c.inc(42)
    assert c.to_prometheus() == "requests_total 42"


def test_counter_to_prometheus_with_labels():
    c = Counter("requests_total", {"method": "GET", "status": "200"})
    c.inc(7)
    output = c.to_prometheus()
    assert "requests_total{" in output
    assert 'method="GET"' in output
    assert 'status="200"' in output
    assert "7" in output


# ---------------------------------------------------------------------------
# Gauge Tests
# ---------------------------------------------------------------------------
def test_gauge_set_and_get():
    g = Gauge("memory_mb")
    g.set(128.5)
    assert g.get() == 128.5


def test_gauge_inc_dec():
    g = Gauge("active_connections")
    g.inc(5)
    g.inc(3)
    g.dec(2)
    assert g.get() == 6.0


# ---------------------------------------------------------------------------
# Histogram Tests
# ---------------------------------------------------------------------------
def test_histogram_observe_values():
    h = Histogram("latency_seconds")
    h.observe(0.005)
    h.observe(0.05)
    h.observe(0.5)
    stats = h.get_stats()
    assert stats["count"] == 3
    assert abs(stats["sum"] - 0.555) < 0.001
    assert abs(stats["mean"] - 0.185) < 0.001


def test_histogram_buckets_distribution():
    h = Histogram("latency", buckets=(1.0, 10.0, 100.0))
    h.observe(0.5)  # falls in 1.0-bucket
    h.observe(5.0)  # falls in 10.0-bucket
    h.observe(50.0)  # falls in 100.0-bucket
    h.observe(150.0)  # falls in inf-bucket
    stats = h.get_stats()
    buckets = stats["buckets"]
    assert buckets[1.0] == 1
    assert buckets[10.0] == 2  # cumulative
    assert buckets[100.0] == 3
    assert buckets[float("inf")] == 4


# ---------------------------------------------------------------------------
# MetricsRegistry Tests
# ---------------------------------------------------------------------------
def test_metrics_registry_counter_idempotent():
    reg = MetricsRegistry()
    c1 = reg.counter("foo")
    c2 = reg.counter("foo")
    assert c1 is c2


def test_metrics_registry_to_prometheus():
    reg = MetricsRegistry()
    reg.counter("requests").inc(5)
    reg.gauge("active").set(3)
    output = reg.to_prometheus()
    assert "requests 5" in output
    assert "active 3" in output


# ---------------------------------------------------------------------------
# Tracer Tests
# ---------------------------------------------------------------------------
def test_tracer_start_and_end_span():
    t = Tracer()
    span = t.start_span("op-1")
    time.sleep(0.001)
    completed = t.end_current_span()
    assert completed.name == "op-1"
    assert completed.duration() is not None
    assert completed.duration() > 0


def test_tracer_nested_spans_parent_child():
    t = Tracer()
    parent = t.start_span("parent")
    child = t.start_span("child")
    assert child.parent_id == parent.span_id
    assert child.trace_id == parent.trace_id
    t.end_current_span()  # child
    t.end_current_span()  # parent
    assert child in parent.children


def test_tracer_completed_spans_aggregated():
    t = Tracer()
    t.start_span("a")
    t.end_current_span()
    t.start_span("b")
    t.end_current_span()
    spans = t.get_completed_spans()
    assert len(spans) == 2


# ---------------------------------------------------------------------------
# HealthCheckRegistry Tests
# ---------------------------------------------------------------------------
def test_healthcheck_register_and_run():
    h = HealthCheckRegistry()
    h.register("db", lambda: HealthStatus.UP)
    h.register("cache", lambda: HealthStatus.DEGRADED)
    results = h.run_all()
    assert results["db"] == HealthStatus.UP
    assert results["cache"] == HealthStatus.DEGRADED


def test_healthcheck_aggregate_all_up():
    h = HealthCheckRegistry()
    h.register("a", lambda: HealthStatus.UP)
    h.register("b", lambda: HealthStatus.UP)
    assert h.aggregate() == HealthStatus.UP


def test_healthcheck_aggregate_one_down():
    h = HealthCheckRegistry()
    h.register("a", lambda: HealthStatus.UP)
    h.register("b", lambda: HealthStatus.DOWN)
    h.register("c", lambda: HealthStatus.DEGRADED)
    assert h.aggregate() == HealthStatus.DOWN


def test_healthcheck_aggregate_one_degraded_no_down():
    h = HealthCheckRegistry()
    h.register("a", lambda: HealthStatus.UP)
    h.register("b", lambda: HealthStatus.DEGRADED)
    assert h.aggregate() == HealthStatus.DEGRADED


def test_healthcheck_exception_treated_as_down():
    h = HealthCheckRegistry()

    def broken_check():
        raise RuntimeError("simulated")

    h.register("broken", broken_check)
    results = h.run_all()
    assert results["broken"] == HealthStatus.DOWN
