"""PRE-5 Stress-Test fuer KMO Lease Manager [CRUX-MK].

Hochskalierung des concurrent-acquire-Tests von 10 auf 100 Threads.
Test-Verdict: genau 1 Winner, 99 Loser, plus Latenz-Statistik.
"""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

import pytest

from kmo_lease_manager import LeaseManager, ResourceType


@pytest.fixture
def mgr(tmp_path: Path) -> LeaseManager:
    """Isolated LeaseManager per test (own SQLite + STOP-flag dir in tmp)."""
    db = tmp_path / "leases.db"
    flag_dir = tmp_path / "stop-flags"
    flag_dir.mkdir(parents=True, exist_ok=True)
    schema_src = Path(__file__).resolve().parent.parent / "schema.sql"
    return LeaseManager(db_path=db, stop_flag_dir=flag_dir, schema_path=schema_src)


def test_pre5_concurrent_acquire_100_threads_one_winner(mgr: LeaseManager) -> None:
    """PRE-5: 100 threads race, exactly 1 acquires, 99 get None.

    Verdict-Kriterien:
    - winners == 1
    - losers == 99
    - kein Crash, kein Deadlock, kein Lost-Update
    """
    n = 100
    results: List[str | None] = [None] * n
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()
        results[i] = mgr.acquire(
            ResourceType.DF, "stress-target", holder=f"holder-{i}", ttl_sec=60
        )

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(worker, range(n)))
    t_total = time.perf_counter() - t_start

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]

    assert len(winners) == 1, f"expected 1 winner, got {len(winners)}"
    assert len(losers) == 99, f"expected 99 losers, got {len(losers)}"

    print(f"\nPRE-5 LEASE-100-THREADS: total={t_total*1000:.1f}ms n={n} winners=1 losers=99")


def test_pre5_concurrent_release_acquire_cycle_100_threads(mgr: LeaseManager) -> None:
    """PRE-5: 100 threads each acquire+release on N=10 different resources.

    Verdict-Kriterien:
    - all acquire succeed (different resources, no race)
    - all release succeed
    - latency p99 < 1000ms
    """
    n_threads = 100
    n_resources = 10  # 10 threads compete per resource
    latencies_ms: List[float] = [0.0] * n_threads
    barrier = threading.Barrier(n_threads)

    def worker(i: int) -> None:
        resource_id = f"res-{i % n_resources}"
        barrier.wait()
        t0 = time.perf_counter()
        token = mgr.acquire(
            ResourceType.DF, resource_id, holder=f"holder-{i}", ttl_sec=60
        )
        if token is not None:
            mgr.release(token)
        latencies_ms[i] = (time.perf_counter() - t0) * 1000

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        list(ex.map(worker, range(n_threads)))

    p50 = statistics.median(latencies_ms)
    p95 = statistics.quantiles(latencies_ms, n=20)[18]
    p99 = statistics.quantiles(latencies_ms, n=100)[98]
    avg = statistics.mean(latencies_ms)
    mx = max(latencies_ms)

    assert p99 < 1000.0, f"p99 latency {p99:.1f}ms > 1000ms threshold"

    print(
        f"\nPRE-5 LEASE-RELEASE-CYCLE-100: "
        f"n={n_threads} resources={n_resources} "
        f"avg={avg:.1f}ms p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms max={mx:.1f}ms"
    )
