"""PRE-5 Stress-Test fuer KMO Durable State Machine [CRUX-MK].

Hochskalierung des concurrent-transition-Tests von 20 auf 100 Threads.
Test-Verdict: alle 100 Threads succeed (mit Retry), Sequence-Numbers contiguous,
keine Duplikate, keine Lcken.
"""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kmo_durable_state_machine import (
    ConcurrentTransitionError,
    DurableStateMachine,
)


def test_pre5_concurrent_transitions_100_threads(tmp_path: Path) -> None:
    """PRE-5: 100 threads race to transition, alle succeed (mit Retry),
    Sequence-Numbers contiguous.

    Verdict-Kriterien:
    - errors == []
    - sequence-Liste hat keine Duplikate
    - sequence-Liste hat keine Lcken (sortiert == range)
    - Alle 100 Threads liefern (kein Hang, timeout=30s join)
    """
    sm = DurableStateMachine(state_root=tmp_path, lock_stale_after_s=10.0)
    sm.start_workflow("wf-stress", initial_state={"hits": 0})
    n = 100
    barrier = threading.Barrier(n)
    errors: list[Exception] = []
    success_count = [0]
    success_lock = threading.Lock()
    latencies_ms: list[float] = []
    latency_lock = threading.Lock()

    def worker(idx: int) -> None:
        barrier.wait()
        t0 = time.perf_counter()
        # Retry up to 30x on contention (100 threads = mehr Konflikt)
        for attempt in range(30):
            try:
                sm.transition_phase(
                    "wf-stress", "x", f"step-{idx}", {f"k{idx}": idx}
                )
                with success_lock:
                    success_count[0] += 1
                with latency_lock:
                    latencies_ms.append((time.perf_counter() - t0) * 1000)
                return
            except ConcurrentTransitionError:
                time.sleep(0.005)
            except Exception as e:
                errors.append(e)
                return

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    t_total = time.perf_counter() - t_start

    assert errors == [], f"unexpected errors: {errors}"
    assert success_count[0] == n, f"expected {n} successes, got {success_count[0]}"

    history = sm.get_history("wf-stress")
    seqs = [e.sequence for e in history]
    assert len(seqs) == len(set(seqs)), "duplicate sequence numbers"
    assert seqs == sorted(seqs), "sequence numbers not in order"
    assert seqs[0] == 1
    assert seqs[-1] == seqs[0] + len(seqs) - 1, "gaps in sequence"

    if latencies_ms:
        p50 = statistics.median(latencies_ms)
        p95 = statistics.quantiles(latencies_ms, n=20)[18]
        p99 = statistics.quantiles(latencies_ms, n=100)[98]
        avg = statistics.mean(latencies_ms)
        mx = max(latencies_ms)
        print(
            f"\nPRE-5 DURABLE-STATE-100-THREADS: total={t_total*1000:.1f}ms "
            f"successes={success_count[0]} sequences=1..{seqs[-1]} "
            f"avg={avg:.1f}ms p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms max={mx:.1f}ms"
        )
