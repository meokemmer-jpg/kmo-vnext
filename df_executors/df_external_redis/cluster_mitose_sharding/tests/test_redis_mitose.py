"""Tests fuer Redis-Cluster Mitose-Sharding [CRUX-MK].

Coverage-Klassen:
- Topology: SlotRange-Math, Invariants, Split-Half
- Orchestrator: decide_to_split, execute_mitose, run_cycle, edge cases
- Validator: Conservation-Law (lost/duplicated/wrong-shard/coverage)
- Threading: 50 parallele Reads/Writes waehrend Resharding (Race-Conditions)
- Conservation-Law: alle Keys ueberleben Resharding (0 Lost)

Pflicht: 15+ Tests inkl. threading.Thread fuer Concurrent-Access waehrend Resharding.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from df_executors.df_external_redis.cluster_mitose_sharding import (
    DEFAULT_LOAD_THRESHOLD,
    ConservationViolation,
    MitoseOutcome,
    RedisClusterTopology,
    RedisMitoseOrchestrator,
    RedisReshardingValidator,
    ShardInfo,
    ShardState,
    SlotRange,
    TOTAL_SLOTS,
    crc16_slot,
)


# ---------- Fixtures ----------


@pytest.fixture
def fake_clock():
    state = {"t": 1000.0}

    def now() -> float:
        return state["t"]

    def advance(dt: float) -> None:
        state["t"] += dt

    now.advance = advance  # type: ignore[attr-defined]
    return now


@pytest.fixture
def topology() -> RedisClusterTopology:
    """Genesis topology: single shard owning [0, 16383]."""
    return RedisClusterTopology()


@pytest.fixture
def orchestrator(topology, fake_clock) -> RedisMitoseOrchestrator:
    return RedisMitoseOrchestrator(
        topology=topology,
        load_threshold=1000,
        min_keys_per_half=10,
        migration_batch_size=128,
        clock=fake_clock,
    )


def _build_kv_store(shard_id: str, n_keys: int) -> dict[str, dict[str, str]]:
    """Generate n_keys deterministic keys mapped to shard."""
    return {shard_id: {f"key-{i:06d}": f"value-{i}" for i in range(n_keys)}}


# ---------- Topology / SlotRange Tests (4) ----------


def test_slot_range_split_half_balanced():
    rng = SlotRange(0, 99)
    left, right = rng.split_half()
    assert left.start == 0
    assert right.end == 99
    assert left.end + 1 == right.start
    # Total width preserved.
    assert left.width() + right.width() == rng.width()


def test_slot_range_rejects_below_min():
    rng = SlotRange(0, 10)  # width 11 < 2*16
    with pytest.raises(ValueError):
        rng.split_half()


def test_topology_genesis_invariant_holds(topology):
    topology.verify_invariants()
    assert topology.shard_count() == 1


def test_topology_split_preserves_full_coverage(topology):
    topology.split_shard("shard-genesis", "shard-A", "shard-B")
    topology.verify_invariants()
    snap = topology.snapshot()
    total = sum(s.total_slots() for s in snap.shards)
    assert total == TOTAL_SLOTS


# ---------- Orchestrator Tests (5) ----------


def test_orchestrator_decide_skips_under_threshold(orchestrator, topology):
    snap = topology.snapshot()
    shard_id = snap.shards[0].shard_id
    # No key_count set; should be skipped.
    candidates = orchestrator.decide_to_split()
    assert candidates == []


def test_orchestrator_decide_picks_overloaded_shard(orchestrator, topology):
    snap = topology.snapshot()
    shard = topology.get_shard(snap.shards[0].shard_id)
    shard.key_count = 5000  # > load_threshold (1000)
    candidates = orchestrator.decide_to_split()
    assert len(candidates) == 1
    assert candidates[0] == shard.shard_id


def test_execute_mitose_divides_genesis(orchestrator, topology):
    snap = topology.snapshot()
    mother_id = snap.shards[0].shard_id
    topology.get_shard(mother_id).key_count = 2000
    kv_store = _build_kv_store(mother_id, 2000)
    event = orchestrator.execute_mitose(mother_id, kv_store)
    assert event.outcome == MitoseOutcome.DIVIDED
    assert event.daughter_a_id is not None
    assert event.daughter_b_id is not None
    assert event.keys_migrated == 2000
    # Mother shard removed; daughters present and HEALTHY.
    assert topology.get_shard(mother_id) is None
    assert topology.get_shard(event.daughter_a_id).state == ShardState.HEALTHY
    assert topology.get_shard(event.daughter_b_id).state == ShardState.HEALTHY


def test_execute_mitose_rejects_unknown_mother(orchestrator):
    event = orchestrator.execute_mitose("nonexistent", {})
    assert event.outcome == MitoseOutcome.REJECTED
    assert "not found" in event.reason


def test_run_cycle_handles_multiple_shards(topology, fake_clock):
    # Build 2-shard topology manually.
    s1 = ShardInfo(shard_id="s1", slot_ranges=[SlotRange(0, 8191)], key_count=5000)
    s2 = ShardInfo(shard_id="s2", slot_ranges=[SlotRange(8192, TOTAL_SLOTS - 1)], key_count=200)
    topo = RedisClusterTopology(initial_shards=[s1, s2])
    orch = RedisMitoseOrchestrator(
        topology=topo,
        load_threshold=1000,
        clock=fake_clock,
    )
    # Generate slot-aware keys: only keys whose CRC16-slot falls into shard's range.
    kv_store: dict[str, dict[str, str]] = {"s1": {}, "s2": {}}
    i = 0
    while len(kv_store["s1"]) < 500:
        k = f"key-s1-{i:06d}"
        if crc16_slot(k) <= 8191:
            kv_store["s1"][k] = f"v-{i}"
        i += 1
    j = 0
    while len(kv_store["s2"]) < 200:
        k = f"key-s2-{j:06d}"
        if crc16_slot(k) >= 8192:
            kv_store["s2"][k] = f"v-{j}"
        j += 1
    # Update model: s1 still considered overloaded (key_count=5000 was synthetic);
    # we only place 500 actual keys but key_count remains 5000 to trigger split.
    events = orch.run_cycle(kv_store)
    assert len(events) == 1  # only s1 over threshold
    assert events[0].mother_shard_id == "s1"
    assert events[0].outcome == MitoseOutcome.DIVIDED
    topo.verify_invariants()


# ---------- Validator / Conservation-Law Tests (3) ----------


def test_validator_passes_on_clean_split(orchestrator, topology):
    snap = topology.snapshot()
    mother_id = snap.shards[0].shard_id
    topology.get_shard(mother_id).key_count = 2000
    kv_store = _build_kv_store(mother_id, 2000)
    pre_keys = set(kv_store[mother_id].keys())
    orchestrator.execute_mitose(mother_id, kv_store)
    validator = RedisReshardingValidator(topology)
    report = validator.validate(pre_keys=pre_keys, post_kv_store=kv_store)
    assert report.passed
    assert report.pre_key_count == report.post_key_count == 2000
    assert report.findings == ()


def test_validator_detects_lost_keys(orchestrator, topology):
    snap = topology.snapshot()
    mother_id = snap.shards[0].shard_id
    topology.get_shard(mother_id).key_count = 1000
    kv_store = _build_kv_store(mother_id, 1000)
    pre_keys = set(kv_store[mother_id].keys())
    event = orchestrator.execute_mitose(mother_id, kv_store)
    # Simulate data-loss: drop 5 keys from daughter-a.
    daughter_a_kv = kv_store[event.daughter_a_id]
    drop_keys = list(daughter_a_kv.keys())[:5]
    for k in drop_keys:
        del daughter_a_kv[k]
    validator = RedisReshardingValidator(topology)
    report = validator.validate(pre_keys=pre_keys, post_kv_store=kv_store)
    assert not report.passed
    lost = [f for f in report.findings if f.violation == ConservationViolation.KEY_LOST]
    assert len(lost) == 5


def test_validator_detects_duplicated_keys(orchestrator, topology):
    snap = topology.snapshot()
    mother_id = snap.shards[0].shard_id
    topology.get_shard(mother_id).key_count = 500
    kv_store = _build_kv_store(mother_id, 500)
    pre_keys = set(kv_store[mother_id].keys())
    event = orchestrator.execute_mitose(mother_id, kv_store)
    # Force duplication: copy 3 keys from a -> b.
    a_kv = kv_store[event.daughter_a_id]
    b_kv = kv_store[event.daughter_b_id]
    dup_keys = list(a_kv.keys())[:3]
    for k in dup_keys:
        b_kv[k] = a_kv[k]
    validator = RedisReshardingValidator(topology)
    report = validator.validate(pre_keys=pre_keys, post_kv_store=kv_store)
    duplicated = [
        f for f in report.findings
        if f.violation == ConservationViolation.KEY_DUPLICATED
    ]
    assert len(duplicated) == 3


# ---------- Threading / Race-Condition Tests (3) ----------


def test_concurrent_topology_reads_during_split():
    """50 reader-threads + 1 splitter -- snapshots stay consistent."""
    topo = RedisClusterTopology()
    s = topo.get_shard("shard-genesis")
    s.key_count = 5000
    n_readers = 50
    barrier = threading.Barrier(n_readers + 1)
    inconsistent: list[str] = []

    def reader_thread(idx: int) -> None:
        barrier.wait(timeout=5.0)
        for _ in range(20):
            snap = topo.snapshot()
            # Each snapshot must self-cover [0, TOTAL_SLOTS-1].
            covered_total = sum(
                r.width() for sh in snap.shards for r in sh.slot_ranges
            )
            if covered_total != TOTAL_SLOTS:
                inconsistent.append(
                    f"reader-{idx} saw {covered_total}/{TOTAL_SLOTS} slots"
                )

    def splitter_thread() -> None:
        barrier.wait(timeout=5.0)
        time.sleep(0.001)  # let readers start
        topo.split_shard("shard-genesis", "shard-A", "shard-B")

    threads = [threading.Thread(target=reader_thread, args=(i,)) for i in range(n_readers)]
    threads.append(threading.Thread(target=splitter_thread))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    assert inconsistent == [], f"snapshot-inconsistencies: {inconsistent[:3]}"
    topo.verify_invariants()


def test_concurrent_split_attempts_idempotent_on_duplicate_ids():
    """20 threads attempt split with same daughter-IDs -- exactly 1 wins."""
    topo = RedisClusterTopology()
    topo.get_shard("shard-genesis").key_count = 5000
    n_threads = 20
    barrier = threading.Barrier(n_threads)
    successes: list[bool] = []
    sl = threading.Lock()

    def attempt_split(idx: int) -> None:
        barrier.wait(timeout=5.0)
        try:
            topo.split_shard("shard-genesis", "twin-A", "twin-B")
            with sl:
                successes.append(True)
        except (KeyError, ValueError):
            with sl:
                successes.append(False)

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        futs = [ex.submit(attempt_split, i) for i in range(n_threads)]
        for f in futs:
            f.result(timeout=10.0)
    # Exactly one winner; rest see KeyError (mother gone) or ValueError (collision).
    assert successes.count(True) == 1
    topo.verify_invariants()


def test_concurrent_key_lookups_during_resharding(orchestrator, topology):
    """Lookups continue working during a split (eventually-consistent)."""
    s = topology.get_shard("shard-genesis")
    s.key_count = 2000
    kv_store = _build_kv_store("shard-genesis", 2000)
    test_keys = [f"key-{i:06d}" for i in range(0, 2000, 50)]  # 40 sample keys
    n_threads = 30
    barrier = threading.Barrier(n_threads + 1)
    lookup_results: list[bool] = []
    rl = threading.Lock()

    def lookup_thread(idx: int) -> None:
        barrier.wait(timeout=5.0)
        for k in test_keys:
            sid = topology.find_shard_for_key(k)
            with rl:
                # During mitose, k must always resolve to *some* shard.
                lookup_results.append(sid is not None)

    def splitter_thread() -> None:
        barrier.wait(timeout=5.0)
        time.sleep(0.001)
        orchestrator.execute_mitose("shard-genesis", kv_store)

    threads = [threading.Thread(target=lookup_thread, args=(i,)) for i in range(n_threads)]
    threads.append(threading.Thread(target=splitter_thread))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    # All lookups resolved (no slot-coverage gap).
    assert all(lookup_results), f"some lookups returned None during resharding"
    assert len(lookup_results) == n_threads * len(test_keys)


# ---------- End-to-End / Conservation-Law Test (1) ----------


def test_end_to_end_two_generations_conserve_all_keys(fake_clock):
    """Mother -> 2 daughters -> 4 grand-daughters; every key survives."""
    topo = RedisClusterTopology()
    topo.get_shard("shard-genesis").key_count = 4000
    orch = RedisMitoseOrchestrator(
        topology=topo,
        load_threshold=1000,
        min_keys_per_half=10,
        clock=fake_clock,
    )
    n_keys = 4000
    kv_store = _build_kv_store("shard-genesis", n_keys)
    pre_keys = set(kv_store["shard-genesis"].keys())

    # Generation 1: split genesis.
    ev1 = orch.execute_mitose("shard-genesis", kv_store)
    assert ev1.outcome == MitoseOutcome.DIVIDED

    # Generation 2: each daughter gets ~2000 keys; force them to split too.
    for daughter_id in (ev1.daughter_a_id, ev1.daughter_b_id):
        d = topo.get_shard(daughter_id)
        d.key_count = len(kv_store[daughter_id])  # sync model with reality
        ev = orch.execute_mitose(daughter_id, kv_store)
        assert ev.outcome == MitoseOutcome.DIVIDED, ev.reason

    topo.verify_invariants()
    validator = RedisReshardingValidator(topo)
    report = validator.validate(pre_keys=pre_keys, post_kv_store=kv_store)
    assert report.passed, f"violations: {report.findings[:3]}"
    assert report.post_key_count == n_keys
    assert topo.shard_count() == 4  # 2-generation mitose -> 4 grand-daughters


# CRUX-MK
