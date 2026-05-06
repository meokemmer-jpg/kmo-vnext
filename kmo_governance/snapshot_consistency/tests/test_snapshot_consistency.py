# [CRUX-MK]
"""Snapshot Consistency Engine Tests."""
from __future__ import annotations

import threading

import pytest

from kmo_governance.snapshot_consistency import (
    ModuleSnapshot,
    SnapshotConsistencyEngine,
    SnapshotResult,
    SnapshotStatus,
)


def test_module_snapshot_frozen():
    s = ModuleSnapshot(
        module_id="m1",
        state_hash="abc",
        timestamp=1.0,
        state_size=10,
    )
    with pytest.raises(Exception):
        s.module_id = "modified"


def test_module_snapshot_validation():
    with pytest.raises(ValueError):
        ModuleSnapshot(module_id="", state_hash="abc", timestamp=1.0, state_size=0)
    with pytest.raises(ValueError):
        ModuleSnapshot(module_id="m", state_hash="", timestamp=1.0, state_size=0)


def test_engine_no_modules_returns_failed():
    e = SnapshotConsistencyEngine()
    result = e.snapshot()
    assert result.status == SnapshotStatus.FAILED


def test_engine_register_and_snapshot():
    e = SnapshotConsistencyEngine()
    e.register_module("m1", lambda: {"x": 1})
    result = e.snapshot()
    assert result.status == SnapshotStatus.CONSISTENT
    assert len(result.snapshots) == 1


def test_engine_multiple_modules():
    e = SnapshotConsistencyEngine()
    e.register_module("m1", lambda: {"x": 1})
    e.register_module("m2", lambda: {"y": 2})
    e.register_module("m3", lambda: {"z": 3})
    result = e.snapshot()
    assert len(result.snapshots) == 3


def test_engine_capture_exception_marks_failed():
    e = SnapshotConsistencyEngine()
    e.register_module("good", lambda: "ok")

    def broken():
        raise RuntimeError("capture broken")

    e.register_module("broken", broken)
    result = e.snapshot()
    assert result.status == SnapshotStatus.FAILED


def test_engine_register_validates_inputs():
    e = SnapshotConsistencyEngine()
    with pytest.raises(ValueError):
        e.register_module("", lambda: 1)
    with pytest.raises(TypeError):
        e.register_module("m", "not_callable")


def test_engine_unregister_idempotent():
    e = SnapshotConsistencyEngine()
    e.register_module("m", lambda: 1)
    e.unregister_module("m")
    e.unregister_module("m")  # idempotent


def test_engine_state_hash_deterministic():
    e = SnapshotConsistencyEngine()
    e.register_module("m", lambda: {"x": 1, "y": 2})
    r1 = e.snapshot()
    r2 = e.snapshot()
    # Same state -> same hash
    h1 = r1.snapshots[0].state_hash
    h2 = r2.snapshots[0].state_hash
    assert h1 == h2


def test_engine_state_hash_changes_with_state():
    state = {"counter": 0}
    e = SnapshotConsistencyEngine()
    e.register_module("m", lambda: dict(state))

    r1 = e.snapshot()
    state["counter"] += 1
    r2 = e.snapshot()

    assert r1.snapshots[0].state_hash != r2.snapshots[0].state_hash


def test_engine_compare_snapshots_unchanged():
    e = SnapshotConsistencyEngine()
    e.register_module("m1", lambda: {"x": 1})
    r1 = e.snapshot()
    r2 = e.snapshot()
    diffs = e.compare_snapshots(r1, r2)
    assert diffs["m1"] == "unchanged"


def test_engine_compare_snapshots_diff():
    state = {"counter": 0}
    e = SnapshotConsistencyEngine()
    e.register_module("m1", lambda: dict(state))

    r1 = e.snapshot()
    state["counter"] = 99
    r2 = e.snapshot()

    diffs = e.compare_snapshots(r1, r2)
    assert "hash differs" in diffs["m1"]


def test_engine_concurrent_snapshots_50_threads():
    e = SnapshotConsistencyEngine()
    e.register_module("m1", lambda: {"x": 1})
    e.register_module("m2", lambda: {"y": 2})

    results = []
    lock = threading.Lock()

    def worker():
        r = e.snapshot()
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 50
    # Alle CONSISTENT (no modifications during)
    consistent = sum(1 for r in results if r.status == SnapshotStatus.CONSISTENT)
    assert consistent == 50
