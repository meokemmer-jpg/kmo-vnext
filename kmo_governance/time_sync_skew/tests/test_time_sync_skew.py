# [CRUX-MK]
"""Time-Sync-Skew Tests."""
from __future__ import annotations

import threading

import pytest

from kmo_governance.time_sync_skew import (
    DriftDetector,
    SkewEvent,
    SkewSample,
    TimeSyncTracker,
)


def test_skew_sample_frozen():
    s = SkewSample(clock_id="c1", timestamp=1.0, offset_ms=10.0)
    with pytest.raises(Exception):
        s.clock_id = "modified"


def test_skew_sample_empty_clock_id_raises():
    with pytest.raises(ValueError):
        SkewSample(clock_id="", timestamp=1.0, offset_ms=0)


def test_tracker_window_size_validation():
    with pytest.raises(ValueError):
        TimeSyncTracker(window_size=0)


def test_tracker_register_and_sample():
    t = TimeSyncTracker()
    t.register_clock("pc1")
    t.sample_skew("pc1", 50.0)
    assert t.get_skew("pc1") == 50.0


def test_tracker_get_skew_unknown_clock():
    t = TimeSyncTracker()
    assert t.get_skew("unknown") is None


def test_tracker_median_skew_odd():
    t = TimeSyncTracker()
    for offset in [10.0, 30.0, 20.0]:
        t.sample_skew("c", offset)
    assert t.median_skew("c") == 20.0


def test_tracker_median_skew_even():
    t = TimeSyncTracker()
    for offset in [10.0, 30.0, 20.0, 40.0]:
        t.sample_skew("c", offset)
    assert t.median_skew("c") == 25.0


def test_tracker_window_size_limits_samples():
    t = TimeSyncTracker(window_size=3)
    for i in range(10):
        t.sample_skew("c", float(i))
    assert t.sample_count("c") == 3


def test_tracker_concurrent_samples_50_threads():
    t = TimeSyncTracker(window_size=10000)

    def worker(n: int):
        for i in range(20):
            t.sample_skew(f"clock-{n % 5}", float(i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for thr in threads:
        thr.start()
    for thr in threads:
        thr.join()

    total = sum(t.sample_count(f"clock-{i}") for i in range(5))
    assert total == 1000


def test_tracker_all_clocks_returns_list():
    t = TimeSyncTracker()
    t.register_clock("a")
    t.register_clock("b")
    clocks = t.all_clocks()
    assert "a" in clocks
    assert "b" in clocks


def test_drift_detector_threshold_validation():
    with pytest.raises(ValueError):
        DriftDetector(threshold_ms=0)
    with pytest.raises(ValueError):
        DriftDetector(threshold_ms=-1)


def test_drift_detector_no_breach_returns_none():
    t = TimeSyncTracker()
    d = DriftDetector(threshold_ms=100.0, tracker=t)
    t.sample_skew("c", 50.0)
    event = d.detect_drift("c")
    assert event is None


def test_drift_detector_above_threshold_emits_event():
    t = TimeSyncTracker()
    d = DriftDetector(threshold_ms=100.0, tracker=t)
    t.sample_skew("c", 150.0)
    event = d.detect_drift("c")
    assert event is not None
    assert event.breach_type == "above"
    assert event.delta_ms == 150.0


def test_drift_detector_below_threshold_emits_event():
    t = TimeSyncTracker()
    d = DriftDetector(threshold_ms=100.0, tracker=t)
    t.sample_skew("c", -200.0)
    event = d.detect_drift("c")
    assert event is not None
    assert event.breach_type == "below"


def test_drift_detector_unknown_clock_returns_none():
    d = DriftDetector(threshold_ms=100.0)
    event = d.detect_drift("unknown")
    assert event is None


def test_drift_detector_get_events_accumulates():
    t = TimeSyncTracker()
    d = DriftDetector(threshold_ms=100.0, tracker=t)
    for i in range(3):
        t.sample_skew("c", 200.0 + i)
        d.detect_drift("c")
    assert len(d.get_events()) == 3


def test_drift_detector_reset_clears_events():
    t = TimeSyncTracker()
    d = DriftDetector(threshold_ms=100.0, tracker=t)
    t.sample_skew("c", 200.0)
    d.detect_drift("c")
    d.reset()
    assert len(d.get_events()) == 0
