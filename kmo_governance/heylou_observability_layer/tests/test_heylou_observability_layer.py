from __future__ import annotations

import threading

import pytest

from kmo_governance.heylou_observability_layer import ObservabilityLayer


def test_counter_defaults_to_zero() -> None:
    layer = ObservabilityLayer()

    assert layer.get_counter("requests_total") == 0


def test_inc_counter_defaults_to_one() -> None:
    layer = ObservabilityLayer()

    layer.inc_counter("requests_total")

    assert layer.get_counter("requests_total") == 1


def test_inc_counter_accepts_custom_value() -> None:
    layer = ObservabilityLayer()

    layer.inc_counter("requests_total", 2)
    layer.inc_counter("requests_total", 3)

    assert layer.get_counter("requests_total") == 5


def test_counter_labels_are_isolated() -> None:
    layer = ObservabilityLayer()

    layer.inc_counter("requests_total", labels={"route": "/health"})
    layer.inc_counter("requests_total", labels={"route": "/api"})

    assert layer.get_counter("requests_total", labels={"route": "/health"}) == 1
    assert layer.get_counter("requests_total", labels={"route": "/api"}) == 1
    assert layer.get_counter("requests_total") == 0


def test_label_order_does_not_affect_lookup() -> None:
    layer = ObservabilityLayer()

    layer.inc_counter("requests_total", labels={"route": "/api", "method": "GET"})

    assert (
        layer.get_counter(
            "requests_total", labels={"method": "GET", "route": "/api"}
        )
        == 1
    )


def test_gauge_defaults_to_zero_float() -> None:
    layer = ObservabilityLayer()

    assert layer.get_gauge("queue_depth") == 0.0


def test_set_gauge_overwrites_previous_value() -> None:
    layer = ObservabilityLayer()

    layer.set_gauge("queue_depth", 10)
    layer.set_gauge("queue_depth", 2.5)

    assert layer.get_gauge("queue_depth") == 2.5


def test_gauge_labels_are_isolated() -> None:
    layer = ObservabilityLayer()

    layer.set_gauge("queue_depth", 2, labels={"queue": "email"})
    layer.set_gauge("queue_depth", 7, labels={"queue": "sms"})

    assert layer.get_gauge("queue_depth", labels={"queue": "email"}) == 2.0
    assert layer.get_gauge("queue_depth", labels={"queue": "sms"}) == 7.0


def test_histogram_negative_raises() -> None:
    layer = ObservabilityLayer()

    with pytest.raises(ValueError, match="non-negative"):
        layer.observe_histogram("request_duration_seconds", -0.1)


def test_empty_histogram_stats() -> None:
    layer = ObservabilityLayer()

    assert layer.get_histogram_stats("request_duration_seconds") == {
        "count": 0,
        "sum": 0.0,
        "min": None,
        "max": None,
        "p50": None,
        "p95": None,
        "p99": None,
    }


def test_histogram_stats_single_value() -> None:
    layer = ObservabilityLayer()

    layer.observe_histogram("request_duration_seconds", 0.25)

    assert layer.get_histogram_stats("request_duration_seconds") == {
        "count": 1,
        "sum": 0.25,
        "min": 0.25,
        "max": 0.25,
        "p50": 0.25,
        "p95": 0.25,
        "p99": 0.25,
    }


def test_histogram_stats_percentiles_include_p95_calculation() -> None:
    layer = ObservabilityLayer()

    for value in range(1, 101):
        layer.observe_histogram("latency_ms", value)

    stats = layer.get_histogram_stats("latency_ms")

    assert stats["count"] == 100
    assert stats["sum"] == 5050.0
    assert stats["min"] == 1.0
    assert stats["max"] == 100.0
    assert stats["p50"] == 50.5
    assert stats["p95"] == pytest.approx(95.05)
    assert stats["p99"] == pytest.approx(99.01)


def test_export_prometheus_output() -> None:
    layer = ObservabilityLayer()

    layer.inc_counter("requests_total", 3, labels={"method": "GET", "route": "/api"})
    layer.set_gauge("queue_depth", 4)
    layer.observe_histogram("latency_ms", 10, labels={"route": "/api"})
    layer.observe_histogram("latency_ms", 20, labels={"route": "/api"})

    output = layer.export_prometheus()

    assert "# TYPE requests_total counter" in output
    assert 'requests_total{method="GET",route="/api"} 3' in output
    assert "# TYPE queue_depth gauge" in output
    assert "queue_depth 4" in output
    assert "# TYPE latency_ms summary" in output
    assert 'latency_ms_count{route="/api"} 2' in output
    assert 'latency_ms_sum{route="/api"} 30' in output
    assert 'latency_ms{route="/api",quantile="50"} 15' in output
    assert 'latency_ms{route="/api",quantile="95"} 19.5' in output
    assert output.endswith("\n")


def test_thread_safety_for_counter_updates() -> None:
    layer = ObservabilityLayer()

    def increment_many() -> None:
        for _ in range(1000):
            layer.inc_counter("events_total")

    threads = [threading.Thread(target=increment_many) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert layer.get_counter("events_total") == 10000
