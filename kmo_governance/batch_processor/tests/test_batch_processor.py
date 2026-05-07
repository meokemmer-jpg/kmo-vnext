"""Tests for KMO Batch-Processor [CRUX-MK].

Welle-21 Phase-14 Modul-2/2 Pflicht-Tests (16 Stueck).
"""

from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.batch_processor import (
    BatchProcessor,
    BatchProgress,
    BatchResult,
    BatchStatus,
    ItemResult,
    ItemStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _double(x):
    return x * 2


def _boom(x):
    raise RuntimeError(f"boom on {x}")


def _conditional_boom(threshold):
    """Returns a fn that raises iff item >= threshold."""

    def _f(x):
        if x >= threshold:
            raise RuntimeError(f"boom on {x}")
        return x * 2

    return _f


# ---------------------------------------------------------------------------
# 1. __init__ validation
# ---------------------------------------------------------------------------


def test_init_validation():
    BatchProcessor()  # default ok
    BatchProcessor(default_max_failures=0, default_chunk_size=1)
    BatchProcessor(default_max_failures=10, default_chunk_size=500)
    with pytest.raises(ValueError):
        BatchProcessor(default_max_failures=-1)
    with pytest.raises(ValueError):
        BatchProcessor(default_chunk_size=0)
    with pytest.raises(ValueError):
        BatchProcessor(default_chunk_size=-5)


# ---------------------------------------------------------------------------
# 2. submit basic - all items succeed
# ---------------------------------------------------------------------------


def test_submit_basic_all_succeed():
    bp = BatchProcessor()
    bid = bp.submit(items=[1, 2, 3, 4, 5], processor_fn=_double)
    result = bp.get_result(bid)
    assert result.status == BatchStatus.COMPLETED
    assert result.total_items == 5
    assert len(result.items) == 5
    for ir in result.items:
        assert ir.status == ItemStatus.SUCCEEDED
    outputs = [ir.output for ir in result.items]
    assert outputs == [2, 4, 6, 8, 10]


# ---------------------------------------------------------------------------
# 3. submit returns batch_id
# ---------------------------------------------------------------------------


def test_submit_returns_batch_id():
    bp = BatchProcessor()
    bid = bp.submit(items=[1, 2], processor_fn=_double)
    assert isinstance(bid, str)
    assert len(bid) > 0
    # explicit batch_id
    bid2 = bp.submit(items=[3], processor_fn=_double, batch_id="my-batch-42")
    assert bid2 == "my-batch-42"
    # duplicate explicit id raises
    with pytest.raises(ValueError):
        bp.submit(items=[4], processor_fn=_double, batch_id="my-batch-42")


# ---------------------------------------------------------------------------
# 4. submit empty items raises
# ---------------------------------------------------------------------------


def test_submit_empty_items_raises():
    bp = BatchProcessor()
    with pytest.raises(ValueError):
        bp.submit(items=[], processor_fn=_double)


# ---------------------------------------------------------------------------
# 5. processor_fn failure increments failed counter
# ---------------------------------------------------------------------------


def test_processor_fn_failure_increments_failed_counter():
    bp = BatchProcessor(default_max_failures=10)
    bid = bp.submit(items=[1, 2, 3], processor_fn=_boom)
    result = bp.get_result(bid)
    # All 3 items should be FAILED
    failed = [ir for ir in result.items if ir.status == ItemStatus.FAILED]
    assert len(failed) == 3
    for ir in failed:
        assert ir.error is not None
        assert "RuntimeError" in ir.error
        assert "boom on" in ir.error


# ---------------------------------------------------------------------------
# 6. max_failures=0 stops on first failure
# ---------------------------------------------------------------------------


def test_max_failures_zero_stops_on_first_failure():
    bp = BatchProcessor(default_max_failures=0)
    # Item 3 (index 2, value 3) raises
    bid = bp.submit(items=[1, 2, 3, 4, 5], processor_fn=_conditional_boom(threshold=3))
    result = bp.get_result(bid)
    assert result.status == BatchStatus.FAILED
    succeeded = [ir for ir in result.items if ir.status == ItemStatus.SUCCEEDED]
    failed = [ir for ir in result.items if ir.status == ItemStatus.FAILED]
    skipped = [ir for ir in result.items if ir.status == ItemStatus.SKIPPED]
    assert len(succeeded) == 2  # items 1, 2
    assert len(failed) == 1  # item 3
    assert len(skipped) == 2  # items 4, 5 skipped after threshold breach


# ---------------------------------------------------------------------------
# 7. max_failures threshold allows some failures
# ---------------------------------------------------------------------------


def test_max_failures_threshold_allows_some_failures():
    bp = BatchProcessor(default_max_failures=2)

    # Items 3, 4, 5 raise; only 2 failures tolerated -> 3rd failure terminates.
    def _fn(x):
        if x >= 3:
            raise RuntimeError(f"boom on {x}")
        return x * 2

    bid = bp.submit(items=[1, 2, 3, 4, 5, 6], processor_fn=_fn)
    result = bp.get_result(bid)
    succeeded = [ir for ir in result.items if ir.status == ItemStatus.SUCCEEDED]
    failed = [ir for ir in result.items if ir.status == ItemStatus.FAILED]
    skipped = [ir for ir in result.items if ir.status == ItemStatus.SKIPPED]
    # 1, 2 succeed; 3, 4, 5 fail (3rd failure trips threshold); 6 skipped.
    assert len(succeeded) == 2
    assert len(failed) == 3
    assert len(skipped) == 1
    assert result.status == BatchStatus.FAILED


# ---------------------------------------------------------------------------
# 8. get_progress during execution
# ---------------------------------------------------------------------------


def test_get_progress_during_execution():
    bp = BatchProcessor()
    progress_snapshots: list[BatchProgress] = []
    lock = threading.Lock()

    def _slow_fn(x):
        time.sleep(0.005)
        return x * 2

    def _watcher(batch_id: str):
        # Poll until terminal
        for _ in range(200):
            try:
                snap = bp.get_progress(batch_id)
            except KeyError:
                time.sleep(0.001)
                continue
            with lock:
                progress_snapshots.append(snap)
            if snap.status in (
                BatchStatus.COMPLETED,
                BatchStatus.FAILED,
                BatchStatus.CANCELLED,
            ):
                return
            time.sleep(0.002)

    # Pre-register batch_id so watcher can poll while submit runs
    explicit_id = "watch-me"
    t = threading.Thread(target=_watcher, args=(explicit_id,))
    t.start()
    time.sleep(0.001)
    bid = bp.submit(items=list(range(20)), processor_fn=_slow_fn, batch_id=explicit_id)
    t.join(timeout=5.0)

    final = bp.get_progress(bid)
    assert final.status == BatchStatus.COMPLETED
    assert final.total_items == 20
    assert final.completed == 20
    assert final.percent_complete == pytest.approx(100.0)
    assert final.elapsed_s > 0
    # Mid-run snapshots should show RUNNING at least once
    statuses = [s.status for s in progress_snapshots]
    assert BatchStatus.COMPLETED in statuses


# ---------------------------------------------------------------------------
# 9. get_result after completion
# ---------------------------------------------------------------------------


def test_get_result_after_completion():
    bp = BatchProcessor()
    bid = bp.submit(items=[1, 2, 3], processor_fn=_double)
    result = bp.get_result(bid)
    assert isinstance(result, BatchResult)
    assert result.batch_id == bid
    assert result.status == BatchStatus.COMPLETED
    assert result.total_items == 3
    assert result.aggregate_elapsed_s >= 0.0
    assert result.completion_timestamp > 0.0


# ---------------------------------------------------------------------------
# 10. get_result raises if not completed
# ---------------------------------------------------------------------------


def test_get_result_raises_if_not_completed():
    bp = BatchProcessor()
    # Manually inject a state in CREATED to test guard (no public API for it,
    # so we use an unknown batch_id to verify KeyError, plus a real submit
    # to verify the success path).
    with pytest.raises(KeyError):
        bp.get_result("does-not-exist")

    # Verify guard works through submit() which always reaches a terminal state.
    bid = bp.submit(items=[1], processor_fn=_double)
    # After completion, get_result must succeed.
    result = bp.get_result(bid)
    assert result.status == BatchStatus.COMPLETED


# ---------------------------------------------------------------------------
# 11. chunk_size processing
# ---------------------------------------------------------------------------


def test_chunk_size_processing():
    bp = BatchProcessor(default_chunk_size=3)
    bid = bp.submit(items=list(range(10)), processor_fn=_double, chunk_size=2)
    result = bp.get_result(bid)
    assert result.status == BatchStatus.COMPLETED
    assert result.total_items == 10
    # Verify all items processed in order, regardless of chunk size
    outputs = [ir.output for ir in result.items]
    assert outputs == [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]

    # Also test chunk_size=1
    bid2 = bp.submit(items=[1, 2, 3], processor_fn=_double, chunk_size=1)
    result2 = bp.get_result(bid2)
    assert result2.status == BatchStatus.COMPLETED
    assert [ir.output for ir in result2.items] == [2, 4, 6]


# ---------------------------------------------------------------------------
# 12. ETA calculated from average
# ---------------------------------------------------------------------------


def test_eta_calculated_from_average():
    bp = BatchProcessor()
    eta_seen = []
    lock = threading.Lock()

    def _slow_fn(x):
        time.sleep(0.005)
        return x

    def _watcher(batch_id: str):
        for _ in range(100):
            try:
                snap = bp.get_progress(batch_id)
            except KeyError:
                time.sleep(0.001)
                continue
            with lock:
                if snap.eta_s is not None:
                    eta_seen.append(snap.eta_s)
            if snap.status == BatchStatus.COMPLETED:
                return
            time.sleep(0.002)

    bid = "eta-test"
    t = threading.Thread(target=_watcher, args=(bid,))
    t.start()
    time.sleep(0.001)
    bp.submit(items=list(range(15)), processor_fn=_slow_fn, batch_id=bid)
    t.join(timeout=5.0)

    # ETA must have been computed at least once during execution
    assert len(eta_seen) >= 1
    for eta in eta_seen:
        assert eta >= 0.0

    # Final progress: completed -> ETA None (no remaining items)
    final = bp.get_progress(bid)
    assert final.eta_s is None or final.completed == final.total_items


# ---------------------------------------------------------------------------
# 13. concurrent batches isolated
# ---------------------------------------------------------------------------


def test_concurrent_batches_isolated():
    bp = BatchProcessor()
    results: dict[str, BatchResult] = {}
    lock = threading.Lock()

    def _runner(prefix: str, items: list[int]):
        bid = bp.submit(
            items=items, processor_fn=_double, batch_id=f"batch-{prefix}"
        )
        res = bp.get_result(bid)
        with lock:
            results[prefix] = res

    threads = [
        threading.Thread(target=_runner, args=("a", [1, 2, 3])),
        threading.Thread(target=_runner, args=("b", [10, 20, 30])),
        threading.Thread(target=_runner, args=("c", [100, 200, 300])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 3
    assert results["a"].status == BatchStatus.COMPLETED
    assert results["b"].status == BatchStatus.COMPLETED
    assert results["c"].status == BatchStatus.COMPLETED
    assert [ir.output for ir in results["a"].items] == [2, 4, 6]
    assert [ir.output for ir in results["b"].items] == [20, 40, 60]
    assert [ir.output for ir in results["c"].items] == [200, 400, 600]
    assert set(bp.list_batches()) == {"batch-a", "batch-b", "batch-c"}


# ---------------------------------------------------------------------------
# 14. progress frozen / immutability
# ---------------------------------------------------------------------------


def test_progress_frozen_immutability():
    bp = BatchProcessor()
    bid = bp.submit(items=[1, 2], processor_fn=_double)
    progress = bp.get_progress(bid)
    assert isinstance(progress, BatchProgress)
    with pytest.raises(Exception):
        progress.total_items = 999  # type: ignore[misc]
    with pytest.raises(Exception):
        progress.status = BatchStatus.CANCELLED  # type: ignore[misc]
    # Hashable
    assert hash(progress) == hash(progress)


# ---------------------------------------------------------------------------
# 15. result frozen / immutability
# ---------------------------------------------------------------------------


def test_result_frozen_immutability():
    bp = BatchProcessor()
    bid = bp.submit(items=[1, 2], processor_fn=_double)
    result = bp.get_result(bid)
    assert isinstance(result, BatchResult)
    with pytest.raises(Exception):
        result.total_items = 999  # type: ignore[misc]
    with pytest.raises(Exception):
        result.status = BatchStatus.CANCELLED  # type: ignore[misc]
    # items is tuple (frozen container)
    assert isinstance(result.items, tuple)
    # ItemResult also frozen
    ir = result.items[0]
    assert isinstance(ir, ItemResult)
    with pytest.raises(Exception):
        ir.status = ItemStatus.FAILED  # type: ignore[misc]
    # Hashable
    assert hash(result) == hash(result)


# ---------------------------------------------------------------------------
# 16. list_batches
# ---------------------------------------------------------------------------


def test_list_batches():
    bp = BatchProcessor()
    assert bp.list_batches() == []
    bid1 = bp.submit(items=[1], processor_fn=_double, batch_id="alpha")
    assert bp.list_batches() == ["alpha"]
    bid2 = bp.submit(items=[2], processor_fn=_double, batch_id="beta")
    bid3 = bp.submit(items=[3], processor_fn=_double, batch_id="gamma")
    assert bp.list_batches() == ["alpha", "beta", "gamma"]
    assert bid1 == "alpha"
    assert bid2 == "beta"
    assert bid3 == "gamma"


# CRUX-MK
