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


# ---------------------------------------------------------------------------
# P-W11-3 V4-HIGH-2 RLock-Contention-Tests fuer observability (Welle-11)
# ---------------------------------------------------------------------------
def test_observability_counter_5000_concurrent_inc_no_loss():
    """5000 inc-Calls ueber 50 threads -> exact 5000 (kein lost update)."""
    c = Counter("stress_counter")
    n_threads = 50
    n_per_thread = 100

    def worker():
        for _ in range(n_per_thread):
            c.inc()

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.get() == n_threads * n_per_thread


def test_observability_gauge_concurrent_inc_dec_consistency():
    """50 threads each inc+dec 100x -> final = 0 (race-safe)."""
    g = Gauge("balance")

    def worker():
        for _ in range(100):
            g.inc(1.0)
            g.dec(1.0)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert g.get() == 0.0


def test_observability_histogram_concurrent_observe():
    """1000 observations across 50 threads."""
    h = Histogram("latency", buckets=(0.01, 0.1, 1.0))

    def worker():
        for i in range(20):
            h.observe(0.05)  # in 0.1-bucket

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = h.get_stats()
    assert stats["count"] == 1000


def test_observability_metrics_registry_concurrent_get_counter():
    """10 threads je get same counter via registry -> 1 instance."""
    reg = MetricsRegistry()
    counters = []
    lock = threading.Lock()

    def worker():
        c = reg.counter("shared")
        with lock:
            counters.append(c)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 10 references to SAME counter (idempotency)
    assert len(set(id(c) for c in counters)) == 1


def test_observability_tracer_concurrent_spans_isolated():
    """Tracer is per-thread; concurrent spans don't interfere."""
    t = Tracer()
    counts = {}
    lock = threading.Lock()

    def worker(name: str):
        for _ in range(5):
            t.start_span(name)
            t.end_current_span()
        spans = t.get_completed_spans()
        with lock:
            counts[name] = len([s for s in spans if s.name == name])

    threads = [threading.Thread(target=worker, args=(f"op-{i}",)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Total: 20 threads * 5 spans = 100 spans completed in tracer
    spans = t.get_completed_spans()
    assert len(spans) >= 100


# ---------------------------------------------------------------------------
# Welle-12 P-W12-1 V5-HIGH-1 Lock-Striping Tests
# ---------------------------------------------------------------------------
def test_lock_striped_registry_init_validation():
    from kmo_governance.observability_layer import LockStripedMetricsRegistry
    with pytest.raises(ValueError):
        LockStripedMetricsRegistry(n_buckets=0)
    with pytest.raises(ValueError):
        LockStripedMetricsRegistry(n_buckets=-1)


def test_lock_striped_registry_idempotent_counter():
    from kmo_governance.observability_layer import LockStripedMetricsRegistry
    reg = LockStripedMetricsRegistry(n_buckets=8)
    c1 = reg.counter("foo")
    c2 = reg.counter("foo")
    assert c1 is c2


def test_lock_striped_registry_distributes_buckets():
    from kmo_governance.observability_layer import LockStripedMetricsRegistry
    reg = LockStripedMetricsRegistry(n_buckets=8)
    for i in range(100):
        reg.counter(f"metric_{i}")
    load = reg.get_bucket_load()
    # Property: at least 4 buckets used (statistical, no perfect skew)
    assert sum(1 for n in load if n > 0) >= 4


def test_lock_striped_registry_concurrent_50_threads():
    from kmo_governance.observability_layer import LockStripedMetricsRegistry
    reg = LockStripedMetricsRegistry(n_buckets=16)

    def worker(n: int):
        c = reg.counter(f"shared_{n % 5}")  # 5 distinct names, all threads contend
        for _ in range(50):
            c.inc()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Total: 50 threads * 50 inc = 2500. Distributed across 5 counters.
    total = sum(reg.counter(f"shared_{i}").get() for i in range(5))
    assert total == 2500


def test_lock_striped_registry_gauge_and_histogram():
    from kmo_governance.observability_layer import LockStripedMetricsRegistry
    reg = LockStripedMetricsRegistry(n_buckets=4)
    g = reg.gauge("memory")
    g.set(100.0)
    assert reg.gauge("memory").get() == 100.0

    h = reg.histogram("latency")
    h.observe(0.1)
    assert reg.histogram("latency").get_stats()["count"] == 1


# ---------------------------------------------------------------------------
# Welle-12 P-W12-2 V5-HIGH-2 Prometheus-Compliance Tests
# ---------------------------------------------------------------------------
def test_prometheus_metric_name_valid():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_metric_name("requests_total")
    assert ok


def test_prometheus_metric_name_starts_with_digit_invalid():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_metric_name("123foo")
    assert not ok


def test_prometheus_metric_name_with_dash_invalid():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_metric_name("foo-bar")
    assert not ok


def test_prometheus_metric_name_empty_invalid():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_metric_name("")
    assert not ok


def test_prometheus_label_name_valid():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_label_name("method")
    assert ok


def test_prometheus_label_double_underscore_reserved():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_label_name("__name__")
    assert not ok


def test_prometheus_label_internal_double_underscore_reserved():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    ok, _ = PrometheusComplianceValidator.validate_label_name("__internal")
    assert not ok


def test_prometheus_cardinality_warn_at_threshold():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    labels_seen = [{"k": str(i)} for i in range(2000)]
    ok, msg = PrometheusComplianceValidator.check_cardinality(labels_seen, warn_at=1000)
    assert not ok
    assert "cardinality" in msg


def test_prometheus_validate_full_metric_passes():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    result = PrometheusComplianceValidator.validate_full_metric(
        "requests_total",
        labels={"method": "GET", "status": "200"},
    )
    assert result["valid"]
    assert len(result["violations"]) == 0


def test_prometheus_validate_full_metric_fails_on_bad_label():
    from kmo_governance.observability_layer import PrometheusComplianceValidator
    result = PrometheusComplianceValidator.validate_full_metric(
        "requests_total",
        labels={"__name__": "evil"},
    )
    assert not result["valid"]
    assert len(result["violations"]) >= 1
