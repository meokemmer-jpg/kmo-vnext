# [CRUX-MK]
"""Tests fuer KPM-Deduplication-Engine.

Welle-26 Phase-19 Round-2 KMO-vNext, Bio-Pattern-Lift 5/5.

Testet: TTL-Lifecycle, True-LRU (last_access), Concurrency, Strategy-
Indexing, Custom-Hash, Frozen-Invarianten.

CRUX-MK
"""
from __future__ import annotations

import threading
import time

import pytest

from kpm_deduplication_engine.kpm_deduplication_engine import (
    KPMDeduplicationEngine,
    OrderRecord,
    TradeDedupResult,
)


# ---------------------------------------------------------------------------
# Init / Validation
# ---------------------------------------------------------------------------


def test_init_validation():
    # Valid construction.
    eng = KPMDeduplicationEngine()
    assert eng.default_ttl_s == 300.0
    assert eng.max_entries == 100_000

    eng2 = KPMDeduplicationEngine(default_ttl_s=60.0, max_entries=500)
    assert eng2.default_ttl_s == 60.0
    assert eng2.max_entries == 500

    # Invalid: ttl <= 0
    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        KPMDeduplicationEngine(default_ttl_s=0)
    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        KPMDeduplicationEngine(default_ttl_s=-1.0)

    # Invalid: max_entries < 1
    with pytest.raises(ValueError, match="max_entries must be >= 1"):
        KPMDeduplicationEngine(max_entries=0)


# ---------------------------------------------------------------------------
# Core Dedup Behavior
# ---------------------------------------------------------------------------


