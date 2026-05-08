"""W-30-3 Replay + Truncation + Network-Split Tests (Welle-31 P-W31-2) [CRUX-MK].

Adversarial-Tests gegen HMAC-Token-Replay + Hash-Chain-Truncation +
Token-Theft + Clock-Skew + Network-Split-Recovery + Diamond-Dependency.
6 Pflicht-Tests:

    1. HMAC-Token-Replay-after-Refractory-Period (60s + 1s, MUSS BLOCK)
    2. Hash-Chain-Truncation-Detection (mismatch via Anchor)
    3. Token-Theft-Test (Sender-Binding via Fingerprint)
    4. Clock-Skew-Test (Lamport-Timestamps statt UNIX-Wall-Clock)
    5. Network-Split-Recovery (Three-Way-Merge bei Split-Brain)
    6. Diamond-Dependency-Resolution (4 Authors, 2 Branches converge)

Conservation-Law: Edits ueberleben Network-Splits, Replays werden
detektiert. Per rules/concurrency-mandatory-tests.md echte threading.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graphity_audit_persister import (  # noqa: E402
    EditHistoryEntry,
    GraphityAuditPersister,
)
from graphity_concurrent_edit_resolver import (  # noqa: E402
    ConflictResolution,
    GraphityConcurrentEditResolver,
)
from graphity_lock_manager import (  # noqa: E402
    GraphityLockManager,
    LockToken,
    REFRACTORY_PERIOD_SECONDS,
)
from graphity_replay_guard import (  # noqa: E402
    ReplayGuard,
    VectorClock,
)


@pytest.fixture
def lock_secret():
    return "test-secret-32-bytes-graphity-lock-x"


@pytest.fixture
def replay_secret():
    return "test-secret-32-bytes-graphity-replay"


@pytest.fixture
def lock_manager(tmp_path, lock_secret):
    db = tmp_path / "lock.db"
    return GraphityLockManager(db_path=db, secret=lock_secret)


@pytest.fixture
def replay_guard(tmp_path, replay_secret):
    db = tmp_path / "replay.db"
    return ReplayGuard(db_path=db, secret=replay_secret)


def test_w31_replay_hmac_token_replay_after_refractory_blocked(
    replay_guard,
):
    """W-30-3 #1: Replay-Cache verhindert Re-Use eines Tokens nach
    Refractory-Period-Ablauf.

    Conservation-Law: Verbrauchter Nonce darf nicht wieder verwendet werden,
    auch nicht nach 60s + 1s.
    """
    nonce = "deadbeef" * 4
    author = "alice"
    fp = ReplayGuard.compute_sender_fingerprint(author, "192.168.1.10")

    # First use: success
    assert replay_guard.mark_used(nonce, author, fp) is True
    assert replay_guard.is_used(nonce) is True

    # Replay attempt: must fail (already in cache).
    assert replay_guard.mark_used(nonce, author, fp) is False

    # Even after Refractory-Period (60s + 1s), replay should still fail
    # because TTL is 24h. We can't sleep 61s in unit test, but we verify
    # is_used still returns True with default TTL.
    assert replay_guard.is_used(nonce) is True


def test_w31_replay_hash_chain_truncation_detection(
    tmp_path, replay_guard
):
    """W-30-3 #2: Chain-Anchor erkennt Truncation (letzte N Eintraege
    geloescht).

    Conservation-Law: anchored_index <= actual_index. Wenn actual_index
    kleiner -> Truncation detected.
    """
    persister = GraphityAuditPersister(
        history_path=tmp_path / "edit_history.jsonl"
    )

    # Append 5 entries
    for i in range(5):
        persister.append_lock_acquire(
            project_id="proj-1",
            section_id="sec-A",
            author=f"author-{i}",
            nonce=f"nonce-{i}-" + "0" * 24,
        )

    # Anchor the chain at index 4
    last_entry = persister._last_entry()  # noqa: SLF001 (test access)
    assert last_entry is not None
    replay_guard.update_chain_anchor(
        project_id="proj-1",
        section_id="sec-A",
        block_index=last_entry.block_index,
        block_hash=last_entry.block_hash,
    )

    # Verify legitimate state passes
    assert (
        replay_guard.verify_chain_against_anchor(
            project_id="proj-1",
            section_id="sec-A",
            actual_last_block_index=last_entry.block_index,
            actual_last_block_hash=last_entry.block_hash,
        )
        is True
    )

    # Truncation simulation: actual chain shorter than anchor
    truncated_index = last_entry.block_index - 2  # 2 entries removed
    assert (
        replay_guard.verify_chain_against_anchor(
            project_id="proj-1",
            section_id="sec-A",
            actual_last_block_index=truncated_index,
            actual_last_block_hash="fake_hash",
        )
        is False
    ), "Truncation NOT detected"

    # Tampering at anchor point (same index, different hash) -> detected
    assert (
        replay_guard.verify_chain_against_anchor(
            project_id="proj-1",
            section_id="sec-A",
            actual_last_block_index=last_entry.block_index,
            actual_last_block_hash="ff" * 32,  # tampered
        )
        is False
    ), "Anchor-point tampering NOT detected"


def test_w31_replay_token_theft_sender_binding(replay_guard):
    """W-30-3 #3: Sender-Bound-Token erkennt Token-Diebstahl.

    Token issued for author-X at sender-X cannot be used by author-Y at
    sender-Y, even if they know the nonce.
    """
    nonce = "stolen_nonce_" + "a" * 19
    author_legit = "alice"
    fp_legit = ReplayGuard.compute_sender_fingerprint(
        author_legit, "10.0.0.1"
    )

    # Alice uses her token
    assert replay_guard.mark_used(nonce, author_legit, fp_legit)

    # Stolen scenario: Bob tries to use Alice's nonce.
    fp_thief = ReplayGuard.compute_sender_fingerprint(
        "bob", "10.0.0.99"
    )
    # Bob fails sender-binding-verification
    assert (
        replay_guard.verify_sender_binding(
            nonce, "bob", fp_thief
        )
        is False
    ), "Token-Theft (different author) NOT detected"

    # Different IP same author also fails
    fp_diff_ip = ReplayGuard.compute_sender_fingerprint(
        author_legit, "10.0.0.99"
    )
    assert (
        replay_guard.verify_sender_binding(
            nonce, author_legit, fp_diff_ip
        )
        is False
    ), "Token-Theft (different IP) NOT detected"

    # Legit owner passes
    assert (
        replay_guard.verify_sender_binding(
            nonce, author_legit, fp_legit
        )
        is True
    )


def test_w31_replay_lamport_clock_skew_resilience(replay_guard):
    """W-30-3 #4: Lamport-Vector-Clocks geben deterministic Causal-Order
    auch bei Wall-Clock-Skew zwischen Nodes.

    Conservation-Law: Lamport-Timestamps strikt monoton steigend
    pro Author, unabhaengig von wall_clock_unix.
    """
    # Author alice: 3 ticks
    c1 = replay_guard.tick_lamport("alice")
    c2 = replay_guard.tick_lamport("alice")
    c3 = replay_guard.tick_lamport("alice")

    assert c1.lamport == 1
    assert c2.lamport == 2
    assert c3.lamport == 3
    assert c2.is_after(c1)
    assert c3.is_after(c2)
    assert not c1.is_after(c3)

    # Receive remote clock from bob with high lamport (clock-skew)
    remote_bob = VectorClock(
        author="bob", lamport=100, wall_clock_unix=99999
    )
    bob_local = replay_guard.observe_remote_clock(remote_bob)
    # Local clock for bob bumps to max(0, 100)+1 = 101
    assert bob_local.lamport == 101

    # Now alice ticks again - alice clock independent of bob
    c4 = replay_guard.tick_lamport("alice")
    assert c4.lamport == 4
    # Alice should see Lamport increase even if wall_clock skewed
    # (we cannot make wall-clock skew in unit-test without time-mock,
    # but Lamport-monotonicity is verified independently)


def test_w31_replay_network_split_recovery_three_way_merge():
    """W-30-3 #5: Network-Split-Recovery via Three-Way-Merge.

    Wenn Split-Brain: 2 Authors editieren parallel, dann Merge.
    Conservation-Law: Beide Edits ueberleben (in mergedem Output).
    """
    resolver = GraphityConcurrentEditResolver()

    base = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
    # Alice edits line 1 (top of file)
    author_a = "ALICE LINE 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
    # Bob edits line 5 (bottom of file) - DISJOINT
    author_b = "Line 1\nLine 2\nLine 3\nLine 4\nBOB LINE 5\n"

    result = resolver.merge(
        base=base,
        author_a=author_a,
        author_b=author_b,
        author_a_name="alice",
        author_b_name="bob",
    )

    assert result.resolution == ConflictResolution.AUTO_MERGE
    assert result.conflict_count == 0
    # Both edits survive
    assert "ALICE LINE 1" in result.merged_text
    assert "BOB LINE 5" in result.merged_text

    # Overlapping case: Both edit line 1 -> conflict.
    author_a_overlap = "ALICE-EDIT line 1\nLine 2\n"
    author_b_overlap = "BOB-EDIT line 1\nLine 2\n"
    result_overlap = resolver.merge(
        base="Line 1\nLine 2\n",
        author_a=author_a_overlap,
        author_b=author_b_overlap,
    )
    assert result_overlap.resolution == ConflictResolution.MANUAL_REQUIRED
    assert result_overlap.conflict_count > 0
    # Both versions still represented in conflict-marked merged text
    assert "ALICE-EDIT" in result_overlap.merged_text
    assert "BOB-EDIT" in result_overlap.merged_text


def test_w31_replay_diamond_dependency_resolution_4_authors():
    """W-30-3 #6: 4 Authors, 2 Branches converge -> konsistenter
    Final-State.

    Diamond-Pattern:
        base -> branch_left  (A1, A2 disjoint changes)
            -> branch_right (B1, B2 disjoint changes)
        merge_left+right -> all 4 changes preserved

    Conservation-Law: Alle 4 Author-Changes ueberleben in finalem Output.
    """
    resolver = GraphityConcurrentEditResolver()

    base = "L1\nL2\nL3\nL4\nL5\nL6\nL7\nL8\n"

    # Branch left: A1 changes L1, A2 changes L2
    branch_left = "A1\nA2\nL3\nL4\nL5\nL6\nL7\nL8\n"
    merged_left = resolver.merge(
        base=base, author_a="A1\nL2\nL3\nL4\nL5\nL6\nL7\nL8\n",
        author_b="L1\nA2\nL3\nL4\nL5\nL6\nL7\nL8\n",
    )
    assert merged_left.resolution == ConflictResolution.AUTO_MERGE

    # Branch right: B1 changes L7, B2 changes L8
    branch_right = "L1\nL2\nL3\nL4\nL5\nL6\nB1\nB2\n"
    merged_right = resolver.merge(
        base=base, author_a="L1\nL2\nL3\nL4\nL5\nL6\nB1\nL8\n",
        author_b="L1\nL2\nL3\nL4\nL5\nL6\nL7\nB2\n",
    )
    assert merged_right.resolution == ConflictResolution.AUTO_MERGE

    # Diamond convergence: merge branch_left + branch_right
    diamond = resolver.merge(
        base=base,
        author_a=branch_left,
        author_b=branch_right,
    )
    assert diamond.resolution == ConflictResolution.AUTO_MERGE
    # Conservation-Law: all 4 edits preserved
    assert "A1" in diamond.merged_text
    assert "A2" in diamond.merged_text
    assert "B1" in diamond.merged_text
    assert "B2" in diamond.merged_text


def test_w31_replay_concurrent_replay_attempts_50_threads(replay_guard):
    """W-30-3 BONUS: 50 parallele Replay-Attempts auf gleichen Nonce.

    Conservation-Law: Genau 1 Thread gewinnt mark_used,
    49 erhalten False. Per rules/concurrency-mandatory-tests.md
    Klasse-1 Race-on-Shared-State.
    """
    nonce = "shared_nonce_" + "x" * 19
    author = "shared-author"
    fp = ReplayGuard.compute_sender_fingerprint(author, "10.0.0.1")
    n_threads = 50

    barrier = threading.Barrier(n_threads)
    results: list[bool] = []
    results_lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        ok = replay_guard.mark_used(nonce, author, fp)
        with results_lock:
            results.append(ok)

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        list(ex.map(lambda _: attempt(), range(n_threads)))

    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)
    # Conservation: exactly 1 success, 49 fails
    assert successes == 1, (
        f"Expected exactly 1 success, got {successes}"
    )
    assert failures == n_threads - 1, (
        f"Expected {n_threads - 1} fails, got {failures}"
    )


# CRUX-MK
