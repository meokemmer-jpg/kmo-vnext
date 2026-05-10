# [CRUX-MK]
"""Tests fuer LexVance-Distributed-Document-Lock (Welle-41 Phase-34)."""
from __future__ import annotations

import time

import pytest

from kmo_governance.lexvance_distributed_lock import (
    DocumentLockResult,
    DocumentLockState,
    LexVanceDistributedLock,
)


def test_init_validation() -> None:
    LexVanceDistributedLock()  # default OK
    with pytest.raises(ValueError):
        LexVanceDistributedLock(default_ttl_s=0)
    with pytest.raises(ValueError):
        LexVanceDistributedLock(max_locks=0)


def test_acquire_basic_success() -> None:
    locks = LexVanceDistributedLock()
    r = locks.acquire("m1", "doc-001", "draft", "lawyer-alice")
    assert r.success is True
    assert r.state == DocumentLockState.HELD
    assert r.holder_lawyer_id == "lawyer-alice"


def test_acquire_held_by_other_blocks() -> None:
    locks = LexVanceDistributedLock()
    locks.acquire("m1", "doc-001", "draft", "alice")
    r = locks.acquire("m1", "doc-001", "draft", "bob")
    assert r.success is False
    assert r.state == DocumentLockState.HELD


def test_acquire_same_lawyer_renews() -> None:
    locks = LexVanceDistributedLock()
    a = locks.acquire("m1", "doc-001", "draft", "alice")
    b = locks.acquire("m1", "doc-001", "draft", "alice")
    assert a.success is True
    assert b.success is True
    assert a.lease_token != b.lease_token


def test_release_with_correct_token() -> None:
    locks = LexVanceDistributedLock()
    a = locks.acquire("m1", "doc-001", "draft", "alice")
    r = locks.release("m1", "doc-001", "draft", a.lease_token)
    assert r.success is True


def test_release_with_wrong_token_fails() -> None:
    locks = LexVanceDistributedLock()
    locks.acquire("m1", "doc-001", "draft", "alice")
    r = locks.release("m1", "doc-001", "draft", "fake")
    assert r.success is False
    assert r.state == DocumentLockState.HELD


def test_conflict_of_interest_blocks_acquire() -> None:
    """Rival-Mandanten: derselbe lawyer kann nicht beide bedienen."""
    locks = LexVanceDistributedLock()
    locks.declare_rival_mandanten("client-A", "client-B")
    locks.acquire("client-A", "doc-001", "draft", "lawyer-x")
    r = locks.acquire("client-B", "doc-002", "draft", "lawyer-x")
    assert r.success is False
    assert r.state == DocumentLockState.CONFLICT_OF_INTEREST


def test_no_coi_when_not_declared() -> None:
    """Ohne declare_rival_mandanten ist alles erlaubt."""
    locks = LexVanceDistributedLock()
    locks.acquire("m1", "doc1", "draft", "lawyer-x")
    r = locks.acquire("m2", "doc2", "draft", "lawyer-x")
    assert r.success is True


def test_declare_rival_validation() -> None:
    locks = LexVanceDistributedLock()
    with pytest.raises(ValueError):
        locks.declare_rival_mandanten("", "m2")
    with pytest.raises(ValueError):
        locks.declare_rival_mandanten("m1", "m1")


def test_acquire_after_ttl_expiry() -> None:
    locks = LexVanceDistributedLock(default_ttl_s=0.05)
    locks.acquire("m1", "doc", "draft", "alice")
    time.sleep(0.1)
    r = locks.acquire("m1", "doc", "draft", "bob")
    assert r.success is True


def test_max_locks_limit() -> None:
    locks = LexVanceDistributedLock(max_locks=2)
    locks.acquire("m1", "doc1", "draft", "a")
    locks.acquire("m1", "doc2", "draft", "a")  # same lawyer same mandant
    r = locks.acquire("m1", "doc3", "draft", "a")
    assert r.success is False


def test_active_locks_count() -> None:
    locks = LexVanceDistributedLock()
    locks.acquire("m1", "doc1", "draft", "alice")
    locks.acquire("m1", "doc2", "draft", "alice")
    assert locks.active_locks_count() == 2


def test_result_frozen_immutability() -> None:
    locks = LexVanceDistributedLock()
    r = locks.acquire("m1", "doc", "draft", "alice")
    with pytest.raises(Exception):
        r.success = False  # type: ignore[misc]


def test_acquire_empty_field_raises() -> None:
    locks = LexVanceDistributedLock()
    with pytest.raises(ValueError):
        locks.acquire("", "doc", "draft", "alice")
    with pytest.raises(ValueError):
        locks.acquire("m1", "", "draft", "alice")
    with pytest.raises(ValueError):
        locks.acquire("m1", "doc", "draft", "")


def test_release_idempotent_no_lock() -> None:
    locks = LexVanceDistributedLock()
    r = locks.release("m1", "doc", "draft", "any-token")
    assert r.success is True


# ---------------------------------------------------------------------------
# W47-P2 (V20-F2-Fix): COI Retroaktive Pruefung
# ---------------------------------------------------------------------------


def test_w47p2_declare_rival_returns_conflicting_lawyers() -> None:
    """W47-P2: declare_rival_mandanten erkennt existing locks die jetzt COI sind."""
    locks = LexVanceDistributedLock()
    locks.acquire("client-A", "doc1", "draft", "lawyer-x")
    locks.acquire("client-B", "doc2", "draft", "lawyer-x")
    # Vor declare: kein conflict
    # Nach declare: x hatte Locks bei beiden -> retro-conflict
    conflicts = locks.declare_rival_mandanten("client-A", "client-B")
    assert "lawyer-x" in conflicts


def test_w47p2_no_retro_conflict_returns_empty() -> None:
    """W47-P2: keine existing locks -> empty tuple."""
    locks = LexVanceDistributedLock()
    conflicts = locks.declare_rival_mandanten("client-A", "client-B")
    assert conflicts == ()


def test_w47p2_retro_only_lawyer_at_both_returned() -> None:
    """W47-P2: nur lawyers die bei BEIDEN Locks halten zaehlen."""
    locks = LexVanceDistributedLock()
    locks.acquire("client-A", "doc1", "draft", "alice")
    locks.acquire("client-B", "doc2", "draft", "bob")
    conflicts = locks.declare_rival_mandanten("client-A", "client-B")
    assert conflicts == ()  # alice + bob sind verschiedene lawyers


# CRUX-MK
