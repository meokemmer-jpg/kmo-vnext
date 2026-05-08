# [CRUX-MK]
"""Tests fuer Graphity-Distributed-Edit-Lock (Welle-30 Phase-23 Wild-Code-Blindtest 3/3).

Pflicht-Coverage:
- Init-Validation (TTL/Sweep > 0)
- Acquire (free / held / expired-auto-release)
- Renew (extend / invalid-token / expired-before-renew)
- Release (valid-token / invalid-token)
- Force-Release (Admin-Override)
- Scope-Independence (CHAPTER vs PARAGRAPH same chapter)
- Chapter-Independence (book_a chap_1 vs book_a chap_2)
- is_held / get_state
- sweep_expired
- list_active / list_active_for_book
- Concurrent 50-Threads (Barrier + only-one-acquires)
- Frozen-Dataclass (FrozenInstanceError)
"""

from __future__ import annotations

import dataclasses
import threading
import time
import unittest

from kmo_governance.graphity_distributed_lock import (
    EditLease,
    EditLockResult,
    EditLockState,
    EditScope,
    GraphityDistributedEditLock,
)


class TestInitValidation(unittest.TestCase):
    """Init muss TTL/Sweep > 0 erzwingen."""

    def test_init_validation(self) -> None:
        # default funktioniert
        mgr = GraphityDistributedEditLock()
        self.assertIsNotNone(mgr)

        # default_ttl_s <= 0 -> ValueError
        with self.assertRaises(ValueError):
            GraphityDistributedEditLock(default_ttl_s=0)
        with self.assertRaises(ValueError):
            GraphityDistributedEditLock(default_ttl_s=-1.0)

        # sweep_interval_s <= 0 -> ValueError
        with self.assertRaises(ValueError):
            GraphityDistributedEditLock(sweep_interval_s=0)
        with self.assertRaises(ValueError):
            GraphityDistributedEditLock(sweep_interval_s=-1.0)


class TestAcquire(unittest.TestCase):
    """Acquire-Operationen."""

    def test_acquire_free_chapter_lock(self) -> None:
        mgr = GraphityDistributedEditLock()
        r = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r.success)
        self.assertEqual(r.book_id, "test_book_a")
        self.assertEqual(r.chapter_id, "test_chapter_1")
        self.assertEqual(r.scope, EditScope.CHAPTER)
        self.assertEqual(r.reason, "acquired")
        self.assertIsNotNone(r.lease)
        self.assertEqual(r.lease.holder_author_id, "test_author_1")
        self.assertTrue(r.lease.lease_token)
        self.assertGreater(r.lease.expires_at, r.lease.acquired_at)
        self.assertIsNone(r.conflict_holder)

    def test_acquire_held_returns_conflict(self) -> None:
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)

        r2 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_2"
        )
        self.assertFalse(r2.success)
        self.assertEqual(r2.conflict_holder, "test_author_1")
        self.assertIn("test_author_1", r2.reason)
        self.assertIsNone(r2.lease)

    def test_acquire_expired_auto_release(self) -> None:
        """TTL=0.05 + sleep(0.1) -> Reacquire muss success=True liefern."""
        mgr = GraphityDistributedEditLock(default_ttl_s=0.05)
        r1 = mgr.acquire(
            "test_book_a",
            "test_chapter_1",
            EditScope.CHAPTER,
            "test_author_1",
            ttl_s=0.05,
        )
        self.assertTrue(r1.success)

        time.sleep(0.1)

        # Reacquire by another author - sollte gelingen wegen Auto-Release
        r2 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_2"
        )
        self.assertTrue(r2.success)
        self.assertEqual(r2.lease.holder_author_id, "test_author_2")
        self.assertNotEqual(r2.lease.lease_token, r1.lease.lease_token)

    def test_acquire_validates_inputs(self) -> None:
        mgr = GraphityDistributedEditLock()
        # empty book_id
        with self.assertRaises(ValueError):
            mgr.acquire("", "test_chapter_1", EditScope.CHAPTER, "test_author_1")
        # empty chapter_id
        with self.assertRaises(ValueError):
            mgr.acquire("test_book_a", "", EditScope.CHAPTER, "test_author_1")
        # falscher scope-type
        with self.assertRaises(ValueError):
            mgr.acquire("test_book_a", "test_chapter_1", "chapter", "test_author_1")  # type: ignore[arg-type]
        # empty holder_author_id
        with self.assertRaises(ValueError):
            mgr.acquire("test_book_a", "test_chapter_1", EditScope.CHAPTER, "")
        # ttl_s <= 0
        with self.assertRaises(ValueError):
            mgr.acquire(
                "test_book_a",
                "test_chapter_1",
                EditScope.CHAPTER,
                "test_author_1",
                ttl_s=0,
            )


