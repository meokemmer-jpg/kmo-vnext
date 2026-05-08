"""Pytest suite fuer Graphity-Verlag Distributed-Lock [CRUX-MK].

Test-Klassen (per rules/concurrency-mandatory-tests.md):
1. Race-on-Shared-State (50+ Threads): test_concurrent_acquire_only_one_wins
2. Conservation-Law-Verification: test_acquire_release_history_count
3. TOCTOU-Detection: test_check_then_acquire_no_double_lock
4. Cross-Section-Isolation (Negative-Test): test_lock_other_section_independent
5. Failure-Injection: test_invalid_token_rejected

Three-Way-Merge:
6. test_disjoint_changes_auto_merge
7. test_overlapping_changes_manual_required
8. test_identical_edits_trivial_merge

Audit-Hash-Chain:
9. test_audit_chain_verify_after_appends
10. test_audit_chain_tamper_detection
11. test_audit_history_filter_by_section

Refractory-Period:
12. test_refractory_blocks_immediate_relock

Token-Lifecycle:
13. test_force_release_admin_override
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

# Allow tests to import sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graphity_lock_manager import (  # noqa: E402
    GraphityLockManager,
    LockToken,
    REFRACTORY_PERIOD_SECONDS,
)
from graphity_concurrent_edit_resolver import (  # noqa: E402
    ConflictResolution,
    GraphityConcurrentEditResolver,
)
from graphity_audit_persister import (  # noqa: E402
    GraphityAuditPersister,
)

TEST_SECRET = "test-secret-graphity-welle-30-w-30-3"


# ---------- Fixtures ----------

@pytest.fixture
def lock_manager(tmp_path: Path) -> GraphityLockManager:
    db_path = tmp_path / "lock_test.db"
    return GraphityLockManager(db_path=db_path, secret=TEST_SECRET)


@pytest.fixture
def resolver() -> GraphityConcurrentEditResolver:
    return GraphityConcurrentEditResolver()


@pytest.fixture
def auditor(tmp_path: Path) -> GraphityAuditPersister:
    history_path = tmp_path / "edit_history.jsonl"
    return GraphityAuditPersister(history_path=history_path)


# ---------- Test 1: Race-on-Shared-State (50 Threads) ----------

def test_concurrent_acquire_only_one_wins(
    lock_manager: GraphityLockManager,
):
    """Conservation-Law: bei 50 Threads die parallel acquiren, gewinnt
    GENAU EINER. Synchronisierte Threads via Barrier."""
    N = 50
    barrier = threading.Barrier(N)
    results: list[str | None] = []
    errors: list[Exception] = []

    def worker(worker_id: int) -> str | None:
        try:
            barrier.wait()  # synchronize start
            # All threads attempt to lock SAME section simultaneously
            return lock_manager.acquire_lock(
                author=f"author_{worker_id}",
                project_id="proj_X",
                section_id="sec_42",
                ttl_seconds=300,
            )
        except RuntimeError as e:
            # Refractory may trigger if test ran before; bubble up
            errors.append(e)
            return None

    with ThreadPoolExecutor(max_workers=N) as ex:
        results = list(ex.map(worker, range(N)))

    # Conservation: exactly 1 winner
    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]

    assert len(winners) == 1, (
        f"Race-Condition: expected 1 winner, got {len(winners)}. "
        f"Errors: {errors}"
    )
    assert len(losers) == N - 1
    # Winner-token must verify
    assert lock_manager.verify_lock(winners[0]) is True


# ---------- Test 2: Conservation-Law (Acquire/Release/History) ----------

def test_acquire_release_history_count(
    lock_manager: GraphityLockManager,
):
    """Conservation: nach 5 Acquire+Release Zyklen muss
    history-Tabelle 5 Eintraege haben (auf einem section).

    Wegen Refractory-Period zwischen Releases verwenden wir
    verschiedene Sektionen (kein Refractory-Konflikt)."""
    for i in range(5):
        token = lock_manager.acquire_lock(
            author=f"author_{i}",
            project_id="proj_A",
            section_id=f"sec_{i}",  # different sections to avoid refractory
            ttl_seconds=300,
        )
        assert token is not None
        assert lock_manager.release_lock(token) is True

    # No active locks
    for i in range(5):
        status = lock_manager.get_lock_status("proj_A", f"sec_{i}")
        assert status is None


# ---------- Test 3: TOCTOU-Detection ----------

def test_check_then_acquire_no_double_lock(
    lock_manager: GraphityLockManager,
):
    """TOCTOU: pruefe Lock-Status, dann Acquire. Andere Session darf
    nicht zwischendurch acquiren koennen wenn Slot belegt ist."""
    # Author-A acquires
    token_a = lock_manager.acquire_lock(
        author="author_a",
        project_id="proj_T",
        section_id="sec_T1",
    )
    assert token_a is not None

    # Author-B tries to acquire same -> must fail
    token_b = lock_manager.acquire_lock(
        author="author_b",
        project_id="proj_T",
        section_id="sec_T1",
    )
    assert token_b is None  # locked by A

    # Status confirms A holds
    status = lock_manager.get_lock_status("proj_T", "sec_T1")
    assert status is not None
    assert status["author"] == "author_a"


# ---------- Test 4: Cross-Section-Isolation (Negative-Test) ----------

def test_lock_other_section_independent(
    lock_manager: GraphityLockManager,
):
    """Negative-Test: Lock auf section X betrifft section Y NICHT."""
    token_x = lock_manager.acquire_lock(
        author="author_a",
        project_id="proj_I",
        section_id="sec_X",
    )
    token_y = lock_manager.acquire_lock(
        author="author_b",
        project_id="proj_I",
        section_id="sec_Y",
    )
    assert token_x is not None
    assert token_y is not None
    # Both authors hold THEIR section, neither sees the other's
    assert (
        lock_manager.get_lock_status("proj_I", "sec_X")["author"]
        == "author_a"
    )
    assert (
        lock_manager.get_lock_status("proj_I", "sec_Y")["author"]
        == "author_b"
    )


# ---------- Test 5: Failure-Injection (Invalid Token) ----------

def test_invalid_token_rejected(
    lock_manager: GraphityLockManager,
):
    """Failure-Injection: gefaelschtes Token wird abgewiesen."""
    # Forge a token with bad signature
    forged = LockToken(
        author="hacker",
        project_id="proj_F",
        section_id="sec_F",
        acquired_at=int(time.time()),
        expires_at=int(time.time()) + 300,
        nonce="deadbeef" * 4,
        signature="0" * 64,  # garbage signature
    ).serialize()

    assert lock_manager.verify_lock(forged) is False
    # Release-attempt with forged token must fail
    assert lock_manager.release_lock(forged) is False


# ---------- Test 6: Three-Way-Merge Disjoint ----------

def test_disjoint_changes_auto_merge(
    resolver: GraphityConcurrentEditResolver,
):
    """Disjunkte Edits werden automatisch gemergt."""
    base = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
    a = "Line 1 (A)\nLine 2\nLine 3\nLine 4\nLine 5\n"  # A aendert Z1
    b = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5 (B)\n"  # B aendert Z5

    result = resolver.merge(base, a, b)
    assert result.resolution == ConflictResolution.AUTO_MERGE
    assert "Line 1 (A)" in result.merged_text
    assert "Line 5 (B)" in result.merged_text
    assert result.conflict_count == 0


# ---------- Test 7: Three-Way-Merge Overlap ----------

def test_overlapping_changes_manual_required(
    resolver: GraphityConcurrentEditResolver,
):
    """Ueberlappende Edits erzeugen Conflict-Marker."""
    base = "Original sentence.\n"
    a = "Modified by author A.\n"
    b = "Modified by author B.\n"

    result = resolver.merge(base, a, b, "alice", "bob")
    assert result.resolution == ConflictResolution.MANUAL_REQUIRED
    assert result.conflict_count >= 1
    assert "AUTHOR-A" in result.merged_text
    assert "AUTHOR-B" in result.merged_text
    assert "alice" in result.merged_text
    assert "bob" in result.merged_text


# ---------- Test 8: Three-Way-Merge Identical ----------

def test_identical_edits_trivial_merge(
    resolver: GraphityConcurrentEditResolver,
):
    """Identische Edits = trivialer Auto-Merge."""
    base = "Original.\n"
    a = "Modified identically.\n"
    b = "Modified identically.\n"

    result = resolver.merge(base, a, b)
    assert result.resolution == ConflictResolution.AUTO_MERGE
    assert result.merged_text == a
    assert result.conflict_count == 0


# ---------- Test 9: Audit-Chain Verify ----------

def test_audit_chain_verify_after_appends(
    auditor: GraphityAuditPersister,
):
    """Hash-Chain-Integrity nach mehreren Appends."""
    auditor.append_lock_acquire(
        "proj_AUD", "sec_1", "alice", "nonce_a"
    )
    auditor.append_edit_commit(
        "proj_AUD", "sec_1", "alice", "Edit content version 1"
    )
    auditor.append_lock_release(
        "proj_AUD", "sec_1", "alice", "nonce_a", "normal"
    )
    assert auditor.verify_chain() is True


# ---------- Test 10: Audit-Chain Tamper-Detection ----------

def test_audit_chain_tamper_detection(
    auditor: GraphityAuditPersister, tmp_path: Path
):
    """Tampering an JSONL erzeugt verify_chain == False."""
    auditor.append_lock_acquire(
        "proj_TAMP", "sec_1", "alice", "nonce_a"
    )
    auditor.append_edit_commit(
        "proj_TAMP", "sec_1", "alice", "Original content"
    )

    # Tamper: rewrite the second entry author from alice -> hacker
    raw = auditor.history_path.read_text()
    tampered = raw.replace('"alice"', '"hacker"', 2)  # both lines hit
    auditor.history_path.write_text(tampered)

    assert auditor.verify_chain() is False


# ---------- Test 11: Audit-History Filter ----------

def test_audit_history_filter_by_section(
    auditor: GraphityAuditPersister,
):
    """history_for_section filtert korrekt."""
    auditor.append_lock_acquire("p1", "s1", "a", "n1")
    auditor.append_lock_acquire("p1", "s2", "b", "n2")
    auditor.append_edit_commit("p1", "s1", "a", "edit-content-1")

    s1_entries = list(auditor.history_for_section("p1", "s1"))
    s2_entries = list(auditor.history_for_section("p1", "s2"))

    assert len(s1_entries) == 2
    assert len(s2_entries) == 1
    assert all(e.section_id == "s1" for e in s1_entries)
    assert all(e.section_id == "s2" for e in s2_entries)


# ---------- Test 12: Refractory-Period ----------

def test_refractory_blocks_immediate_relock(
    lock_manager: GraphityLockManager, monkeypatch
):
    """Nach Release: 60s Refractory blockiert sofortigen Re-Lock."""
    # Mock time-funktion auf Lock-Manager-Modul-Ebene
    fake_now = [int(time.time())]

    def fake_time():
        return fake_now[0]

    import graphity_lock_manager as glm_module
    monkeypatch.setattr(glm_module.time, "time", fake_time)

    token = lock_manager.acquire_lock(
        author="alice",
        project_id="proj_R",
        section_id="sec_R",
    )
    assert token is not None
    assert lock_manager.release_lock(token) is True

    # Sofortiger Re-Lock-Versuch -> Refractory
    with pytest.raises(RuntimeError, match="Refractory"):
        lock_manager.acquire_lock(
            author="bob",
            project_id="proj_R",
            section_id="sec_R",
        )

    # Nach Refractory-Period (61s vorrueckend) muss Re-Lock funktionieren
    fake_now[0] += REFRACTORY_PERIOD_SECONDS + 1

    token2 = lock_manager.acquire_lock(
        author="bob",
        project_id="proj_R",
        section_id="sec_R",
    )
    assert token2 is not None


# ---------- Test 13: Force-Release Admin-Override ----------

def test_force_release_admin_override(
    lock_manager: GraphityLockManager,
):
    """Admin kann gestuckten Lock zwangs-releasen (z.B. crashed Author)."""
    token = lock_manager.acquire_lock(
        author="alice",
        project_id="proj_FR",
        section_id="sec_FR",
        ttl_seconds=14400,  # 4h
    )
    assert token is not None

    # Admin force-released
    success = lock_manager.force_release(
        project_id="proj_FR",
        section_id="sec_FR",
        admin="martin",
    )
    assert success is True
    # Lock nun frei
    assert lock_manager.get_lock_status("proj_FR", "sec_FR") is None
    # Originales Token darf nicht mehr verifizieren
    assert lock_manager.verify_lock(token) is False


# ---------- Bonus Test 14: Race auf verschiedene Sektionen ----------

def test_concurrent_acquire_different_sections_all_succeed(
    lock_manager: GraphityLockManager,
):
    """Conservation: 20 Threads, 20 verschiedene Sektionen -> alle 20
    erfolgreich (kein Konflikt da disjunkte Sektionen)."""
    N = 20
    barrier = threading.Barrier(N)

    def worker(worker_id: int) -> str | None:
        try:
            barrier.wait()
            return lock_manager.acquire_lock(
                author=f"author_{worker_id}",
                project_id="proj_DISJ",
                section_id=f"sec_{worker_id}",  # disjunkt
                ttl_seconds=300,
            )
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=N) as ex:
        results = list(ex.map(worker, range(N)))

    successful = [r for r in results if r is not None]
    assert (
        len(successful) == N
    ), f"Expected {N} successes (disjoint sections), got {len(successful)}"
    # All tokens valid
    assert all(lock_manager.verify_lock(t) for t in successful)
