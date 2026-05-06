# [CRUX-MK]
"""Causal Event Log Tests."""
from __future__ import annotations

import threading

import pytest

from kmo_governance.causal_event_log import (
    CausalEvent,
    CausalEventLog,
    VectorClock,
)


def test_vector_clock_validation():
    with pytest.raises(ValueError):
        VectorClock(node_id="")


def test_vector_clock_initial_state():
    vc = VectorClock("node-A")
    assert vc.get_snapshot() == {"node-A": 0}


def test_vector_clock_tick_increments():
    vc = VectorClock("node-A")
    vc.tick()
    vc.tick()
    assert vc.get_snapshot()["node-A"] == 2


def test_vector_clock_merge_takes_max():
    vc_a = VectorClock("a")
    vc_a.tick()  # a=1
    vc_a.tick()  # a=2
    other = {"a": 1, "b": 5}
    snap = vc_a.merge(other)
    assert snap["a"] == 3  # max(2, 1) + 1 (local tick)
    assert snap["b"] == 5


def test_vector_clock_compare_equal():
    a = {"x": 1, "y": 2}
    b = {"x": 1, "y": 2}
    assert VectorClock.compare(a, b) == "equal"


def test_vector_clock_compare_before():
    a = {"x": 1, "y": 1}
    b = {"x": 2, "y": 2}
    assert VectorClock.compare(a, b) == "before"


def test_vector_clock_compare_after():
    a = {"x": 5, "y": 5}
    b = {"x": 1, "y": 1}
    assert VectorClock.compare(a, b) == "after"


def test_vector_clock_compare_concurrent():
    a = {"x": 1, "y": 5}
    b = {"x": 5, "y": 1}
    assert VectorClock.compare(a, b) == "concurrent"


def test_causal_event_frozen():
    e = CausalEvent(
        event_id="e1",
        node_id="n1",
        payload=(("k", "v"),),
        clock_snapshot=(("n1", 1),),
    )
    with pytest.raises(Exception):
        e.event_id = "modified"


def test_causal_event_validation():
    with pytest.raises(ValueError):
        CausalEvent(event_id="", node_id="n", payload=(), clock_snapshot=())


def test_log_init_validation():
    with pytest.raises(ValueError):
        CausalEventLog(node_id="")


def test_log_append_local_increments_clock():
    log = CausalEventLog("node-A")
    e = log.append_local({"action": "start"})
    assert e.get_clock()["node-A"] == 1


def test_log_receive_remote_merges_clocks():
    log = CausalEventLog("node-B")
    log.append_local({"x": 1})  # B=1
    e = log.receive_remote({"node-A": 5}, {"received": "from-A"}, "node-A")
    clock = e.get_clock()
    assert clock["node-A"] == 5
    assert clock["node-B"] == 2  # local tick after merge


def test_log_get_events_returns_all():
    log = CausalEventLog("n")
    for i in range(5):
        log.append_local({"i": i})
    assert len(log.get_events()) == 5


def test_log_get_causal_order():
    log = CausalEventLog("n")
    for i in range(3):
        log.append_local({"i": i})
    ordered = log.get_causal_order()
    assert len(ordered) == 3


def test_log_concurrent_appends_50_threads():
    log = CausalEventLog("stress")

    def worker():
        for _ in range(20):
            log.append_local({"x": 1})

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(log.get_events()) == 1000


def test_log_event_ids_unique():
    log = CausalEventLog("n")
    ids = set()
    for _ in range(50):
        e = log.append_local({})
        assert e.event_id not in ids
        ids.add(e.event_id)