class TestRenew(unittest.TestCase):
    """Renew-Operationen."""

    def test_renew_extends(self) -> None:
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a",
            "test_chapter_1",
            EditScope.CHAPTER,
            "test_author_1",
            ttl_s=10.0,
        )
        self.assertTrue(r1.success)
        original_expires = r1.lease.expires_at
        original_token = r1.lease.lease_token
        original_acquired_at = r1.lease.acquired_at

        time.sleep(0.01)
        r2 = mgr.renew(
            "test_book_a",
            "test_chapter_1",
            EditScope.CHAPTER,
            r1.lease.lease_token,
            additional_ttl_s=20.0,
        )
        self.assertTrue(r2.success)
        self.assertGreater(r2.lease.expires_at, original_expires)
        # Token und acquired_at bleiben preserved
        self.assertEqual(r2.lease.lease_token, original_token)
        self.assertEqual(r2.lease.acquired_at, original_acquired_at)
        self.assertEqual(r2.lease.ttl_s, 20.0)

    def test_renew_invalid_token(self) -> None:
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)

        r2 = mgr.renew(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "fake_token_xyz"
        )
        self.assertFalse(r2.success)
        self.assertIn("invalid lease_token", r2.reason)
        self.assertEqual(r2.conflict_holder, "test_author_1")

    def test_renew_lock_not_found(self) -> None:
        mgr = GraphityDistributedEditLock()
        r = mgr.renew(
            "test_book_x", "test_chapter_x", EditScope.CHAPTER, "any_token"
        )
        self.assertFalse(r.success)
        self.assertEqual(r.reason, "lock not found")


class TestRelease(unittest.TestCase):
    """Release-Operationen."""

    def test_release_valid_token(self) -> None:
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)

        r2 = mgr.release(
            "test_book_a",
            "test_chapter_1",
            EditScope.CHAPTER,
            r1.lease.lease_token,
        )
        self.assertTrue(r2.success)
        self.assertEqual(r2.reason, "released")

        # Nach Release ist Lock FREE
        self.assertEqual(
            mgr.get_state("test_book_a", "test_chapter_1", EditScope.CHAPTER),
            EditLockState.FREE,
        )

    def test_release_invalid_token(self) -> None:
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)

        r2 = mgr.release(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "fake_token_xyz"
        )
        self.assertFalse(r2.success)
        self.assertIn("invalid lease_token", r2.reason)
        self.assertEqual(r2.conflict_holder, "test_author_1")

        # Lock haelt nach Failed-Release
        self.assertTrue(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.CHAPTER)
        )


class TestForceRelease(unittest.TestCase):
    """Admin-Override (force_release ohne Token)."""

    def test_force_release(self) -> None:
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)

        r2 = mgr.force_release(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER
        )
        self.assertTrue(r2.success)
        self.assertIn("force-released", r2.reason)
        self.assertIn("test_author_1", r2.reason)

        self.assertEqual(
            mgr.get_state("test_book_a", "test_chapter_1", EditScope.CHAPTER),
            EditLockState.FREE,
        )

    def test_force_release_not_found(self) -> None:
        mgr = GraphityDistributedEditLock()
        r = mgr.force_release(
            "test_book_x", "test_chapter_x", EditScope.CHAPTER
        )
        self.assertFalse(r.success)
        self.assertEqual(r.reason, "lock not found")


