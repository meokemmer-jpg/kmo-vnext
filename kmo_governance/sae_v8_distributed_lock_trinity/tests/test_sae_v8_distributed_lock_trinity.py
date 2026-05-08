# [CRUX-MK]
"""Tests fuer SAE-v8-Distributed-Trinity-Voting-Lock-Manager [CRUX-MK].

Welle-34 Phase-27 Test-Suite (18+ Tests).

Coverage:
- Init-Validation (TTL/sweep > 0)
- Acquire (free / held / expired auto-release / input-validation)
- Renew (extend / invalid token / expired)
- Release (valid token / invalid token)
- Force-Release (admin override)
- Voting-Round-Independence (same slot, different rounds = separate locks)
- Variant-Independence-Per-Round (different rounds with different variants)
- is_held / get_state / sweep_expired
- list_active / list_active_for_slot
- Concurrency (50 threads barrier, exactly 1 success)
- Frozen Dataclass Invariants (FrozenInstanceError)
"""

from __future__ import annotations

import dataclasses
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from kmo_governance.sae_v8_distributed_lock_trinity import (
    SAEv8DistributedTrinityLockManager,
    TrinityVariant,
    TrinityVotingLease,
    TrinityVotingLockResult,
    VotingLockState,
)


# ---------------------------------------------------------------------------
# Init / Validation
# ---------------------------------------------------------------------------


def test_init_validation():
    """default_ttl_s und sweep_interval_s muessen > 0 sein."""
    SAEv8DistributedTrinityLockManager(default_ttl_s=10.0, sweep_interval_s=1.0)
    SAEv8DistributedTrinityLockManager()  # defaults

    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        SAEv8DistributedTrinityLockManager(default_ttl_s=0.0)
    with pytest.raises(ValueError, match="default_ttl_s must be > 0"):
        SAEv8DistributedTrinityLockManager(default_ttl_s=-1.0)
    with pytest.raises(ValueError, match="sweep_interval_s must be > 0"):
        SAEv8DistributedTrinityLockManager(sweep_interval_s=0.0)
    with pytest.raises(ValueError, match="sweep_interval_s must be > 0"):
        SAEv8DistributedTrinityLockManager(sweep_interval_s=-2.0)


# ---------------------------------------------------------------------------
# Acquire
# ---------------------------------------------------------------------------


def test_acquire_free_voting_lock():
    """Erfolg auf freiem Lock + Lease + Token vorhanden."""
    mgr = SAEv8DistributedTrinityLockManager()
    r = mgr.acquire(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_alpha",
        variant_locked=TrinityVariant.CONSERVATIVE,
    )
    assert r.success is True
    assert r.slot_id == "slot_42"
    assert r.voting_round_id == "round_001"
    assert r.reason == "acquired"
    assert r.lease is not None
    assert r.lease.holder_voter_id == "voter_alpha"
    assert r.lease.variant_locked is TrinityVariant.CONSERVATIVE
    assert r.lease.lease_token  # nicht-leer (uuid hex)
    assert r.lease.ttl_s == 10.0  # default
    assert r.conflict_holder is None


def test_acquire_held_returns_conflict():
    """Acquire auf bereits gehaltenem Lock -> success=False mit conflict_holder."""
    mgr = SAEv8DistributedTrinityLockManager()
    mgr.acquire(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_alpha",
        variant_locked=TrinityVariant.AGGRESSIVE,
    )
    r2 = mgr.acquire(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_beta",
        variant_locked=TrinityVariant.CONSERVATIVE,
    )
    assert r2.success is False
    assert r2.conflict_holder == "voter_alpha"
    assert "voter_alpha" in r2.reason
    assert r2.lease is None