def test_first_order_not_duplicate():
    eng = KPMDeduplicationEngine()
    payload = {"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 150.0}
    res = eng.check(
        client_order_id="ORD-001",
        order_payload=payload,
        strategy_id="momentum-v1",
    )
    assert res.is_duplicate is False
    assert res.client_order_id == "ORD-001"
    assert res.order_hash  # non-empty SHA256
    assert res.original_seen_at is None
    assert res.reason == "first_seen"
    assert res.ttl_remaining_s == 300.0

    stats = eng.get_stats()
    assert stats["active_entries"] == 1
    assert stats["misses"] == 1
    assert stats["hits"] == 0


def test_repeated_order_is_duplicate():
    eng = KPMDeduplicationEngine()
    payload = {"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 150.0}
    res1 = eng.check(
        client_order_id="ORD-001",
        order_payload=payload,
        strategy_id="momentum-v1",
    )
    res2 = eng.check(
        client_order_id="ORD-001",
        order_payload=payload,
        strategy_id="momentum-v1",
    )
    assert res1.is_duplicate is False
    assert res2.is_duplicate is True
    assert res2.original_seen_at == res1.timestamp or \
        res2.original_seen_at <= res2.timestamp
    assert res2.reason == "duplicate_active"
    assert res2.ttl_remaining_s > 0
    assert res2.ttl_remaining_s <= 300.0

    stats = eng.get_stats()
    assert stats["active_entries"] == 1
    assert stats["misses"] == 1
    assert stats["hits"] == 1


def test_different_payload_same_client_order_id_still_duplicate():
    """Domain-Note: client_order_id ist primary key. Wenn dieselbe
    client_order_id mit divergentem payload-Hash erscheint, ist das ein
    Strategy-Bug-Signal — aber Dedup-Engine markiert dennoch als duplicate
    (Idempotency-Garantie). Audit-Trail bewahrt ORIGINALEN order_hash auf.
    """
    eng = KPMDeduplicationEngine()
    payload1 = {"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 150.0}
    payload2 = {"symbol": "AAPL", "side": "BUY", "qty": 200, "price": 151.0}

    res1 = eng.check(
        client_order_id="ORD-001",
        order_payload=payload1,
        strategy_id="momentum-v1",
    )
    res2 = eng.check(
        client_order_id="ORD-001",
        order_payload=payload2,
        strategy_id="momentum-v1",
    )
    assert res1.is_duplicate is False
    # Same client_order_id → still duplicate (Idempotency-Pflicht)
    assert res2.is_duplicate is True
    # Audit-Trail: original order_hash bleibt erhalten
    assert res2.order_hash == res1.order_hash
    # Aber payload2 Hash != payload1 Hash → Caller kann via _default_hash
    # eigenes Bug-Detection-Signal ableiten.


def test_ttl_expiry_allows_re_check():
    eng = KPMDeduplicationEngine(default_ttl_s=0.1)  # 100ms TTL
    payload = {"symbol": "MSFT", "side": "SELL", "qty": 50}
    res1 = eng.check(
        client_order_id="ORD-002",
        order_payload=payload,
        strategy_id="mean-rev",
    )
    assert res1.is_duplicate is False

    time.sleep(0.15)  # Warte > TTL

    res2 = eng.check(
        client_order_id="ORD-002",
        order_payload=payload,
        strategy_id="mean-rev",
    )
    assert res2.is_duplicate is False
    assert res2.reason == "duplicate_expired_renewed"

    stats = eng.get_stats()
    assert stats["expired_purges"] == 1
    assert stats["misses"] == 2


def test_custom_ttl_overrides_default():
    eng = KPMDeduplicationEngine(default_ttl_s=300.0)
    payload = {"symbol": "GOOG", "side": "BUY", "qty": 10}

    res = eng.check(
        client_order_id="ORD-003",
        order_payload=payload,
        strategy_id="alpha",
        ttl_s=60.0,
    )
    assert res.is_duplicate is False
    assert res.ttl_remaining_s == 60.0

    # ttl_s <= 0 muss raisen
    with pytest.raises(ValueError, match="ttl_s must be > 0 when provided"):
        eng.check(
            client_order_id="ORD-X",
            order_payload=payload,
            strategy_id="alpha",
            ttl_s=0,
        )


# ---------------------------------------------------------------------------
# Manual Expire / Cleanup
# ---------------------------------------------------------------------------


def test_force_expire_removes():
    eng = KPMDeduplicationEngine()
    payload = {"symbol": "TSLA", "qty": 5}
    eng.check(
        client_order_id="ORD-CANCEL",
        order_payload=payload,
        strategy_id="strat-x",
    )
    assert eng.get_stats()["active_entries"] == 1

    removed = eng.force_expire("ORD-CANCEL")
    assert removed is True
    assert eng.get_stats()["active_entries"] == 0

    # Erneuter Aufruf: nicht mehr da → False
    removed_again = eng.force_expire("ORD-CANCEL")
    assert removed_again is False

    # Empty client_order_id → ValueError
    with pytest.raises(ValueError, match="client_order_id required"):
        eng.force_expire("")


def test_cleanup_expired_purges():
    eng = KPMDeduplicationEngine(default_ttl_s=0.05)  # 50ms
    for i in range(5):
        eng.check(
            client_order_id=f"ORD-{i}",
            order_payload={"symbol": "X", "i": i},
            strategy_id="bulk",
        )

    assert eng.get_stats()["active_entries"] == 5

    time.sleep(0.1)
    purged = eng.cleanup_expired()
    assert purged == 5
    assert eng.get_stats()["active_entries"] == 0


# ---------------------------------------------------------------------------
# True-LRU Eviction (W20-P2 Baseline)
# ---------------------------------------------------------------------------


def test_lru_eviction_uses_last_access():
    """Hot-Order (recently accessed via retry) muss vor idle-Order survive.

    Setup: max_entries=2. Order A first_seen, Order B first_seen,
           Order A wird re-checked (Hit → last_access updated),
           Order C first_seen → muss B evict (NICHT A).

    Test der True-LRU-by-last_access (NICHT FIFO-by-first_seen).
    """
    eng = KPMDeduplicationEngine(default_ttl_s=300.0, max_entries=2)

    eng.check(
        client_order_id="A",
        order_payload={"x": 1},
        strategy_id="s",
    )
    time.sleep(0.01)
    eng.check(
        client_order_id="B",
        order_payload={"x": 2},
        strategy_id="s",
    )
    time.sleep(0.01)
    # Hit auf A → A.last_access updated zu now
    res_a = eng.check(
        client_order_id="A",
        order_payload={"x": 1},
        strategy_id="s",
    )
    assert res_a.is_duplicate is True
    time.sleep(0.01)
    # C einfuegen → muss B evicten (B ist eldest by last_access)
    eng.check(
        client_order_id="C",
        order_payload={"x": 3},
        strategy_id="s",
    )

    stats = eng.get_stats()
    assert stats["active_entries"] == 2
    assert stats["evictions"] == 1

    active_ids = {r.client_order_id for r in eng.list_active()}
    assert "A" in active_ids  # Hot, geschuetzt
    assert "C" in active_ids  # Neu
    assert "B" not in active_ids  # Idle, evicted


# ---------------------------------------------------------------------------
# Strategy-Indexing
# ---------------------------------------------------------------------------


def test_query_by_strategy_id():
    eng = KPMDeduplicationEngine()
    eng.check(
        client_order_id="ORD-A1",
        order_payload={"sym": "AAA"},
        strategy_id="alpha",
    )
    eng.check(
        client_order_id="ORD-B1",
        order_payload={"sym": "BBB"},
        strategy_id="beta",
    )
    eng.check(
        client_order_id="ORD-A2",
        order_payload={"sym": "AAA"},
        strategy_id="alpha",
    )

    alpha_orders = eng.query_by_strategy("alpha")
    beta_orders = eng.query_by_strategy("beta")

    assert isinstance(alpha_orders, tuple)
    assert isinstance(beta_orders, tuple)
    assert len(alpha_orders) == 2
    assert len(beta_orders) == 1
    assert {r.client_order_id for r in alpha_orders} == {"ORD-A1", "ORD-A2"}
    assert beta_orders[0].client_order_id == "ORD-B1"

    # Empty strategy_id → ValueError
    with pytest.raises(ValueError, match="strategy_id required"):
        eng.query_by_strategy("")


# ---------------------------------------------------------------------------
# Hit-Count + Stats
# ---------------------------------------------------------------------------


def test_hit_count_increments():
    eng = KPMDeduplicationEngine()
    payload = {"symbol": "NVDA", "qty": 10}

    eng.check(
        client_order_id="ORD-HC",
        order_payload=payload,
        strategy_id="s",
    )
    eng.check(
        client_order_id="ORD-HC",
        order_payload=payload,
        strategy_id="s",
    )
    eng.check(
        client_order_id="ORD-HC",
        order_payload=payload,
        strategy_id="s",
    )

    active = eng.list_active()
    assert len(active) == 1
    assert active[0].client_order_id == "ORD-HC"
    assert active[0].hit_count == 2  # 1 first_seen + 2 hits


def test_get_stats_correct():
    eng = KPMDeduplicationEngine(default_ttl_s=300.0, max_entries=1000)
    eng.check(
        client_order_id="X",
        order_payload={"a": 1},
        strategy_id="s",
    )
    eng.check(
        client_order_id="X",
        order_payload={"a": 1},
        strategy_id="s",
    )
    eng.check(
        client_order_id="Y",
        order_payload={"b": 2},
        strategy_id="s",
    )

    stats = eng.get_stats()
    assert stats["active_entries"] == 2
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["total_checks"] == 3
    assert stats["expired_purges"] == 0
    assert stats["evictions"] == 0
    assert stats["max_entries"] == 1000
    assert stats["default_ttl_s"] == 300.0


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_50_threads_idempotent():
    """50 Threads checken gleiche client_order_id → genau 1 first_seen,
    49 duplicate. Idempotenz unter Race-Condition.
    """
    eng = KPMDeduplicationEngine()
    payload = {"symbol": "RACE", "qty": 100}
    results: list[TradeDedupResult] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(50)

    def worker():
        barrier.wait()  # Sync alle Threads
        res = eng.check(
            client_order_id="ORD-RACE",
            order_payload=payload,
            strategy_id="s",
        )
        with results_lock:
            results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 50
    first_seen = [r for r in results if not r.is_duplicate]
    duplicates = [r for r in results if r.is_duplicate]

    assert len(first_seen) == 1
    assert len(duplicates) == 49

    stats = eng.get_stats()
    assert stats["active_entries"] == 1
    assert stats["misses"] == 1
    assert stats["hits"] == 49


# ---------------------------------------------------------------------------
# Custom Hash
# ---------------------------------------------------------------------------


def test_custom_hash_fn():
    """Eigene hash_fn kann genutzt werden (z.B. broker-spezifischer Hash)."""

    def my_hash(payload):
        return f"custom-{payload.get('symbol', 'NONE')}"

    eng = KPMDeduplicationEngine(hash_fn=my_hash)
    res = eng.check(
        client_order_id="ORD-H",
        order_payload={"symbol": "AAPL"},
        strategy_id="s",
    )
    assert res.order_hash == "custom-AAPL"

    # Bad hash_fn (returns non-str) muss raisen
    eng2 = KPMDeduplicationEngine(hash_fn=lambda p: 42)
    with pytest.raises(ValueError, match="hash_fn must return non-empty str"):
        eng2.check(
            client_order_id="ORD-X",
            order_payload={"a": 1},
            strategy_id="s",
        )

    # Bad hash_fn (returns empty str) muss raisen
    eng3 = KPMDeduplicationEngine(hash_fn=lambda p: "")
    with pytest.raises(ValueError, match="hash_fn must return non-empty str"):
        eng3.check(
            client_order_id="ORD-Y",
            order_payload={"a": 1},
            strategy_id="s",
        )


# ---------------------------------------------------------------------------
# Frozen Invarianten
# ---------------------------------------------------------------------------


def test_result_frozen():
    eng = KPMDeduplicationEngine()
    res = eng.check(
        client_order_id="ORD-F",
        order_payload={"a": 1},
        strategy_id="s",
    )
    assert isinstance(res, TradeDedupResult)
    with pytest.raises((AttributeError, Exception)):
        res.is_duplicate = True  # frozen → muss raisen

    # Validierung im __post_init__
    with pytest.raises(ValueError, match="client_order_id required"):
        TradeDedupResult(
            is_duplicate=False,
            client_order_id="",
            order_hash="abc",
            original_seen_at=None,
            ttl_remaining_s=10.0,
            reason="x",
            timestamp=time.time(),
        )
    with pytest.raises(ValueError, match="order_hash required"):
        TradeDedupResult(
            is_duplicate=False,
            client_order_id="X",
            order_hash="",
            original_seen_at=None,
            ttl_remaining_s=10.0,
            reason="x",
            timestamp=time.time(),
        )
    with pytest.raises(ValueError, match="ttl_remaining_s must be >= 0"):
        TradeDedupResult(
            is_duplicate=False,
            client_order_id="X",
            order_hash="abc",
            original_seen_at=None,
            ttl_remaining_s=-1.0,
            reason="x",
            timestamp=time.time(),
        )


def test_record_frozen():
    rec = OrderRecord(
        client_order_id="X",
        order_hash="abc",
        first_seen_at=100.0,
        hit_count=0,
        ttl_s=300.0,
        strategy_id="s",
    )
    assert rec.client_order_id == "X"
    assert rec.last_access_at == rec.first_seen_at  # default

    with pytest.raises((AttributeError, Exception)):
        rec.hit_count = 5  # frozen → muss raisen

    # Validierung
    with pytest.raises(ValueError, match="client_order_id required"):
        OrderRecord(
            client_order_id="",
            order_hash="abc",
            first_seen_at=100.0,
            hit_count=0,
            ttl_s=300.0,
            strategy_id="s",
        )
    with pytest.raises(ValueError, match="order_hash required"):
        OrderRecord(
            client_order_id="X",
            order_hash="",
            first_seen_at=100.0,
            hit_count=0,
            ttl_s=300.0,
            strategy_id="s",
        )
    with pytest.raises(ValueError, match="strategy_id required"):
        OrderRecord(
            client_order_id="X",
            order_hash="abc",
            first_seen_at=100.0,
            hit_count=0,
            ttl_s=300.0,
            strategy_id="",
        )
    with pytest.raises(ValueError, match="first_seen_at must be > 0"):
        OrderRecord(
            client_order_id="X",
            order_hash="abc",
            first_seen_at=0,
            hit_count=0,
            ttl_s=300.0,
            strategy_id="s",
        )
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        OrderRecord(
            client_order_id="X",
            order_hash="abc",
            first_seen_at=100.0,
            hit_count=0,
            ttl_s=0,
            strategy_id="s",
        )
    with pytest.raises(ValueError, match="hit_count must be >= 0"):
        OrderRecord(
            client_order_id="X",
            order_hash="abc",
            first_seen_at=100.0,
            hit_count=-1,
            ttl_s=300.0,
            strategy_id="s",
        )
    with pytest.raises(ValueError, match="last_access_at must be >="):
        OrderRecord(
            client_order_id="X",
            order_hash="abc",
            first_seen_at=100.0,
            hit_count=0,
            ttl_s=300.0,
            strategy_id="s",
            last_access_at=50.0,  # < first_seen_at
        )


# ---------------------------------------------------------------------------
# Pflicht-Feld Validation in check()
# ---------------------------------------------------------------------------


def test_check_requires_client_order_id_and_strategy_id():
    eng = KPMDeduplicationEngine()
    with pytest.raises(ValueError, match="client_order_id required"):
        eng.check(
            client_order_id="",
            order_payload={"a": 1},
            strategy_id="s",
        )
    with pytest.raises(ValueError, match="strategy_id required"):
        eng.check(
            client_order_id="X",
            order_payload={"a": 1},
            strategy_id="",
        )


# CRUX-MK