class TestScopeIndependence(unittest.TestCase):
    """Verschiedene Scopes auf gleichem Chapter sind unabhaengig."""

    def test_different_scopes_independent(self) -> None:
        """CHAPTER und PARAGRAPH auf gleichem Chapter koennen parallel gehalten werden."""
        mgr = GraphityDistributedEditLock()
        r_chapter = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        r_paragraph = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.PARAGRAPH, "test_author_2"
        )
        self.assertTrue(r_chapter.success)
        self.assertTrue(r_paragraph.success)
        self.assertNotEqual(
            r_chapter.lease.lease_token, r_paragraph.lease.lease_token
        )

        # Beide Scopes individuell pruefbar
        self.assertTrue(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.CHAPTER)
        )
        self.assertTrue(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.PARAGRAPH)
        )
        # SECTION ist immer noch frei
        self.assertFalse(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.SECTION)
        )

    def test_all_four_scopes_independent(self) -> None:
        """Alle 4 Scopes auf gleichem Chapter sind unabhaengig."""
        mgr = GraphityDistributedEditLock()
        for i, scope in enumerate(
            [
                EditScope.CHAPTER,
                EditScope.SECTION,
                EditScope.PARAGRAPH,
                EditScope.ANNOTATION,
            ]
        ):
            r = mgr.acquire(
                "test_book_a", "test_chapter_1", scope, f"test_author_{i + 1}"
            )
            self.assertTrue(r.success, f"scope={scope} should acquire")
        self.assertEqual(len(mgr.list_active()), 4)


class TestChapterAndBookIndependence(unittest.TestCase):
    """Verschiedene Chapters/Books sind unabhaengig."""

    def test_different_chapters_independent(self) -> None:
        """book_a/chap_1 und book_a/chap_2 sind unabhaengig."""
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        r2 = mgr.acquire(
            "test_book_a", "test_chapter_2", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)
        self.assertNotEqual(r1.lease.lease_token, r2.lease.lease_token)

    def test_different_books_independent(self) -> None:
        """book_a und book_b mit gleicher chapter_id/scope sind unabhaengig."""
        mgr = GraphityDistributedEditLock()
        r1 = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        r2 = mgr.acquire(
            "test_book_b", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)