def test_acquire_expired_auto_release():
    """Lock mit ttl=0.05 + sleep(0.1) -> Reacquire moeglich (Auto-Release)."""
    mgr = SAEv8DistributedTrinityLockManager()
    r1 = mgr.acquire(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_alpha",
        variant_locked=TrinityVariant.CONSERVATIVE,
        ttl_s=0.05,
    )
    assert r1.success is True
    time.sleep(0.1)
    r2 = mgr.acquire(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_beta",
        variant_locked=TrinityVariant.CONTRARIAN,
    )
    assert r2.success is True
    assert r2.lease is not None
    assert r2.lease.holder_voter_id == "voter_beta"
    assert r2.lease.variant_locked is TrinityVariant.CONTRARIAN
    # Token muss neu sein
    assert r2.lease.lease_token != r1.lease.lease_token


def test_acquire_validates_inputs():
    """Empty/None-Inputs + falsche Variant-Type werden abgewiesen."""
    mgr = SAEv8DistributedTrinityLockManager()

    with pytest.raises(ValueError, match="slot_id must be non-empty"):
        mgr.acquire("", "round_1", "v_a", TrinityVariant.CONSERVATIVE)
    with pytest.raises(ValueError, match="voting_round_id must be non-empty"):
        mgr.acquire("slot_42", "", "v_a", TrinityVariant.CONSERVATIVE)
    with pytest.raises(ValueError, match="holder_voter_id must be non-empty"):
        mgr.acquire("slot_42", "round_1", "", TrinityVariant.CONSERVATIVE)
    with pytest.raises(ValueError, match="variant_locked must be a TrinityVariant"):
        mgr.acquire("slot_42", "round_1", "v_a", "conservative")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        mgr.acquire("slot_42", "round_1", "v_a", TrinityVariant.CONSERVATIVE, ttl_s=0.0)
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        mgr.acquire("slot_42", "round_1", "v_a", TrinityVariant.CONSERVATIVE, ttl_s=-3.0)


# ---------------------------------------------------------------------------
# Renew
# ---------------------------------------------------------------------------


def test_renew_extends():
    """Renew verlaengert expires_at und behaelt Token + acquired_at."""
    mgr = SAEv8DistributedTrinityLockManager()
    r1 = mgr.acquire(
        "slot_42", "round_001", "voter_alpha", TrinityVariant.CONSERVATIVE, ttl_s=2.0
    )
    assert r1.success and r1.lease is not None
    original_expires = r1.lease.expires_at
    original_acquired = r1.lease.acquired_at
    original_token = r1.lease.lease_token

    time.sleep(0.05)
    r2 = mgr.renew("slot_42", "round_001", original_token, additional_ttl_s=5.0)
    assert r2.success is True
    assert r2.lease is not None
    assert r2.lease.expires_at > original_expires
    assert r2.lease.acquired_at == original_acquired  # preserved
    assert r2.lease.lease_token == original_token  # preserved
    assert r2.lease.ttl_s == 5.0


def test_renew_invalid_token():
    """Token-Mismatch -> success=False, Lock haelt unveraendert."""
    mgr = SAEv8DistributedTrinityLockManager()
    r1 = mgr.acquire(
        "slot_42", "round_001", "voter_alpha", TrinityVariant.CONSERVATIVE
    )
    r2 = mgr.renew("slot_42", "round_001", "fake-token-xyz")
    assert r2.success is False
    assert "invalid lease_token" in r2.reason
    assert r2.conflict_holder == "voter_alpha"
    # Lock muss noch existieren
    assert mgr.is_held("slot_42", "round_001")


def test_renew_lock_not_found():
    """Renew auf nicht-existentem Lock -> 'not found'."""
    mgr = SAEv8DistributedTrinityLockManager()
    r = mgr.renew("slot_99", "round_999", "any-token")
    assert r.success is False
    assert "not found" in r.reason


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------


