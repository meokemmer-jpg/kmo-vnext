# [CRUX-MK]
"""Tests fuer 9dots-Distributed-Project-Lock (Welle-38 Phase-31 W38-T3)."""
from __future__ import annotations

import time

import pytest

from kmo_governance.ninedots_distributed_lock import (
    NineDotsDistributedLock,
    ProjectLockResult,
    ProjectLockState,
)


def test_init_validation() -> None:
    NineDotsDistributedLock()  # default OK
    with pytest.raises(ValueError):
        NineDotsDistributedLock(default_ttl_s=0)
    with pytest.raises(ValueError):
        NineDotsDistributedLock(max_locks=0)


def test_acquire_basic_success() -> None:
    """Conservative: free slot -> acquire OK."""
    locks = NineDotsDistributedLock()
    result = locks.acquire(
        project_id="proj-001",
        phase="phase-1",
        owner_role="lead",
        holder_session_id="session-alice",
    )
    assert result.success is True
    assert result.state == ProjectLockState.HELD
    assert result.holder_session_id == "session-alice"
    assert result.lease_token is not None


def test_acquire_held_by_other_blocks() -> None:
    """Aggressive: different holder cannot acquire held lock."""
    locks = NineDotsDistributedLock()
    locks.acquire("proj-001", "phase-1", "lead", "alice")
    result = locks.acquire("proj-001", "phase-1", "lead", "bob")
    assert result.success is False
    assert result.state == ProjectLockState.HELD
    assert result.holder_session_id == "alice"


def test_acquire_same_holder_renews() -> None:
    """Re-acquire by same holder = TTL renewal."""
    locks = NineDotsDistributedLock(default_ttl_s=10.0)
    r1 = locks.acquire("proj-001", "phase-1", "lead", "alice")
    r2 = locks.acquire("proj-001", "phase-1", "lead", "alice")
    assert r1.success is True
    assert r2.success is True
    assert r1.lease_token != r2.lease_token  # new token on renewal


def test_release_with_correct_token() -> None:
    """Release with matching token succeeds."""
    locks = NineDotsDistributedLock()
    a = locks.acquire("proj-001", "phase-1", "lead", "alice")
    r = locks.release("proj-001", "phase-1", "lead", a.lease_token)
    assert r.success is True
    assert r.state == ProjectLockState.AVAILABLE


def test_release_with_wrong_token_fails() -> None:
    """Wrong token should NOT release (anti-race)."""
    locks = NineDotsDistributedLock()
    locks.acquire("proj-001", "phase-1", "lead", "alice")
    r = locks.release("proj-001", "phase-1", "lead", "fake-token")
    assert r.success is False
    assert r.state == ProjectLockState.HELD


def test_release_idempotent_no_lock() -> None:
    """Release on free slot = idempotent (success=True)."""
    locks = NineDotsDistributedLock()
    r = locks.release("proj-001", "phase-1", "lead", "any-token")
    assert r.success is True


def test_acquire_after_ttl_expiry() -> None:
    """TTL-Expiry: lock auto-released, new acquire succeeds."""
    locks = NineDotsDistributedLock(default_ttl_s=0.05)
    locks.acquire("proj-001", "phase-1", "lead", "alice")
    time.sleep(0.1)
    r = locks.acquire("proj-001", "phase-1", "lead", "bob")
    assert r.success is True
    assert r.holder_session_id == "bob"


def test_get_holder() -> None:
    locks = NineDotsDistributedLock()
    locks.acquire("p", "ph", "lead", "alice")
    assert locks.get_holder("p", "ph", "lead") == "alice"
    assert locks.get_holder("p", "other", "lead") is None


def test_active_locks_count() -> None:
    locks = NineDotsDistributedLock()
    assert locks.active_locks_count() == 0
    locks.acquire("p1", "ph1", "lead", "alice")
    locks.acquire("p2", "ph1", "lead", "bob")
    assert locks.active_locks_count() == 2


def test_max_locks_limit() -> None:
    locks = NineDotsDistributedLock(max_locks=2)
    locks.acquire("p1", "ph1", "lead", "alice")
    locks.acquire("p2", "ph1", "lead", "bob")
    r = locks.acquire("p3", "ph1", "lead", "carol")
    assert r.success is False
    assert r.state == ProjectLockState.AVAILABLE  # no slot available


def test_acquire_empty_field_raises() -> None:
    locks = NineDotsDistributedLock()
    with pytest.raises(ValueError):
        locks.acquire("", "ph", "lead", "alice")
    with pytest.raises(ValueError):
        locks.acquire("p", "", "lead", "alice")


def test_acquire_ttl_validation() -> None:
    locks = NineDotsDistributedLock()
    with pytest.raises(ValueError):
        locks.acquire("p", "ph", "lead", "alice", ttl_s=0)


def test_result_frozen_immutability() -> None:
    locks = NineDotsDistributedLock()
    r = locks.acquire("p", "ph", "lead", "alice")
    with pytest.raises(Exception):
        r.success = False  # type: ignore[misc]


def test_different_phase_independent() -> None:
    """Different (project, phase, role) tuple = independent locks."""
    locks = NineDotsDistributedLock()
    r1 = locks.acquire("p", "phase-1", "lead", "alice")
    r2 = locks.acquire("p", "phase-2", "lead", "bob")  # different phase
    assert r1.success is True
    assert r2.success is True


# CRUX-MK
