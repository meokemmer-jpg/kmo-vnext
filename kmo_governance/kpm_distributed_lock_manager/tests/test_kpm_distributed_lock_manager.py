# [CRUX-MK]
"""Tests for KPM-Distributed-Trade-Lock-Manager [CRUX-MK].

Welle-26 Phase-19 Test-Suite. 17 Tests inkl.:
- Init-Validation
- Acquire / Renew / Release / Force-Release
- Token-Validation (invalid token rejected)
- Auto-Release expired Leases
- Sweep-Reaper
- LONG-vs-SHORT-Independence (gleichem Instrument)
- Concurrent-Access (50 threads, only one acquires)
- Frozen-Immutability (TradeLease + TradeLockResult)
- State-Transitions (FREE / ACQUIRED / EXPIRED)
"""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from kmo_governance.kpm_distributed_lock_manager import (
    KPMDistributedTradeLockManager,
    PositionSide,
    TradeLease,
    TradeLockResult,
    TradeLockState,
)


# ---------------------------------------------------------------------------
# Init-Validation
# ---------------------------------------------------------------------------


def test_init_validation() -> None:
    # Default works
    KPMDistributedTradeLockManager()
    KPMDistributedTradeLockManager(default_ttl_s=10.0, sweep_interval_s=1.0)

    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        KPMDistributedTradeLockManager(default_ttl_s=0)
    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        KPMDistributedTradeLockManager(default_ttl_s=-1.0)
    with pytest.raises(ValueError, match="sweep_interval_s must be > 0"):
        KPMDistributedTradeLockManager(sweep_interval_s=0)
    with pytest.raises(ValueError, match="sweep_interval_s must be > 0"):
        KPMDistributedTradeLockManager(sweep_interval_s=-0.5)


# ---------------------------------------------------------------------------
# Acquire
# ---------------------------------------------------------------------------


def test_acquire_free_lock_long() -> None:
    mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)
    result = mgr.acquire("BTCUSDT", PositionSide.LONG, "kelly-0.4-strat")
    assert result.success is True
    assert result.instrument_id == "BTCUSDT"
    assert result.position_side == PositionSide.LONG
    assert result.lease is not None
    assert result.lease.holder_strategy_id == "kelly-0.4-strat"
    assert result.lease.instrument_id == "BTCUSDT"
    assert result.lease.position_side == PositionSide.LONG
    assert result.lease.lease_token  # non-empty
    assert result.conflict_holder is None
    assert result.reason == "acquired"


def test_acquire_held_returns_conflict() -> None:
    mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)
    r1 = mgr.acquire("ETHUSDT", PositionSide.LONG, "strat-A")
    assert r1.success is True

    r2 = mgr.acquire("ETHUSDT", PositionSide.LONG, "strat-B")
    assert r2.success is False
    assert r2.lease is None
    assert r2.conflict_holder == "strat-A"
    assert "held by strat-A" in r2.reason


def test_acquire_expired_auto_release() -> None:
    mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)
    # Sehr kurze TTL, dann sleep, dann reacquire
    r1 = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-X", ttl_s=0.05)
    assert r1.success is True
    time.sleep(0.1)

    r2 = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-Y")
    assert r2.success is True
    assert r2.lease is not None
    assert r2.lease.holder_strategy_id == "strat-Y"
    assert r2.lease.lease_token != r1.lease.lease_token


def test_acquire_validates_inputs() -> None:
    mgr = KPMDistributedTradeLockManager()
    with pytest.raises(ValueError, match="instrument_id must be non-empty"):
        mgr.acquire("", PositionSide.LONG, "strat-A")
    with pytest.raises(ValueError, match="position_side must be a PositionSide enum"):
        mgr.acquire("BTCUSDT", "long", "strat-A")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="holder_strategy_id must be non-empty"):
        mgr.acquire("BTCUSDT", PositionSide.LONG, "")
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A", ttl_s=0)
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A", ttl_s=-1.0)