def test_release_valid_token():
    """Release mit korrektem Token -> success=True + State -> FREE."""
    mgr = SAEv8DistributedTrinityLockManager()
    r1 = mgr.acquire(
        "slot_42", "round_001", "voter_alpha", TrinityVariant.AGGRESSIVE
    )
    token = r1.lease.lease_token
    r2 = mgr.release("slot_42", "round_001", token)
    assert r2.success is True
    assert r2.reason == "released"
    assert mgr.get_state("slot_42", "round_001") is VotingLockState.FREE
    assert not mgr.is_held("slot_42", "round_001")


def test_release_invalid_token():
    """Release mit falschem Token -> success=False, Lock haelt."""
    mgr = SAEv8DistributedTrinityLockManager()
    mgr.acquire("slot_42", "round_001", "voter_alpha", TrinityVariant.CONSERVATIVE)
    r = mgr.release("slot_42", "round_001", "wrong-token")
    assert r.success is False
    assert "invalid lease_token" in r.reason
    assert r.conflict_holder == "voter_alpha"
    # Lock muss noch existieren
    assert mgr.is_held("slot_42", "round_001")


# ---------------------------------------------------------------------------
# Force-Release (Admin Override)
# ---------------------------------------------------------------------------


def test_force_release():
    """Force-Release ohne Token + Reason enthaelt Holder-Name."""
    mgr = SAEv8DistributedTrinityLockManager()
    mgr.acquire("slot_42", "round_001", "voter_alpha", TrinityVariant.CONTRARIAN)
    r = mgr.force_release("slot_42", "round_001")
    assert r.success is True
    assert "force-released" in r.reason
    assert "voter_alpha" in r.reason
    assert mgr.get_state("slot_42", "round_001") is VotingLockState.FREE


def test_force_release_not_found():
    """Force-Release auf nicht-existentem Lock -> success=False."""
    mgr = SAEv8DistributedTrinityLockManager()
    r = mgr.force_release("slot_99", "round_999")
    assert r.success is False
    assert "not found" in r.reason


# ---------------------------------------------------------------------------
# Voting-Round-Independence + Variant-Independence
# ---------------------------------------------------------------------------


def test_different_voting_rounds_independent():
    """Same slot_id, verschiedene voting_round_ids = separate Locks (no conflict)."""
    mgr = SAEv8DistributedTrinityLockManager()
    r1 = mgr.acquire(
        "slot_42", "round_001", "voter_alpha", TrinityVariant.CONSERVATIVE
    )
    r2 = mgr.acquire(
        "slot_42", "round_002", "voter_beta", TrinityVariant.AGGRESSIVE
    )
    assert r1.success is True
    assert r2.success is True
    # Tokens unabhaengig
    assert r1.lease.lease_token != r2.lease.lease_token
    # Beide Locks aktiv
    assert mgr.is_held("slot_42", "round_001")
    assert mgr.is_held("slot_42", "round_002")
    # release round_001 beruehrt round_002 nicht
    mgr.release("slot_42", "round_001", r1.lease.lease_token)
    assert not mgr.is_held("slot_42", "round_001")
    assert mgr.is_held("slot_42", "round_002")


def test_different_variants_per_round():
    """Verschiedene Variants pro voting_round funktionieren (Audit-Marker)."""
    mgr = SAEv8DistributedTrinityLockManager()
    r1 = mgr.acquire(
        "slot_42", "round_001", "voter_a", TrinityVariant.CONSERVATIVE
    )
    r2 = mgr.acquire(
        "slot_42", "round_002", "voter_b", TrinityVariant.AGGRESSIVE
    )
    r3 = mgr.acquire(
        "slot_42", "round_003", "voter_c", TrinityVariant.CONTRARIAN
    )
    assert r1.success and r2.success and r3.success
    assert r1.lease.variant_locked is TrinityVariant.CONSERVATIVE
    assert r2.lease.variant_locked is TrinityVariant.AGGRESSIVE
    assert r3.lease.variant_locked is TrinityVariant.CONTRARIAN


# ---------------------------------------------------------------------------
# Inspection: is_held / get_state
# ---------------------------------------------------------------------------


