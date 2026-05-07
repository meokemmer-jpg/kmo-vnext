"""Tests for KMO Distributed-Lock-Manager [CRUX-MK].

Welle-21 Phase-14 Test-Suite. 16+ Tests inkl.:
- Init-Validation
- Acquire / Renew / Release / Force-Release
- Token-Validation (invalid token rejected)
- Auto-Release expired Leases
- Sweep-Reaper
- Concurrent-Access (50 threads, only one acquires)
- Frozen-Immutability (Lease + LockResult)
- State-Transitions (FREE / ACQUIRED / EXPIRED)
"""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from kmo_governance.distributed_lock_manager import (
    DistributedLockManager,
    Lease,
    LockResult,
    LockState,
)


# ---------------------------------------------------------------------------
# Init-Validation
# ---------------------------------------------------------------------------


def test_init_validation() -> None:
    # Default works
    DistributedLockManager()
    DistributedLockManager(default_ttl_s=10.0, sweep_interval_s=1.0)

    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        DistributedLockManager(default_ttl_s=0)
    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        DistributedLockManager(default_ttl_s=-1.0)
    with pytest.raises(ValueError, match="sweep_interval_s must be > 0"):
        DistributedLockManager(sweep_interval_s=0)
    with pytest.raises(ValueError, match="sweep_interval_s must be > 0"):
        DistributedLockManager(sweep_interval_s=-0.5)


# ---------------------------------------------------------------------------
# Acquire
# ---------------------------------------------------------------------------


def test_acquire_free_lock() -> None:
    mgr = DistributedLockManager(default_ttl_s=30.0)
    result = mgr.acquire("res-A", "holder-1")
    assert result.success is True
    assert result.lock_id == "res-A"
    assert result.lease is not None
    assert result.lease.holder_id == "holder-1"
    assert result.lease.lock_id == "res-A"
    assert result.lease.lease_token  # non-empty
    assert result.conflict_holder is None
    assert result.reason == "acquired"


def test_acquire_held_lock_returns_conflict() -> None:
    mgr = DistributedLockManager(default_ttl_s=30.0)
    r1 = mgr.acquire("res-A", "holder-1")
    assert r1.success is True

    r2 = mgr.acquire("res-A", "holder-2")
    assert r2.success is False
    assert r2.lease is None
    assert r2.conflict_holder == "holder-1"
    assert "held by holder-1" in r2.reason


def test_acquire_expired_lock_succeeds_after_auto_release() -> None:
    mgr = DistributedLockManager(default_ttl_s=30.0)
    r1 = mgr.acquire("res-A", "holder-1", ttl_s=0.05)
    assert r1.success is True

    # Wait for expiry
    time.sleep(0.1)

    # holder-2 should now succeed (auto-release of expired lease)
    r2 = mgr.acquire("res-A", "holder-2")
    assert r2.success is True
    assert r2.lease is not None
    assert r2.lease.holder_id == "holder-2"
    # Token should be different
    assert r2.lease.lease_token != r1.lease.lease_token


def test_acquire_input_validation() -> None:
    mgr = DistributedLockManager()
    with pytest.raises(ValueError, match="lock_id must be non-empty"):
        mgr.acquire("", "holder-1")
    with pytest.raises(ValueError, match="holder_id must be non-empty"):
        mgr.acquire("res-A", "")
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        mgr.acquire("res-A", "holder-1", ttl_s=0)
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        mgr.acquire("res-A", "holder-1", ttl_s=-1.0)


# ---------------------------------------------------------------------------
# Renew
# ---------------------------------------------------------------------------


def test_renew_extends_expiry() -> None:
    mgr = DistributedLockManager(default_ttl_s=30.0)
    r1 = mgr.acquire("res-A", "holder-1", ttl_s=10.0)
    assert r1.success is True
    original_expires = r1.lease.expires_at
    original_token = r1.lease.lease_token

    time.sleep(0.05)
    r2 = mgr.renew("res-A", original_token, additional_ttl_s=60.0)
    assert r2.success is True
    assert r2.lease is not None
    assert r2.lease.expires_at > original_expires
    # Token preserved across renew
    assert r2.lease.lease_token == original_token
    # holder + acquired_at preserved
    assert r2.lease.holder_id == "holder-1"
    assert r2.lease.acquired_at == r1.lease.acquired_at
    assert r2.reason == "renewed"


def test_renew_with_invalid_token_fails() -> None:
    mgr = DistributedLockManager()
    r1 = mgr.acquire("res-A", "holder-1")
    assert r1.success is True

    r2 = mgr.renew("res-A", "wrong-token-deadbeef")
    assert r2.success is False
    assert r2.lease is None
    assert r2.conflict_holder == "holder-1"
    assert "invalid lease_token" in r2.reason


def test_renew_unknown_lock_fails() -> None:
    mgr = DistributedLockManager()
    r = mgr.renew("nonexistent", "any-token")
    assert r.success is False
    assert r.reason == "lock not found"


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------


def test_release_with_valid_token() -> None:
    mgr = DistributedLockManager()
    r1 = mgr.acquire("res-A", "holder-1")
    assert r1.success is True

    r2 = mgr.release("res-A", r1.lease.lease_token)
    assert r2.success is True
    assert r2.reason == "released"
    assert mgr.is_held("res-A") is False
    assert mgr.get_state("res-A") == LockState.FREE


def test_release_with_invalid_token_fails() -> None:
    mgr = DistributedLockManager()
    r1 = mgr.acquire("res-A", "holder-1")
    assert r1.success is True

    r2 = mgr.release("res-A", "evil-token-cafebabe")
    assert r2.success is False
    assert r2.conflict_holder == "holder-1"
    assert "invalid lease_token" in r2.reason
    # Lock should still be held
    assert mgr.is_held("res-A") is True