# ---------------------------------------------------------------------------
# Renew
# ---------------------------------------------------------------------------


def test_renew_extends() -> None:
    mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)
    r1 = mgr.acquire("BTCUSDT", PositionSide.SHORT, "strat-A", ttl_s=2.0)
    assert r1.success is True
    original_expires = r1.lease.expires_at

    time.sleep(0.05)
    r2 = mgr.renew(
        "BTCUSDT", PositionSide.SHORT, r1.lease.lease_token, additional_ttl_s=10.0
    )
    assert r2.success is True
    assert r2.lease is not None
    assert r2.lease.expires_at > original_expires
    # Renew preserves token
    assert r2.lease.lease_token == r1.lease.lease_token
    # Renew preserves acquired_at
    assert r2.lease.acquired_at == r1.lease.acquired_at


def test_renew_invalid_token() -> None:
    mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)
    r1 = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A")
    assert r1.success is True

    r2 = mgr.renew("BTCUSDT", PositionSide.LONG, "invalid-token-xyz")
    assert r2.success is False
    assert r2.reason == "invalid lease_token"
    assert r2.conflict_holder == "strat-A"


# ---------------------------------------------------------------------------
# Release / Force-Release
# ---------------------------------------------------------------------------


def test_release_valid_token() -> None:
    mgr = KPMDistributedTradeLockManager()
    r1 = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A")
    assert r1.success is True

    r2 = mgr.release("BTCUSDT", PositionSide.LONG, r1.lease.lease_token)
    assert r2.success is True
    assert r2.reason == "released"

    # After release, instrument is FREE
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is False
    assert mgr.get_state("BTCUSDT", PositionSide.LONG) == TradeLockState.FREE


def test_release_invalid_token() -> None:
    mgr = KPMDistributedTradeLockManager()
    r1 = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A")
    assert r1.success is True

    r2 = mgr.release("BTCUSDT", PositionSide.LONG, "wrong-token-zzz")
    assert r2.success is False
    assert r2.reason == "invalid lease_token"
    assert r2.conflict_holder == "strat-A"
    # Lock still held
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is True


def test_force_release() -> None:
    mgr = KPMDistributedTradeLockManager()
    r1 = mgr.acquire("ETHUSDT", PositionSide.SHORT, "stuck-strat")
    assert r1.success is True

    r2 = mgr.force_release("ETHUSDT", PositionSide.SHORT)
    assert r2.success is True
    assert "force-released" in r2.reason
    assert "stuck-strat" in r2.reason
    assert mgr.is_held("ETHUSDT", PositionSide.SHORT) is False

    # Force-release on absent lock returns success=False
    r3 = mgr.force_release("ETHUSDT", PositionSide.SHORT)
    assert r3.success is False
    assert r3.reason == "lock not found"


# ---------------------------------------------------------------------------
# LONG-vs-SHORT-Independence (Trading-Domain-spezifisch)
# ---------------------------------------------------------------------------


def test_long_and_short_independent() -> None:
    """LONG und SHORT auf gleichem Instrument sind separate Locks (separate Synapsen)."""
    mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)

    r_long = mgr.acquire("BTCUSDT", PositionSide.LONG, "long-strat")
    assert r_long.success is True

    # Different side -> different lock, no conflict
    r_short = mgr.acquire("BTCUSDT", PositionSide.SHORT, "short-strat")
    assert r_short.success is True
    assert r_short.lease.lease_token != r_long.lease.lease_token

    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is True
    assert mgr.is_held("BTCUSDT", PositionSide.SHORT) is True

    # Releasing LONG does not affect SHORT
    mgr.release("BTCUSDT", PositionSide.LONG, r_long.lease.lease_token)
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is False
    assert mgr.is_held("BTCUSDT", PositionSide.SHORT) is True


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def test_is_held() -> None:
    mgr = KPMDistributedTradeLockManager()
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is False
    r = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A")
    assert r.success is True
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is True
    # Empty instrument_id -> False
    assert mgr.is_held("", PositionSide.LONG) is False