class TestInspection(unittest.TestCase):
    """is_held / get_state / sweep_expired / list_active."""

    def test_is_held(self) -> None:
        mgr = GraphityDistributedEditLock()
        self.assertFalse(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.CHAPTER)
        )

        r = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.CHAPTER)
        )

        mgr.release(
            "test_book_a",
            "test_chapter_1",
            EditScope.CHAPTER,
            r.lease.lease_token,
        )
        self.assertFalse(
            mgr.is_held("test_book_a", "test_chapter_1", EditScope.CHAPTER)
        )

    def test_get_state(self) -> None:
        mgr = GraphityDistributedEditLock(default_ttl_s=0.05)

        # FREE
        self.assertEqual(
            mgr.get_state("test_book_a", "test_chapter_1", EditScope.CHAPTER),
            EditLockState.FREE,
        )

        # LOCKED
        r = mgr.acquire(
            "test_book_a",
            "test_chapter_1",
            EditScope.CHAPTER,
            "test_author_1",
            ttl_s=0.05,
        )
        self.assertEqual(
            mgr.get_state("test_book_a", "test_chapter_1", EditScope.CHAPTER),
            EditLockState.LOCKED,
        )

        # EXPIRED (nach TTL-Ablauf)
        time.sleep(0.1)
        self.assertEqual(
            mgr.get_state("test_book_a", "test_chapter_1", EditScope.CHAPTER),
            EditLockState.EXPIRED,
        )

        # Sweep -> FREE
        mgr.sweep_expired()
        self.assertEqual(
            mgr.get_state("test_book_a", "test_chapter_1", EditScope.CHAPTER),
            EditLockState.FREE,
        )

    def test_sweep_expired(self) -> None:
        mgr = GraphityDistributedEditLock(default_ttl_s=0.05)
        # 3 Locks mit kurzer TTL
        mgr.acquire(
            "book_a", "chap_1", EditScope.CHAPTER, "author_1", ttl_s=0.05
        )
        mgr.acquire(
            "book_a", "chap_2", EditScope.CHAPTER, "author_1", ttl_s=0.05
        )
        mgr.acquire(
            "book_b", "chap_1", EditScope.CHAPTER, "author_2", ttl_s=0.05
        )
        # 1 Lock mit langer TTL
        mgr.acquire(
            "book_b", "chap_2", EditScope.CHAPTER, "author_2", ttl_s=100.0
        )

        time.sleep(0.1)
        purged = mgr.sweep_expired()
        self.assertEqual(purged, 3)
        self.assertEqual(len(mgr.list_active()), 1)

    def test_list_active(self) -> None:
        mgr = GraphityDistributedEditLock(default_ttl_s=0.05)
        # 1 expired + 2 active
        mgr.acquire(
            "book_a", "chap_1", EditScope.CHAPTER, "author_1", ttl_s=0.05
        )
        time.sleep(0.1)
        mgr.acquire(
            "book_a", "chap_2", EditScope.CHAPTER, "author_1", ttl_s=10.0
        )
        mgr.acquire(
            "book_b", "chap_1", EditScope.CHAPTER, "author_2", ttl_s=10.0
        )

        active = mgr.list_active()
        # tuple, immutable
        self.assertIsInstance(active, tuple)
        # nur 2 aktiv (1 expired versteckt)
        self.assertEqual(len(active), 2)
        author_ids = sorted(lease.holder_author_id for lease in active)
        self.assertEqual(author_ids, ["author_1", "author_2"])

    def test_list_active_for_book_filters(self) -> None:
        """list_active_for_book filtert auf book_id."""
        mgr = GraphityDistributedEditLock()
        mgr.acquire("book_a", "chap_1", EditScope.CHAPTER, "author_1")
        mgr.acquire("book_a", "chap_2", EditScope.SECTION, "author_2")
        mgr.acquire("book_b", "chap_1", EditScope.CHAPTER, "author_3")
        mgr.acquire("book_c", "chap_1", EditScope.PARAGRAPH, "author_4")

        active_a = mgr.list_active_for_book("book_a")
        self.assertIsInstance(active_a, tuple)
        self.assertEqual(len(active_a), 2)
        for lease in active_a:
            self.assertEqual(lease.book_id, "book_a")

        active_b = mgr.list_active_for_book("book_b")
        self.assertEqual(len(active_b), 1)
        self.assertEqual(active_b[0].holder_author_id, "author_3")

        # nicht-existentes Book
        self.assertEqual(mgr.list_active_for_book("book_zzz"), tuple())
        # leerer book_id
        self.assertEqual(mgr.list_active_for_book(""), tuple())


class TestConcurrent(unittest.TestCase):
    """Concurrent 50-Threads -> exactly 1 erfolgreich."""

    def test_concurrent_50_threads_only_one(self) -> None:
        mgr = GraphityDistributedEditLock(default_ttl_s=10.0)
        n_threads = 50
        barrier = threading.Barrier(n_threads)
        results: list[EditLockResult] = []
        results_lock = threading.Lock()

        def worker(i: int) -> None:
            barrier.wait()
            r = mgr.acquire(
                "test_book_concurrent",
                "test_chapter_1",
                EditScope.CHAPTER,
                f"author_{i}",
            )
            with results_lock:
                results.append(r)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), n_threads - 1)
        # Alle Failures haben den gleichen conflict_holder
        winner = successes[0].lease.holder_author_id
        for f in failures:
            self.assertEqual(f.conflict_holder, winner)