def test_is_held():
    """is_held: True nach acquire, False nach release/force_release/empty-input."""
    mgr = SAEv8DistributedTrinityLockManager()
    assert mgr.is_held("slot_42", "round_001") is False
    r = mgr.acquire("slot_42", "round_001", "voter_a", TrinityVariant.CONSERVATIVE)
    assert mgr.is_held("slot_42", "round_001") is True
    mgr.release("slot_42", "round_001", r.lease.lease_token)
    assert mgr.is_held("slot_42", "round_001") is False
    # Empty-Inputs -> False (graceful)
    assert mgr.is_held("", "round_001") is False
    assert mgr.is_held("slot_42", "") is False


def test_get_state():
    """FREE -> ACQUIRED -> EXPIRED -> (sweep) -> FREE."""
    mgr = SAEv8DistributedTrinityLockManager()
    assert mgr.get_state("slot_42", "round_001") is VotingLockState.FREE
    mgr.acquire(
        "slot_42", "round_001", "voter_a", TrinityVariant.CONSERVATIVE, ttl_s=0.05
    )
    assert mgr.get_state("slot_42", "round_001") is VotingLockState.ACQUIRED
    time.sleep(0.1)
    assert mgr.get_state("slot_42", "round_001") is VotingLockState.EXPIRED
    mgr.sweep_expired()
    assert mgr.get_state("slot_42", "round_001") is VotingLockState.FREE
    # Empty-Inputs -> FREE
    assert mgr.get_state("", "round_001") is VotingLockState.FREE
    assert mgr.get_state("slot_42", "") is VotingLockState.FREE


# ---------------------------------------------------------------------------
# Sweep / List
# ---------------------------------------------------------------------------


def test_sweep_expired():
    """sweep_expired purge Anzahl korrekt; only-expired removed."""
    mgr = SAEv8DistributedTrinityLockManager()
    mgr.acquire(
        "slot_a", "round_001", "voter_1", TrinityVariant.CONSERVATIVE, ttl_s=0.05
    )
    mgr.acquire(
        "slot_b", "round_001", "voter_2", TrinityVariant.AGGRESSIVE, ttl_s=0.05
    )
    mgr.acquire(
        "slot_c", "round_001", "voter_3", TrinityVariant.CONTRARIAN, ttl_s=10.0
    )
    time.sleep(0.1)
    purged = mgr.sweep_expired()
    assert purged == 2
    # slot_c bleibt aktiv
    assert mgr.is_held("slot_c", "round_001") is True
    assert mgr.is_held("slot_a", "round_001") is False
    assert mgr.is_held("slot_b", "round_001") is False


def test_list_active_excludes_expired():
    """list_active liefert Tuple und filtert expired raus."""
    mgr = SAEv8DistributedTrinityLockManager()
    mgr.acquire(
        "slot_a", "round_1", "voter_1", TrinityVariant.CONSERVATIVE, ttl_s=0.05
    )
    mgr.acquire(
        "slot_b", "round_1", "voter_2", TrinityVariant.AGGRESSIVE, ttl_s=10.0
    )
    time.sleep(0.1)
    active = mgr.list_active()
    assert isinstance(active, tuple)
    assert len(active) == 1
    assert active[0].slot_id == "slot_b"
    assert active[0].holder_voter_id == "voter_2"