# ---------------------------------------------------------------------------
# Force-Release
# ---------------------------------------------------------------------------


def test_force_release_overrides_holder() -> None:
    mgr = DistributedLockManager()
    r1 = mgr.acquire("res-A", "holder-1")
    assert r1.success is True

    # Admin override without token
    r2 = mgr.force_release("res-A")
    assert r2.success is True
    assert "force-released" in r2.reason
    assert "holder-1" in r2.reason
    assert mgr.is_held("res-A") is False

    # Now holder-2 can acquire
    r3 = mgr.acquire("res-A", "holder-2")
    assert r3.success is True


def test_force_release_unknown_lock() -> None:
    mgr = DistributedLockManager()
    r = mgr.force_release("nonexistent")
    assert r.success is False
    assert r.reason == "lock not found"


# ---------------------------------------------------------------------------
# State / Inspection
# ---------------------------------------------------------------------------


def test_is_held_correct() -> None:
    mgr = DistributedLockManager()
    assert mgr.is_held("res-A") is False
    assert mgr.is_held("") is False  # edge-case: empty lock_id

    r = mgr.acquire("res-A", "holder-1", ttl_s=0.05)
    assert mgr.is_held("res-A") is True

    time.sleep(0.1)
    assert mgr.is_held("res-A") is False  # expired


def test_get_state_transitions() -> None:
    mgr = DistributedLockManager()
    # FREE
    assert mgr.get_state("res-A") == LockState.FREE
    assert mgr.get_state("") == LockState.FREE

    # ACQUIRED
    r = mgr.acquire("res-A", "holder-1", ttl_s=0.05)
    assert mgr.get_state("res-A") == LockState.ACQUIRED

    # EXPIRED (after timeout)
    time.sleep(0.1)
    assert mgr.get_state("res-A") == LockState.EXPIRED

    # FREE again after force-release
    mgr.force_release("res-A")
    assert mgr.get_state("res-A") == LockState.FREE


# ---------------------------------------------------------------------------
# Sweep / List
# ---------------------------------------------------------------------------


def test_sweep_expired_purges_old() -> None:
    mgr = DistributedLockManager()
    mgr.acquire("res-A", "h1", ttl_s=0.05)
    mgr.acquire("res-B", "h2", ttl_s=0.05)
    mgr.acquire("res-C", "h3", ttl_s=10.0)  # long-lived

    time.sleep(0.1)
    purged = mgr.sweep_expired()
    assert purged == 2
    assert mgr.is_held("res-A") is False
    assert mgr.is_held("res-B") is False
    assert mgr.is_held("res-C") is True

    # Second sweep is no-op
    assert mgr.sweep_expired() == 0


def test_list_active_excludes_expired() -> None:
    mgr = DistributedLockManager()
    mgr.acquire("res-A", "h1", ttl_s=0.05)
    mgr.acquire("res-B", "h2", ttl_s=10.0)
    mgr.acquire("res-C", "h3", ttl_s=10.0)

    time.sleep(0.1)
    active = mgr.list_active()
    active_ids = {lease.lock_id for lease in active}
    assert active_ids == {"res-B", "res-C"}
    assert "res-A" not in active_ids


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_50_threads_only_one_acquires() -> None:
    mgr = DistributedLockManager(default_ttl_s=30.0)
    n_threads = 50
    barrier = threading.Barrier(n_threads)
    results: list[LockResult] = []
    results_lock = threading.Lock()

    def attempt_acquire(holder_id: str) -> None:
        barrier.wait()  # all threads attempt simultaneously
        r = mgr.acquire("hot-resource", holder_id)
        with results_lock:
            results.append(r)

    threads = [
        threading.Thread(target=attempt_acquire, args=(f"holder-{i}",))
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 1
    assert len(failures) == n_threads - 1
    # All failures must report the winning holder
    winner_id = successes[0].lease.holder_id
    for f in failures:
        assert f.conflict_holder == winner_id


# ---------------------------------------------------------------------------
# Frozen-Immutability
# ---------------------------------------------------------------------------


def test_lease_frozen_immutability() -> None:
    mgr = DistributedLockManager()
    r = mgr.acquire("res-A", "holder-1")
    lease = r.lease
    assert lease is not None

    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.holder_id = "evil-holder"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.lease_token = "hijacked"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.expires_at = 1e18  # type: ignore[misc]


def test_result_frozen_immutability() -> None:
    mgr = DistributedLockManager()
    r = mgr.acquire("res-A", "holder-1")

    with pytest.raises(dataclasses.FrozenInstanceError):
        r.success = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.reason = "tampered"  # type: ignore[misc]


def test_lease_validation() -> None:
    # Direct Lease construction validates pre-conditions
    with pytest.raises(ValueError, match="lock_id must be non-empty"):
        Lease(lock_id="", holder_id="h", acquired_at=0.0, expires_at=1.0,
              ttl_s=1.0, lease_token="x")
    with pytest.raises(ValueError, match="holder_id must be non-empty"):
        Lease(lock_id="L", holder_id="", acquired_at=0.0, expires_at=1.0,
              ttl_s=1.0, lease_token="x")
    with pytest.raises(ValueError, match="expires_at must be > acquired_at"):
        Lease(lock_id="L", holder_id="h", acquired_at=5.0, expires_at=5.0,
              ttl_s=1.0, lease_token="x")
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        Lease(lock_id="L", holder_id="h", acquired_at=0.0, expires_at=1.0,
              ttl_s=0.0, lease_token="x")
    with pytest.raises(ValueError, match="lease_token must be non-empty"):
        Lease(lock_id="L", holder_id="h", acquired_at=0.0, expires_at=1.0,
              ttl_s=1.0, lease_token="")


# CRUX-MK