class TestFrozen(unittest.TestCase):
    """Frozen-Dataclasses (FrozenInstanceError bei Mutation)."""

    def test_lease_frozen(self) -> None:
        mgr = GraphityDistributedEditLock()
        r = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        self.assertTrue(r.success)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.lease.holder_author_id = "hijacker"  # type: ignore[misc]

    def test_result_frozen(self) -> None:
        mgr = GraphityDistributedEditLock()
        r = mgr.acquire(
            "test_book_a", "test_chapter_1", EditScope.CHAPTER, "test_author_1"
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.success = False  # type: ignore[misc]


class TestMaxActiveLeases(unittest.TestCase):
    """P-V15-4: Anti-OOM Auto-Sweep + max_active_leases (Cross-LLM-V15)."""

    def test_max_active_leases_enforced(self) -> None:
        """max_active_leases voll + alle aktiv -> RuntimeError beim NEUEN acquire."""
        # Cap=3, alle Leases mit langer TTL (nicht expired)
        mgr = GraphityDistributedEditLock(
            default_ttl_s=3600.0, max_active_leases=3
        )
        # 3 disjunkte Locks belegen (full)
        r1 = mgr.acquire("book_a", "ch_1", EditScope.CHAPTER, "auth_1")
        r2 = mgr.acquire("book_a", "ch_2", EditScope.CHAPTER, "auth_2")
        r3 = mgr.acquire("book_a", "ch_3", EditScope.CHAPTER, "auth_3")
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)
        self.assertTrue(r3.success)

        # 4. acquire fuer NEUEN Lock (Cap voll, kein Expired-Lease)
        with self.assertRaises(RuntimeError) as ctx:
            mgr.acquire("book_a", "ch_4", EditScope.CHAPTER, "auth_4")
        self.assertIn("max_active_leases exceeded", str(ctx.exception))

        # Re-acquire auf existierendes (held) Lock soll weiterhin success=False
        # liefern (kein RuntimeError, nur lock-conflict).
        r_dup = mgr.acquire("book_a", "ch_1", EditScope.CHAPTER, "another_auth")
        self.assertFalse(r_dup.success)
        self.assertEqual(r_dup.conflict_holder, "auth_1")

    def test_acquire_triggers_global_sweep_when_full(self) -> None:
        """Cap voll mit expired Leases -> Auto-Sweep + neuer acquire success."""
        mgr = GraphityDistributedEditLock(
            default_ttl_s=0.05, max_active_leases=3  # 50ms TTL
        )
        # 3 Leases mit kurzer TTL
        mgr.acquire("book_a", "ch_1", EditScope.CHAPTER, "auth_1")
        mgr.acquire("book_a", "ch_2", EditScope.CHAPTER, "auth_2")
        mgr.acquire("book_a", "ch_3", EditScope.CHAPTER, "auth_3")
        self.assertEqual(len(mgr._leases), 3)

        # Warten bis alle expired sind
        time.sleep(0.10)

        # Neuer acquire mit langer TTL -> triggert Auto-Sweep -> success
        r4 = mgr.acquire(
            "book_a", "ch_4", EditScope.CHAPTER, "auth_4", ttl_s=3600.0
        )
        self.assertTrue(r4.success)
        # Auto-Sweep hat alte Leases entfernt; jetzt nur noch 1 aktive
        self.assertEqual(len(mgr._leases), 1)
        self.assertEqual(
            mgr._leases[("book_a", "ch_4", EditScope.CHAPTER)].holder_author_id,
            "auth_4",
        )


if __name__ == "__main__":
    unittest.main()

# CRUX-MK