def test_list_active_for_slot_filters():
    """list_active_for_slot liefert alle voting_rounds eines Slots."""
    mgr = SAEv8DistributedTrinityLockManager()
    mgr.acquire(
        "slot_42", "round_001", "voter_a", TrinityVariant.CONSERVATIVE
    )
    mgr.acquire(
        "slot_42", "round_002", "voter_b", TrinityVariant.AGGRESSIVE
    )
    mgr.acquire(
        "slot_99", "round_001", "voter_c", TrinityVariant.CONTRARIAN
    )
    leases_42 = mgr.list_active_for_slot("slot_42")
    assert isinstance(leases_42, tuple)
    assert len(leases_42) == 2
    rounds = {lease.voting_round_id for lease in leases_42}
    assert rounds == {"round_001", "round_002"}
    # slot_99 separat
    leases_99 = mgr.list_active_for_slot("slot_99")
    assert len(leases_99) == 1
    # Empty-Slot -> ()
    assert mgr.list_active_for_slot("") == ()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_50_threads_only_one():
    """Barrier + 50 Threads, exactly 1 Erfolg + 49 Conflicts auf gleichem Lock."""
    mgr = SAEv8DistributedTrinityLockManager()
    barrier = threading.Barrier(50)
    results: list[TrinityVotingLockResult] = []
    results_lock = threading.Lock()

    def worker(voter_idx: int):
        barrier.wait()  # alle Threads gleichzeitig starten
        r = mgr.acquire(
            "slot_42",
            "round_concurrent",
            f"voter_{voter_idx}",
            TrinityVariant.CONSERVATIVE,
            ttl_s=30.0,
        )
        with results_lock:
            results.append(r)

    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = [pool.submit(worker, i) for i in range(50)]
        for f in futures:
            f.result(timeout=5.0)

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 1
    assert len(failures) == 49
    # Alle Failures haben denselben conflict_holder
    winner_voter = successes[0].lease.holder_voter_id
    for f in failures:
        assert f.conflict_holder == winner_voter


# ---------------------------------------------------------------------------
# Frozen Dataclasses
# ---------------------------------------------------------------------------


def test_lease_frozen():
    """TrinityVotingLease ist frozen -> FrozenInstanceError bei Mutation."""
    lease = TrinityVotingLease(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_a",
        variant_locked=TrinityVariant.CONSERVATIVE,
        acquired_at=0.0,
        expires_at=10.0,
        ttl_s=10.0,
        lease_token="abc123",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.holder_voter_id = "voter_b"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.expires_at = 999.0  # type: ignore[misc]


def test_result_frozen():
    """TrinityVotingLockResult ist frozen -> FrozenInstanceError bei Mutation."""
    result = TrinityVotingLockResult(
        success=True,
        slot_id="slot_42",
        voting_round_id="round_001",
        timestamp=0.0,
        reason="acquired",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.success = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.reason = "tampered"  # type: ignore[misc]


def test_lease_post_init_validation():
    """TrinityVotingLease.__post_init__ validiert alle Pre-Conditions."""
    base = dict(
        slot_id="slot_42",
        voting_round_id="round_001",
        holder_voter_id="voter_a",
        variant_locked=TrinityVariant.CONSERVATIVE,
        acquired_at=0.0,
        expires_at=10.0,
        ttl_s=10.0,
        lease_token="abc",
    )
    with pytest.raises(ValueError, match="slot_id must be non-empty"):
        TrinityVotingLease(**{**base, "slot_id": ""})
    with pytest.raises(ValueError, match="voting_round_id must be non-empty"):
        TrinityVotingLease(**{**base, "voting_round_id": ""})
    with pytest.raises(ValueError, match="holder_voter_id must be non-empty"):
        TrinityVotingLease(**{**base, "holder_voter_id": ""})
    with pytest.raises(ValueError, match="variant_locked must be a TrinityVariant"):
        TrinityVotingLease(**{**base, "variant_locked": "conservative"})
    with pytest.raises(ValueError, match="acquired_at must be >= 0"):
        TrinityVotingLease(**{**base, "acquired_at": -1.0})
    with pytest.raises(ValueError, match="expires_at must be > acquired_at"):
        TrinityVotingLease(**{**base, "acquired_at": 10.0, "expires_at": 5.0})
    with pytest.raises(ValueError, match="ttl_s must be > 0"):
        TrinityVotingLease(**{**base, "ttl_s": 0.0})
    with pytest.raises(ValueError, match="lease_token must be non-empty"):
        TrinityVotingLease(**{**base, "lease_token": ""})


# CRUX-MK
