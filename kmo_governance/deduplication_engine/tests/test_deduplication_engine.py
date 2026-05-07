# [CRUX-MK]
"""Deduplication-Engine Tests (Welle-20 Phase-13.2)."""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.deduplication_engine import (
    DedupResult,
    DeduplicationEngine,
    EventRecord,
)


def test_init_validation():
    with pytest.raises(ValueError):
        DeduplicationEngine(default_ttl_s=0)
    with pytest.raises(ValueError):
        DeduplicationEngine(default_ttl_s=-1.0)
    with pytest.raises(ValueError):
        DeduplicationEngine(max_entries=0)
    # Valid construction
    engine = DeduplicationEngine(default_ttl_s=10.0, max_entries=5)
    assert engine.default_ttl_s == 10.0
    assert engine.max_entries == 5


def test_first_event_not_duplicate():
    engine = DeduplicationEngine(default_ttl_s=60.0)
    result = engine.check({"event": "X", "id": 1})
    assert isinstance(result, DedupResult)
    assert result.is_duplicate is False
    assert result.original_seen_at is None
    assert result.reason == "first_seen"
    assert result.event_hash  # non-empty


def test_repeated_event_is_duplicate():
    engine = DeduplicationEngine(default_ttl_s=60.0)
    payload = {"event": "X", "id": 1}
    first = engine.check(payload)
    second = engine.check(payload)
    third = engine.check(payload)
    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert second.reason == "duplicate_active"
    assert second.original_seen_at == pytest.approx(first.timestamp, abs=0.5)
    assert third.is_duplicate is True
    assert second.event_hash == first.event_hash == third.event_hash


def test_different_payload_different_hash():
    engine = DeduplicationEngine(default_ttl_s=60.0)
    r1 = engine.check({"a": 1, "b": 2})
    r2 = engine.check({"a": 2, "b": 1})  # Different values
    assert r1.event_hash != r2.event_hash
    assert r1.is_duplicate is False
    assert r2.is_duplicate is False  # different content -> not duplicate


def test_same_payload_dict_order_irrelevant():
    engine = DeduplicationEngine(default_ttl_s=60.0)
    r1 = engine.check({"a": 1, "b": 2})
    r2 = engine.check({"b": 2, "a": 1})  # Same content, different insertion order
    assert r1.event_hash == r2.event_hash
    assert r1.is_duplicate is False
    assert r2.is_duplicate is True


def test_ttl_expiry_allows_re_check():
    engine = DeduplicationEngine(default_ttl_s=0.05)  # 50ms
    payload = {"event": "Y"}
    first = engine.check(payload)
    assert first.is_duplicate is False
    # Wait beyond TTL
    time.sleep(0.08)
    second = engine.check(payload)
    assert second.is_duplicate is False  # expired -> renewed
    assert second.reason == "duplicate_expired_renewed"


def test_custom_ttl_overrides_default():
    engine = DeduplicationEngine(default_ttl_s=3600.0)
    payload = {"event": "Z"}
    first = engine.check(payload, ttl_s=0.05)
    assert first.is_duplicate is False
    assert first.ttl_remaining_s == pytest.approx(0.05, abs=0.01)
    time.sleep(0.08)
    second = engine.check(payload, ttl_s=0.05)
    assert second.is_duplicate is False
    assert second.reason == "duplicate_expired_renewed"
    # Invalid ttl_s
    with pytest.raises(ValueError):
        engine.check(payload, ttl_s=0)
    with pytest.raises(ValueError):
        engine.check(payload, ttl_s=-1.0)


def test_force_expire_removes_record():
    engine = DeduplicationEngine(default_ttl_s=3600.0)
    payload = {"event": "force-test"}
    first = engine.check(payload)
    assert first.is_duplicate is False
    # Verify record exists by re-check (would be duplicate)
    repeat = engine.check(payload)
    assert repeat.is_duplicate is True
    # Force expire
    removed = engine.force_expire(first.event_hash)
    assert removed is True
    # Now re-check should be first_seen again
    after = engine.check(payload)
    assert after.is_duplicate is False
    assert after.reason == "first_seen"
    # force_expire on non-existent
    not_removed = engine.force_expire("nonexistent-hash")
    assert not_removed is False
    # empty hash raises
    with pytest.raises(ValueError):
        engine.force_expire("")