def test_get_state() -> None:
    mgr = KPMDistributedTradeLockManager()
    assert mgr.get_state("BTCUSDT", PositionSide.LONG) == TradeLockState.FREE

    r = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A", ttl_s=0.05)
    assert r.success is True
    assert mgr.get_state("BTCUSDT", PositionSide.LONG) == TradeLockState.ACQUIRED

    time.sleep(0.1)
    assert mgr.get_state("BTCUSDT", PositionSide.LONG) == TradeLockState.EXPIRED

    # After sweep, state -> FREE
    purged = mgr.sweep_expired()
    assert purged >= 1
    assert mgr.get_state("BTCUSDT", PositionSide.LONG) == TradeLockState.FREE


def test_sweep_expired() -> None:
    mgr = KPMDistributedTradeLockManager()
    mgr.acquire("BTCUSDT", PositionSide.LONG, "s1", ttl_s=0.05)
    mgr.acquire("ETHUSDT", PositionSide.SHORT, "s2", ttl_s=0.05)
    mgr.acquire("SOLUSDT", PositionSide.LONG, "s3", ttl_s=10.0)  # not expired
    time.sleep(0.1)

    purged = mgr.sweep_expired()
    assert purged == 2
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is False
    assert mgr.is_held("ETHUSDT", PositionSide.SHORT) is False
    assert mgr.is_held("SOLUSDT", PositionSide.LONG) is True


def test_list_active_excludes_expired() -> None:
    mgr = KPMDistributedTradeLockManager()
    mgr.acquire("BTCUSDT", PositionSide.LONG, "s1", ttl_s=0.05)
    mgr.acquire("ETHUSDT", PositionSide.LONG, "s2", ttl_s=10.0)

    # Before expiry: 2 active
    active_before = mgr.list_active()
    assert len(active_before) == 2

    time.sleep(0.1)
    active_after = mgr.list_active()
    # Only ETHUSDT visible (BTCUSDT expired)
    assert len(active_after) == 1
    assert active_after[0].instrument_id == "ETHUSDT"
    assert active_after[0].holder_strategy_id == "s2"
    # list_active returns tuple (immutable)
    assert isinstance(active_after, tuple)


# ---------------------------------------------------------------------------
# Concurrent-Access
# ---------------------------------------------------------------------------


def test_concurrent_50_threads_only_one() -> None:
    """50 Threads kompetitieren um (BTCUSDT, LONG); nur einer gewinnt."""
    mgr = KPMDistributedTradeLockManager(default_ttl_s=10.0)
    results: list[bool] = []
    barrier = threading.Barrier(50)
    results_lock = threading.Lock()

    def worker(strat_id: str) -> None:
        barrier.wait()  # synchronize start
        r = mgr.acquire("BTCUSDT", PositionSide.LONG, strat_id)
        with results_lock:
            results.append(r.success)

    threads = [
        threading.Thread(target=worker, args=(f"strat-{i}",)) for i in range(50)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == 1, "Only one thread may acquire the lock"
    assert mgr.is_held("BTCUSDT", PositionSide.LONG) is True


# ---------------------------------------------------------------------------
# Frozen-Immutability
# ---------------------------------------------------------------------------


def test_lease_frozen() -> None:
    mgr = KPMDistributedTradeLockManager()
    r = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A")
    assert r.lease is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.lease.holder_strategy_id = "hijacker"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.lease.lease_token = "fake"  # type: ignore[misc]


def test_result_frozen() -> None:
    mgr = KPMDistributedTradeLockManager()
    r = mgr.acquire("BTCUSDT", PositionSide.LONG, "strat-A")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.success = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.reason = "tampered"  # type: ignore[misc]


# CRUX-MK
