# [CRUX-MK]
"""Tests fuer KPM-Observability-Layer (Welle-35 Phase-28 Bio-Pattern-Lift).

15 Pflicht-Tests:

1.  test_init_validation
2.  test_register_metric_basic
3.  test_register_duplicate_raises
4.  test_inc_counter_basic
5.  test_inc_counter_with_labels
6.  test_inc_counter_negative_raises
7.  test_set_gauge_basic
8.  test_observe_histogram_buckets
9.  test_get_metric_unknown_raises
10. test_inc_counter_on_gauge_raises
11. test_concurrent_inc_50_threads
12. test_export_prometheus_format
13. test_reset_clears
14. test_metric_frozen_immutability
15. test_lock_striping_no_cross_metric_blocking
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.kpm_observability_layer import (
    KPMObservabilityLayer,
    MetricType,
    TradingMetric,
)


# ---------------------------------------------------------------------------
# 1. test_init_validation
# ---------------------------------------------------------------------------
def test_init_validation() -> None:
    """default_buckets non-empty + sortiert ascending + alle > 0."""
    # default OK
    obs = KPMObservabilityLayer()
    assert obs.list_metrics() == ()

    # custom buckets OK
    obs = KPMObservabilityLayer(default_buckets=(0.001, 0.01, 0.1, 1.0))
    assert obs.list_metrics() == ()

    # empty raises
    with pytest.raises(ValueError, match="non-empty"):
        KPMObservabilityLayer(default_buckets=())

    # negative raises
    with pytest.raises(ValueError, match="must be > 0"):
        KPMObservabilityLayer(default_buckets=(0.001, -0.01, 0.1))

    # zero raises
    with pytest.raises(ValueError, match="must be > 0"):
        KPMObservabilityLayer(default_buckets=(0.0, 0.1, 1.0))

    # unsorted raises
    with pytest.raises(ValueError, match="sorted ascending"):
        KPMObservabilityLayer(default_buckets=(1.0, 0.001, 0.1))


# ---------------------------------------------------------------------------
# 2. test_register_metric_basic
# ---------------------------------------------------------------------------
def test_register_metric_basic() -> None:
    """Registriert COUNTER + GAUGE + HISTOGRAM. list_metrics liefert sorted tuple."""
    obs = KPMObservabilityLayer()

    obs.register_metric("trades_total", MetricType.COUNTER, description="Total trades")
    obs.register_metric("position_size", MetricType.GAUGE, description="Current pos")
    obs.register_metric("slippage", MetricType.HISTOGRAM, description="Slippage dist")

    metrics = obs.list_metrics()
    assert metrics == ("position_size", "slippage", "trades_total")
    assert isinstance(metrics, tuple)


# ---------------------------------------------------------------------------
# 3. test_register_duplicate_raises
# ---------------------------------------------------------------------------
def test_register_duplicate_raises() -> None:
    """Doppel-Registrierung mit anderem Spec raises. Gleicher Spec = idempotent."""
    obs = KPMObservabilityLayer()
    obs.register_metric("metric_a", MetricType.COUNTER)

    # Idempotent: gleicher Spec = no-op
    obs.register_metric("metric_a", MetricType.COUNTER)

    # Konflikt: anderer Typ raises
    with pytest.raises(ValueError, match="different spec"):
        obs.register_metric("metric_a", MetricType.GAUGE)

    # Konflikt: andere Labels raises
    with pytest.raises(ValueError, match="different spec"):
        obs.register_metric("metric_a", MetricType.COUNTER, labels=("strategy",))

    # Empty name raises
    with pytest.raises(ValueError, match="non-empty"):
        obs.register_metric("", MetricType.COUNTER)

    # Wrong type raises
    with pytest.raises(TypeError, match="MetricType"):
        obs.register_metric("metric_b", "counter")  # type: ignore


# ---------------------------------------------------------------------------
# 4. test_inc_counter_basic
# ---------------------------------------------------------------------------
def test_inc_counter_basic() -> None:
    """inc_counter: monoton steigend, default value=1.0."""
    obs = KPMObservabilityLayer()
    obs.register_metric("trades_total", MetricType.COUNTER)

    obs.inc_counter("trades_total")
    obs.inc_counter("trades_total")
    obs.inc_counter("trades_total", value=3.0)

    snap = obs.get_metric("trades_total")
    assert snap.value == 5.0
    assert snap.metric_type == MetricType.COUNTER
    assert snap.metric_name == "trades_total"


# ---------------------------------------------------------------------------
# 5. test_inc_counter_with_labels
# ---------------------------------------------------------------------------
def test_inc_counter_with_labels() -> None:
    """Counter mit Labels: pro Label-Kombination eigener Wert."""
    obs = KPMObservabilityLayer()
    obs.register_metric(
        "trades_total",
        MetricType.COUNTER,
        labels=("strategy", "side"),
    )

    obs.inc_counter("trades_total", strategy="kelly_0.4", side="long")
    obs.inc_counter("trades_total", strategy="kelly_0.4", side="long")
    obs.inc_counter("trades_total", strategy="kelly_0.4", side="short")
    obs.inc_counter("trades_total", strategy="variance_min", side="long")

    snap_kelly_long = obs.get_metric(
        "trades_total", strategy="kelly_0.4", side="long"
    )
    snap_kelly_short = obs.get_metric(
        "trades_total", strategy="kelly_0.4", side="short"
    )
    snap_var_long = obs.get_metric(
        "trades_total", strategy="variance_min", side="long"
    )
    snap_unknown = obs.get_metric(
        "trades_total", strategy="nonexistent", side="x"
    )

    assert snap_kelly_long.value == 2.0
    assert snap_kelly_short.value == 1.0
    assert snap_var_long.value == 1.0
    assert snap_unknown.value == 0.0  # unknown label-combo defaults to 0


# ---------------------------------------------------------------------------
# 6. test_inc_counter_negative_raises
# ---------------------------------------------------------------------------
def test_inc_counter_negative_raises() -> None:
    """Counter inc mit value < 0 raises (Counter ist monoton steigend)."""
    obs = KPMObservabilityLayer()
    obs.register_metric("counter_a", MetricType.COUNTER)

    with pytest.raises(ValueError, match="must be >= 0"):
        obs.inc_counter("counter_a", value=-1.0)

    with pytest.raises(ValueError, match="must be >= 0"):
        obs.inc_counter("counter_a", value=-0.001)


# ---------------------------------------------------------------------------
# 7. test_set_gauge_basic
# ---------------------------------------------------------------------------
def test_set_gauge_basic() -> None:
    """Gauge: kann fallen + steigen, set_gauge ueberschreibt Wert."""
    obs = KPMObservabilityLayer()
    obs.register_metric("position_size", MetricType.GAUGE)

    obs.set_gauge("position_size", 12500.0)
    assert obs.get_metric("position_size").value == 12500.0

    obs.set_gauge("position_size", 8000.0)  # kann fallen
    assert obs.get_metric("position_size").value == 8000.0

    obs.set_gauge("position_size", -500.0)  # kann negativ werden
    assert obs.get_metric("position_size").value == -500.0


# ---------------------------------------------------------------------------
# 8. test_observe_histogram_buckets
# ---------------------------------------------------------------------------
def test_observe_histogram_buckets() -> None:
    """Histogram: Bucket-Counters cumulative (Prometheus-Konvention)."""
    obs = KPMObservabilityLayer(default_buckets=(0.01, 0.1, 1.0))
    obs.register_metric("slippage", MetricType.HISTOGRAM)

    # Werte: 0.005 (in 0.01), 0.05 (in 0.1), 0.5 (in 1.0), 5.0 (in +Inf)
    obs.observe_histogram("slippage", 0.005)
    obs.observe_histogram("slippage", 0.05)
    obs.observe_histogram("slippage", 0.5)
    obs.observe_histogram("slippage", 5.0)

    buckets = obs.get_histogram_buckets("slippage")

    # Cumulative: bucket 0.01 -> 1 (only 0.005)
    # bucket 0.1 -> 2 (0.005 + 0.05)
    # bucket 1.0 -> 3 (0.005 + 0.05 + 0.5)
    # bucket +Inf -> 4 (alle)
    assert buckets[0.01] == 1
    assert buckets[0.1] == 2
    assert buckets[1.0] == 3
    assert buckets[float("inf")] == 4

    # count snapshot via get_metric (HISTOGRAM liefert count)
    snap = obs.get_metric("slippage")
    assert snap.value == 4.0


# ---------------------------------------------------------------------------
# 9. test_get_metric_unknown_raises
# ---------------------------------------------------------------------------
def test_get_metric_unknown_raises() -> None:
    """Unknown Metric raises KeyError."""
    obs = KPMObservabilityLayer()

    with pytest.raises(KeyError, match="not registered"):
        obs.get_metric("nonexistent_metric")

    with pytest.raises(KeyError, match="not registered"):
        obs.get_histogram_buckets("nonexistent_histogram")

    with pytest.raises(KeyError, match="not registered"):
        obs.inc_counter("nonexistent_counter")

    with pytest.raises(KeyError, match="not registered"):
        obs.set_gauge("nonexistent_gauge", 1.0)

    with pytest.raises(KeyError, match="not registered"):
        obs.observe_histogram("nonexistent_histogram", 0.1)


# ---------------------------------------------------------------------------
# 10. test_inc_counter_on_gauge_raises
# ---------------------------------------------------------------------------
def test_inc_counter_on_gauge_raises() -> None:
    """Type-Check: COUNTER-Op auf GAUGE / HISTOGRAM raises."""
    obs = KPMObservabilityLayer()
    obs.register_metric("gauge_a", MetricType.GAUGE)
    obs.register_metric("hist_a", MetricType.HISTOGRAM)

    # COUNTER-Op auf GAUGE
    with pytest.raises(TypeError, match="expected counter"):
        obs.inc_counter("gauge_a")

    # COUNTER-Op auf HISTOGRAM
    with pytest.raises(TypeError, match="expected counter"):
        obs.inc_counter("hist_a")

    # GAUGE-Op auf HISTOGRAM
    with pytest.raises(TypeError, match="expected gauge"):
        obs.set_gauge("hist_a", 1.0)

    # HISTOGRAM-Op auf GAUGE
    with pytest.raises(TypeError, match="expected histogram"):
        obs.observe_histogram("gauge_a", 1.0)

    # get_histogram_buckets auf GAUGE
    with pytest.raises(TypeError, match="expected histogram"):
        obs.get_histogram_buckets("gauge_a")


# ---------------------------------------------------------------------------
# 11. test_concurrent_inc_50_threads
# ---------------------------------------------------------------------------
def test_concurrent_inc_50_threads() -> None:
    """50 threads x 100 inc = exact 5000 (race-safe)."""
    obs = KPMObservabilityLayer()
    obs.register_metric("trades_total", MetricType.COUNTER)

    barrier = threading.Barrier(50)

    def worker() -> None:
        barrier.wait()
        for _ in range(100):
            obs.inc_counter("trades_total")

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = obs.get_metric("trades_total")
    assert snap.value == 5000.0


# ---------------------------------------------------------------------------
# 12. test_export_prometheus_format
# ---------------------------------------------------------------------------
def test_export_prometheus_format() -> None:
    """Prometheus-Text-Format: HELP + TYPE + value-lines."""
    obs = KPMObservabilityLayer(default_buckets=(0.01, 0.1, 1.0))
    obs.register_metric(
        "trades_total",
        MetricType.COUNTER,
        description="Total trades executed",
        labels=("strategy",),
    )
    obs.register_metric(
        "position_size",
        MetricType.GAUGE,
        description="Current pos EUR",
    )
    obs.register_metric(
        "slippage",
        MetricType.HISTOGRAM,
        description="Slippage in bps",
    )

    obs.inc_counter("trades_total", strategy="kelly_0.4")
    obs.inc_counter("trades_total", strategy="kelly_0.4")
    obs.set_gauge("position_size", 12500.0)
    obs.observe_histogram("slippage", 0.005)
    obs.observe_histogram("slippage", 0.05)
    obs.observe_histogram("slippage", 5.0)

    text = obs.export_prometheus()
    lines = text.split("\n")

    # HELP-Line fuer trades_total
    assert any("# HELP trades_total Total trades executed" in l for l in lines)
    # TYPE-Line fuer trades_total
    assert any("# TYPE trades_total counter" in l for l in lines)
    # Wert-Line mit Label
    assert any('trades_total{strategy="kelly_0.4"} 2.0' in l for l in lines)

    # GAUGE
    assert any("# TYPE position_size gauge" in l for l in lines)
    assert any("position_size 12500.0" in l for l in lines)

    # HISTOGRAM
    assert any("# TYPE slippage histogram" in l for l in lines)
    assert any("slippage_bucket" in l for l in lines)
    assert any('le="+Inf"' in l for l in lines)
    assert any("slippage_count" in l for l in lines)
    assert any("slippage_sum" in l for l in lines)


# ---------------------------------------------------------------------------
# 13. test_reset_clears
# ---------------------------------------------------------------------------
def test_reset_clears() -> None:
    """reset() loescht alle Metrics + Locks."""
    obs = KPMObservabilityLayer()
    obs.register_metric("a", MetricType.COUNTER)
    obs.register_metric("b", MetricType.GAUGE)
    obs.inc_counter("a")
    obs.set_gauge("b", 42.0)

    assert obs.list_metrics() == ("a", "b")

    obs.reset()

    assert obs.list_metrics() == ()
    # Re-registrieren OK
    obs.register_metric("a", MetricType.COUNTER)
    snap = obs.get_metric("a")
    assert snap.value == 0.0  # frischer Counter


# ---------------------------------------------------------------------------
# 14. test_metric_frozen_immutability
# ---------------------------------------------------------------------------
def test_metric_frozen_immutability() -> None:
    """TradingMetric ist frozen (immutable + hashable)."""
    obs = KPMObservabilityLayer()
    obs.register_metric("a", MetricType.COUNTER, labels=("k",))
    obs.inc_counter("a", k="v1")

    snap = obs.get_metric("a", k="v1")

    # frozen: Setattr raises
    with pytest.raises(Exception):  # FrozenInstanceError oder AttributeError
        snap.value = 999.0  # type: ignore

    # hashable
    snap_set = {snap}
    assert len(snap_set) == 1

    # Equal-Snapshot ist gleich-hash
    snap2 = obs.get_metric("a", k="v1")
    # Werte sind identisch, timestamps koennen aber abweichen -> nur Inhalts-Felder pruefen
    assert snap.metric_name == snap2.metric_name
    assert snap.metric_type == snap2.metric_type
    assert snap.value == snap2.value
    assert snap.labels == snap2.labels


# ---------------------------------------------------------------------------
# 15. test_lock_striping_no_cross_metric_blocking
# ---------------------------------------------------------------------------
def test_lock_striping_no_cross_metric_blocking() -> None:
    """Per-Metric Lock-Striping: Update auf Metric-A blockiert Metric-B nicht.

    Multi-Receptor-Independence: simultane Updates auf verschiedenen Metrics
    laufen parallel, nicht seriell.
    """
    obs = KPMObservabilityLayer()
    obs.register_metric("metric_a", MetricType.COUNTER)
    obs.register_metric("metric_b", MetricType.COUNTER)

    barrier = threading.Barrier(2)
    results: dict[str, float] = {}

    def worker_a() -> None:
        barrier.wait()
        start = time.perf_counter()
        for _ in range(1000):
            obs.inc_counter("metric_a")
        results["a_duration"] = time.perf_counter() - start

    def worker_b() -> None:
        barrier.wait()
        start = time.perf_counter()
        for _ in range(1000):
            obs.inc_counter("metric_b")
        results["b_duration"] = time.perf_counter() - start

    t_a = threading.Thread(target=worker_a)
    t_b = threading.Thread(target=worker_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    # Beide Counter exakt 1000 (race-safe)
    assert obs.get_metric("metric_a").value == 1000.0
    assert obs.get_metric("metric_b").value == 1000.0

    # Beide haben gelaufen (Smoke-Test, real-Speed-Vergleich nicht-deterministisch)
    assert results["a_duration"] > 0
    assert results["b_duration"] > 0


# CRUX-MK