def test_cleanup_expired_purges_old():
    engine = DeduplicationEngine(default_ttl_s=0.05)  # 50ms
    engine.check({"a": 1})
    engine.check({"b": 2})
    engine.check({"c": 3})
    assert len(engine.list_active()) == 3
    time.sleep(0.08)
    purged = engine.cleanup_expired()
    assert purged == 3
    assert len(engine.list_active()) == 0
    # Calling again on empty store
    purged_again = engine.cleanup_expired()
    assert purged_again == 0


def test_lru_eviction_when_max_entries():
    engine = DeduplicationEngine(default_ttl_s=3600.0, max_entries=3)
    r1 = engine.check({"id": 1})
    time.sleep(0.001)  # ensure distinct first_seen_at
    r2 = engine.check({"id": 2})
    time.sleep(0.001)
    r3 = engine.check({"id": 3})
    assert engine.get_stats()["active_entries"] == 3
    # Insert 4th -> evicts eldest (id=1)
    time.sleep(0.001)
    r4 = engine.check({"id": 4})
    stats = engine.get_stats()
    assert stats["active_entries"] == 3
    assert stats["evictions"] == 1
    # The eldest (id=1) should now be missing -> re-check is first_seen again
    r1_again = engine.check({"id": 1})
    assert r1_again.is_duplicate is False
    assert r1_again.reason == "first_seen"
    # Eviction count incremented again
    assert engine.get_stats()["evictions"] == 2


def test_hit_count_increments_on_duplicate():
    engine = DeduplicationEngine(default_ttl_s=3600.0)
    payload = {"event": "hit-count"}
    engine.check(payload)
    engine.check(payload)
    engine.check(payload)
    engine.check(payload)
    actives = engine.list_active()
    assert len(actives) == 1
    record = actives[0]
    assert isinstance(record, EventRecord)
    # 1 first_seen + 3 hits = hit_count 3
    assert record.hit_count == 3


def test_get_stats_correct():
    engine = DeduplicationEngine(default_ttl_s=3600.0, max_entries=10)
    engine.check({"a": 1})  # miss
    engine.check({"a": 1})  # hit
    engine.check({"b": 2})  # miss
    engine.check({"a": 1})  # hit
    stats = engine.get_stats()
    assert stats["misses"] == 2
    assert stats["hits"] == 2
    assert stats["total_checks"] == 4
    assert stats["active_entries"] == 2
    assert stats["max_entries"] == 10
    assert stats["default_ttl_s"] == 3600.0
    assert stats["expired_purges"] == 0
    assert stats["evictions"] == 0


def test_concurrent_50_threads_idempotent():
    engine = DeduplicationEngine(default_ttl_s=3600.0)
    payload = {"event": "concurrent-X", "id": 42}
    results: list[DedupResult] = []
    results_lock = threading.Lock()

    def worker() -> None:
        r = engine.check(payload)
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 50
    not_dup_count = sum(1 for r in results if not r.is_duplicate)
    dup_count = sum(1 for r in results if r.is_duplicate)
    assert not_dup_count == 1, (
        f"Exactly 1 thread must see first_seen, got {not_dup_count}"
    )
    assert dup_count == 49
    # All hashes identical
    hashes = {r.event_hash for r in results}
    assert len(hashes) == 1
    # Engine state correct
    stats = engine.get_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 49
    assert stats["active_entries"] == 1


def test_custom_hash_fn():
    captured: list[object] = []

    def upper_hash(payload: object) -> str:
        captured.append(payload)
        return str(payload).upper()

    engine = DeduplicationEngine(default_ttl_s=3600.0, hash_fn=upper_hash)
    r1 = engine.check("hello")
    r2 = engine.check("hello")
    assert r1.event_hash == "HELLO"
    assert r2.event_hash == "HELLO"
    assert r1.is_duplicate is False
    assert r2.is_duplicate is True
    assert len(captured) == 2

    # hash_fn that returns invalid value
    def bad_hash(_payload: object) -> str:
        return ""

    bad_engine = DeduplicationEngine(default_ttl_s=60.0, hash_fn=bad_hash)
    with pytest.raises(ValueError):
        bad_engine.check({"x": 1})


def test_result_frozen_immutability():
    engine = DeduplicationEngine(default_ttl_s=60.0)
    r = engine.check({"a": 1})
    with pytest.raises(Exception):
        r.is_duplicate = True  # type: ignore[misc]
    with pytest.raises(Exception):
        r.event_hash = "modified"  # type: ignore[misc]
    # EventRecord too
    rec = engine.list_active()[0]
    with pytest.raises(Exception):
        rec.hit_count = 999  # type: ignore[misc]


def test_dedup_result_validation():
    # Empty hash forbidden
    with pytest.raises(ValueError):
        DedupResult(
            is_duplicate=False,
            event_hash="",
            original_seen_at=None,
            ttl_remaining_s=0.0,
            reason="x",
            timestamp=1.0,
        )
    # Negative ttl_remaining_s forbidden
    with pytest.raises(ValueError):
        DedupResult(
            is_duplicate=False,
            event_hash="abc",
            original_seen_at=None,
            ttl_remaining_s=-1.0,
            reason="x",
            timestamp=1.0,
        )


def test_event_record_validation():
    with pytest.raises(ValueError):
        EventRecord(event_hash="", first_seen_at=1.0, hit_count=0, ttl_s=10.0)
    with pytest.raises(ValueError):
        EventRecord(event_hash="abc", first_seen_at=0.0, hit_count=0, ttl_s=10.0)
    with pytest.raises(ValueError):
        EventRecord(event_hash="abc", first_seen_at=1.0, hit_count=0, ttl_s=0.0)
    with pytest.raises(ValueError):
        EventRecord(event_hash="abc", first_seen_at=1.0, hit_count=-1, ttl_s=10.0)
    # Valid
    rec = EventRecord(event_hash="abc", first_seen_at=100.0, hit_count=5, ttl_s=60.0)
    assert rec.is_expired(now=200.0) is True
    assert rec.is_expired(now=130.0) is False
    assert rec.remaining_s(now=130.0) == pytest.approx(30.0, abs=0.001)
    assert rec.remaining_s(now=200.0) == 0.0


# --- W20-P2: True-LRU Eviction Tests (Welle-20 Patch-1) ---


def test_lru_eviction_uses_last_access_not_first_seen():
    """True-LRU by last_access_at (NOT FIFO by first_seen_at).

    W20-P2 (Cross-LLM-V10 Codex): hot records survive eviction.
    Hot record (id=1, accessed 5 times, latest access very recent) must NOT be
    evicted when a new record arrives, even though its first_seen_at is oldest.
    """
    engine = DeduplicationEngine(default_ttl_s=3600.0, max_entries=3)
    # Create 3 records, id=1 has earliest first_seen_at
    engine.check({"id": 1})
    time.sleep(0.001)
    engine.check({"id": 2})
    time.sleep(0.001)
    engine.check({"id": 3})
    # Access id=1 multiple times -> last_access_at becomes recent
    time.sleep(0.001)
    engine.check({"id": 1})
    time.sleep(0.001)
    engine.check({"id": 1})
    time.sleep(0.001)
    # Now id=2 has the OLDEST last_access_at (was only touched at first_seen)
    # Insert id=4 -> should evict id=2 (LRU), NOT id=1 (despite older first_seen_at)
    engine.check({"id": 4})
    stats = engine.get_stats()
    assert stats["active_entries"] == 3
    assert stats["evictions"] == 1
    # id=1 must STILL be present (re-check is duplicate)
    r1_again = engine.check({"id": 1})
    assert r1_again.is_duplicate is True, (
        "id=1 was hot (4 hits) and must survive LRU eviction"
    )
    # id=2 must be gone (re-check is first_seen)
    r2_again = engine.check({"id": 2})
    assert r2_again.is_duplicate is False
    assert r2_again.reason == "first_seen", (
        "id=2 had oldest last_access_at and must be evicted"
    )


def test_repeated_access_protects_from_eviction():
    """Hot records (event A 100x checks) survive eviction over cold records (event B 1x).

    Eviction-1 (max_entries=2 then add 3rd) must remove B, not A.
    """
    engine = DeduplicationEngine(default_ttl_s=3600.0, max_entries=2)
    # event A: 100 checks -> last_access_at very recent
    for _ in range(100):
        engine.check({"event": "A"})
    # event B: 1 check older
    time.sleep(0.001)
    engine.check({"event": "B"})
    # event A again -> bump last_access_at on A so B is now LRU
    time.sleep(0.001)
    engine.check({"event": "A"})
    # Now insert C -> max_entries=2, must evict B (LRU)
    time.sleep(0.001)
    engine.check({"event": "C"})
    assert engine.get_stats()["evictions"] == 1
    # A must still be present
    r_a = engine.check({"event": "A"})
    assert r_a.is_duplicate is True, "Hot event A must survive"
    # B must be gone
    r_b = engine.check({"event": "B"})
    assert r_b.is_duplicate is False, "Cold event B must be evicted"


def test_last_access_at_updated_on_hit():
    """Each hit on a duplicate updates last_access_at. RLock-protected."""
    engine = DeduplicationEngine(default_ttl_s=3600.0)
    payload = {"event": "access-update"}
    engine.check(payload)
    rec_before = engine.list_active()[0]
    initial_access = rec_before.last_access_at
    initial_first_seen = rec_before.first_seen_at
    # Wait + hit again
    time.sleep(0.01)
    engine.check(payload)
    rec_after = engine.list_active()[0]
    # last_access_at must have advanced
    assert rec_after.last_access_at > initial_access, (
        "last_access_at must be updated on hit"
    )
    # first_seen_at must remain unchanged
    assert rec_after.first_seen_at == initial_first_seen, (
        "first_seen_at must NOT change on hit"
    )
    # hit_count must have incremented
    assert rec_after.hit_count == 1


def test_lru_with_force_expire():
    """force_expire entfernt unabhaengig von last_access_at.

    Even a hot record (recently accessed) is removed by force_expire.
    """
    engine = DeduplicationEngine(default_ttl_s=3600.0, max_entries=10)
    # Hot record
    payload = {"event": "force-lru-test"}
    for _ in range(10):
        engine.check(payload)
    rec = engine.list_active()[0]
    assert rec.hit_count == 9
    # force_expire must remove it regardless of last_access_at
    removed = engine.force_expire(rec.event_hash)
    assert removed is True
    # Now re-check is first_seen
    after = engine.check(payload)
    assert after.is_duplicate is False
    assert after.reason == "first_seen"


def test_event_record_last_access_at_default_to_first_seen():
    """Backward-compat: EventRecord without last_access_at gets first_seen_at default."""
    rec = EventRecord(event_hash="abc", first_seen_at=100.0, hit_count=0, ttl_s=60.0)
    assert rec.last_access_at == 100.0


def test_event_record_last_access_at_validation():
    """last_access_at < first_seen_at is rejected."""
    with pytest.raises(ValueError):
        EventRecord(
            event_hash="abc",
            first_seen_at=100.0,
            hit_count=0,
            ttl_s=60.0,
            last_access_at=50.0,  # < first_seen_at
        )
    # Equal is OK
    rec = EventRecord(
        event_hash="abc",
        first_seen_at=100.0,
        hit_count=0,
        ttl_s=60.0,
        last_access_at=100.0,
    )
    assert rec.last_access_at == 100.0
    # Greater is OK
    rec2 = EventRecord(
        event_hash="abc",
        first_seen_at=100.0,
        hit_count=0,
        ttl_s=60.0,
        last_access_at=150.0,
    )
    assert rec2.last_access_at == 150.0
