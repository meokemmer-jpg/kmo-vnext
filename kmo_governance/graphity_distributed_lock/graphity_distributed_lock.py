# [CRUX-MK]
"""Graphity-Distributed-Edit-Lock [CRUX-MK].

Welle-30 Phase-23 Modul: Concurrent-Edit-Lock-Coordinator fuer Buchprojekte
(TTL-Lease + Auto-Release) im Graphity-Verlag-Domain.

Bio-Aequivalent: Synaptische-Verbindung.
    Pre-Synapse        -> holder_author_id reserviert Edit-Slot (Lease)
    Post-Synapse       -> Edit-Window mit Lease-Time (lange TTL, 600s Editor-Inactivity)
    Aktivitaets-Decay  -> Auto-Release nach TTL-Ablauf (verhindert Stale-Locks bei Editor-Crash)
    Kompetition        -> Multiple Authoren kompetitieren um (book, chapter, scope)

Domain-Mapping (3-Domain-Vergleich):
    Hotel.lock_id              -> Trading.(instrument, side)         -> Verlag.(book, chapter, scope)
    Hotel.holder_id            -> Trading.holder_strategy_id          -> Verlag.holder_author_id
    Hotel.ttl_s 30.0           -> Trading.ttl_s 5.0                   -> Verlag.ttl_s 600.0
    Hotel.sweep_interval 5.0   -> Trading.sweep_interval 1.0          -> Verlag.sweep_interval 60.0

Pattern-Inspiration:
- distributed_lock_manager (Welle-21, Synaptic-Pattern, 373 LoC, Hotel-Domain)
- kpm_distributed_lock_manager (Welle-26, Synaptic-Pattern, Trading-Domain)

CRUX-Bindung:
- K_0: lease_token verhindert Edit-Hijacking durch fremde Authoren (kein VG-Wort-Verlust)
- Q_0: Auto-Release expired Leases verhindert Author-Deadlocks bei Editor-Crash
- I_min: uuid.uuid4 Token als kryptographischer Author-Owner-Beleg
- W_0: Sweep-on-Acquire (amortisierter O(1)-Cleanup bei Multi-Author-Workflow)

Usage:
    >>> mgr = GraphityDistributedEditLock(default_ttl_s=600.0)
    >>> r = mgr.acquire("symbiotic_minds", "chapter_3", EditScope.SECTION,
    ...                 "author_kemmer", ttl_s=900.0)
    >>> if r.success:
    ...     # ... edit section ...
    ...     mgr.release("symbiotic_minds", "chapter_3", EditScope.SECTION,
    ...                 r.lease.lease_token)
"""

from __future__ import annotations

import enum
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EditScope(str, enum.Enum):
    """Edit-Granularitaet: CHAPTER / SECTION / PARAGRAPH / ANNOTATION.

    Verschiedene Scopes auf gleichem (book, chapter) sind unabhaengige Locks
    (separate Synapsen). Erlaubt parallele Annotation waehrend SECTION-Edit.
    """

    CHAPTER = "chapter"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    ANNOTATION = "annotation"


class EditLockState(str, enum.Enum):
    """Lifecycle-Status eines Edit-Locks (synaptische Verbindung)."""

    FREE = "free"
    LOCKED = "locked"
    EXPIRED = "expired"
    RELEASED = "released"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EditLease:
    """TTL-Lease Beleg fuer einen Edit-Lock.

    Pre-Conditions:
        book_id non-empty.
        chapter_id non-empty.
        scope ist EditScope-Instanz (CHAPTER / SECTION / PARAGRAPH / ANNOTATION).
        holder_author_id non-empty.
        acquired_at >= 0.
        expires_at > acquired_at.
        ttl_s > 0.
        lease_token non-empty (uuid.uuid4().hex).

    Post-Conditions:
        Frozen / hashable / immutable.
    """

    book_id: str
    chapter_id: str
    scope: EditScope
    holder_author_id: str
    acquired_at: float
    expires_at: float
    ttl_s: float
    lease_token: str

    def __post_init__(self) -> None:
        if not self.book_id:
            raise ValueError("book_id must be non-empty")
        if not self.chapter_id:
            raise ValueError("chapter_id must be non-empty")
        if not isinstance(self.scope, EditScope):
            raise ValueError("scope must be an EditScope enum")
        if not self.holder_author_id:
            raise ValueError("holder_author_id must be non-empty")
        if self.acquired_at < 0:
            raise ValueError("acquired_at must be >= 0")
        if self.expires_at <= self.acquired_at:
            raise ValueError("expires_at must be > acquired_at")
        if self.ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        if not self.lease_token:
            raise ValueError("lease_token must be non-empty")

    def is_expired(self, now: Optional[float] = None) -> bool:
        """True wenn now > expires_at."""
        ts = now if now is not None else time.monotonic()
        return ts > self.expires_at


@dataclass(frozen=True)
class EditLockResult:
    """Ergebnis einer Edit-Lock-Operation (acquire/renew/release/force_release).

    Pre-Conditions:
        book_id non-empty.
        chapter_id non-empty.
        scope ist EditScope-Instanz.
        timestamp >= 0.
        reason non-empty.

    Post-Conditions:
        Frozen / immutable.
    """

    success: bool
    book_id: str
    chapter_id: str
    scope: EditScope
    timestamp: float
    reason: str
    lease: Optional[EditLease] = None
    conflict_holder: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.book_id:
            raise ValueError("book_id must be non-empty")
        if not self.chapter_id:
            raise ValueError("chapter_id must be non-empty")
        if not isinstance(self.scope, EditScope):
            raise ValueError("scope must be an EditScope enum")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")
        if not self.reason:
            raise ValueError("reason must be non-empty")


# ---------------------------------------------------------------------------
# Graphity-Distributed-Edit-Lock
# ---------------------------------------------------------------------------


class GraphityDistributedEditLock:
    """TTL-Lease basierter Distributed-Edit-Lock mit Auto-Release fuer Buchprojekte.

    Pre-Conditions:
        default_ttl_s > 0 (Verlag-Default 600.0s, 10min Editor-Inactivity-Window).
        sweep_interval_s > 0 (Default 60.0s, weniger haeufig als Trading).

    Thread-Safety:
        Alle Operationen sind serialisiert via threading.RLock.

    Lock-Key:
        (book_id, chapter_id, scope) als Tupel — verschiedene Scopes auf gleichem
        Chapter sind unabhaengige Locks. Verschiedene Chapters in gleichem Book
        sind unabhaengig. Erlaubt feingranulare Multi-Author-Workflows.

    Auto-Release-Mechanik:
        Sweep-on-Acquire: Bei jedem acquire() wird vorher der Ziel-Lock auf
        Expiry geprueft. Optional kann sweep_expired() explizit aufgerufen
        werden (z.B. via Cron oder Periodic-Worker mit sweep_interval_s).
        Stale-Locks bei Editor-Crashes werden so automatisch freigegeben.
    """

    def __init__(
        self,
        default_ttl_s: float = 600.0,
        sweep_interval_s: float = 60.0,
        max_active_leases: int = 10000,
    ) -> None:
        """Constructor.

        Pre-Conditions:
            default_ttl_s > 0.
            sweep_interval_s > 0.
            max_active_leases > 0 (P-V15-4: bounded _leases dict, default 10000).

        Post-Conditions:
            self._leases ist dict mit max_active_leases als Hard-Cap.
            acquire() triggert global sweep_expired() opportunistisch
            wenn dict-cap erreicht ist (Auto-Sweep statt OOM).
        """
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if sweep_interval_s <= 0:
            raise ValueError("sweep_interval_s must be > 0")
        if max_active_leases <= 0:
            raise ValueError("max_active_leases must be > 0")
        self._default_ttl_s = default_ttl_s
        self._sweep_interval_s = sweep_interval_s
        self._max_active_leases = int(max_active_leases)
        self._leases: dict[tuple[str, str, EditScope], EditLease] = {}
        self._lock = threading.RLock()

    # ---- Acquire / Renew / Release ----------------------------------------

    def acquire(
        self,
        book_id: str,
        chapter_id: str,
        scope: EditScope,
        holder_author_id: str,
        ttl_s: Optional[float] = None,
    ) -> EditLockResult:
        """Versuche, (book_id, chapter_id, scope) fuer holder_author_id zu reservieren.

        Auto-Release: Falls Lock expired ist, wird er vor dem Acquire-Versuch
        automatisch released (z.B. nach Editor-Crash).

        Returns:
            EditLockResult.success=True mit EditLease bei Erfolg.
            EditLockResult.success=False mit conflict_holder bei Konflikt.
        """
        if not book_id:
            raise ValueError("book_id must be non-empty")
        if not chapter_id:
            raise ValueError("chapter_id must be non-empty")
        if not isinstance(scope, EditScope):
            raise ValueError("scope must be an EditScope enum")
        if not holder_author_id:
            raise ValueError("holder_author_id must be non-empty")
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")

        key = (book_id, chapter_id, scope)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is not None:
                if existing.is_expired(now):
                    # Auto-Release expired Lease vor Reacquire
                    del self._leases[key]
                else:
                    return EditLockResult(
                        success=False,
                        book_id=book_id,
                        chapter_id=chapter_id,
                        scope=scope,
                        timestamp=now,
                        reason=f"lock held by {existing.holder_author_id}",
                        conflict_holder=existing.holder_author_id,
                    )

            # P-V15-4: Auto-Sweep bei max_active_leases-Cap.
            # Wenn key NICHT existing (also wir adden ein NEUES Slot-Element):
            # bei Cap-Erreichung opportunistisch global sweep_expired().
            # Wenn nach Sweep immer noch voll: RuntimeError.
            if key not in self._leases and len(self._leases) >= self._max_active_leases:
                # Inline-Sweep (lock haelt RLock, sweep_expired ist re-entrant).
                expired_keys = [
                    k for k, lease in self._leases.items() if lease.is_expired(now)
                ]
                for k in expired_keys:
                    del self._leases[k]
                if len(self._leases) >= self._max_active_leases:
                    raise RuntimeError(
                        f"max_active_leases exceeded "
                        f"({len(self._leases)} >= {self._max_active_leases})"
                    )

            lease = EditLease(
                book_id=book_id,
                chapter_id=chapter_id,
                scope=scope,
                holder_author_id=holder_author_id,
                acquired_at=now,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=uuid.uuid4().hex,
            )
            self._leases[key] = lease
            return EditLockResult(
                success=True,
                book_id=book_id,
                chapter_id=chapter_id,
                scope=scope,
                timestamp=now,
                reason="acquired",
                lease=lease,
            )

    def renew(
        self,
        book_id: str,
        chapter_id: str,
        scope: EditScope,
        lease_token: str,
        additional_ttl_s: Optional[float] = None,
    ) -> EditLockResult:
        """Verlaengere Lease um additional_ttl_s (oder default_ttl_s).

        Author-Workflow: bei laengerem Edit-Window (>10min) ruft Editor periodisch
        renew() auf, um Lease nicht expirieren zu lassen.
        """
        if not book_id:
            raise ValueError("book_id must be non-empty")
        if not chapter_id:
            raise ValueError("chapter_id must be non-empty")
        if not isinstance(scope, EditScope):
            raise ValueError("scope must be an EditScope enum")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")
        ttl = additional_ttl_s if additional_ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("additional_ttl_s must be > 0")

        key = (book_id, chapter_id, scope)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is None:
                return EditLockResult(
                    success=False,
                    book_id=book_id,
                    chapter_id=chapter_id,
                    scope=scope,
                    timestamp=now,
                    reason="lock not found",
                )
            if existing.lease_token != lease_token:
                return EditLockResult(
                    success=False,
                    book_id=book_id,
                    chapter_id=chapter_id,
                    scope=scope,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_author_id,
                )
            if existing.is_expired(now):
                del self._leases[key]
                return EditLockResult(
                    success=False,
                    book_id=book_id,
                    chapter_id=chapter_id,
                    scope=scope,
                    timestamp=now,
                    reason="lease expired before renew",
                )
            renewed = EditLease(
                book_id=existing.book_id,
                chapter_id=existing.chapter_id,
                scope=existing.scope,
                holder_author_id=existing.holder_author_id,
                acquired_at=existing.acquired_at,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=existing.lease_token,
            )
            self._leases[key] = renewed
            return EditLockResult(
                success=True,
                book_id=book_id,
                chapter_id=chapter_id,
                scope=scope,
                timestamp=now,
                reason="renewed",
                lease=renewed,
            )

    def release(
        self,
        book_id: str,
        chapter_id: str,
        scope: EditScope,
        lease_token: str,
    ) -> EditLockResult:
        """Token-validated Release. Nur Owner-Author mit gueltigem Token darf releasen."""
        if not book_id:
            raise ValueError("book_id must be non-empty")
        if not chapter_id:
            raise ValueError("chapter_id must be non-empty")
        if not isinstance(scope, EditScope):
            raise ValueError("scope must be an EditScope enum")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")

        key = (book_id, chapter_id, scope)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is None:
                return EditLockResult(
                    success=False,
                    book_id=book_id,
                    chapter_id=chapter_id,
                    scope=scope,
                    timestamp=now,
                    reason="lock not found",
                )
            if existing.lease_token != lease_token:
                return EditLockResult(
                    success=False,
                    book_id=book_id,
                    chapter_id=chapter_id,
                    scope=scope,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_author_id,
                )
            del self._leases[key]
            return EditLockResult(
                success=True,
                book_id=book_id,
                chapter_id=chapter_id,
                scope=scope,
                timestamp=now,
                reason="released",
            )

    def force_release(
        self,
        book_id: str,
        chapter_id: str,
        scope: EditScope,
    ) -> EditLockResult:
        """Admin-Override: Release ohne Token-Validation.

        Use-Case: Chefredakteur forciert Lock-Release bei Author-Abwesenheit
        (z.B. Krankheit, Editor-Hang).
        """
        if not book_id:
            raise ValueError("book_id must be non-empty")
        if not chapter_id:
            raise ValueError("chapter_id must be non-empty")
        if not isinstance(scope, EditScope):
            raise ValueError("scope must be an EditScope enum")

        key = (book_id, chapter_id, scope)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.pop(key, None)
            if existing is None:
                return EditLockResult(
                    success=False,
                    book_id=book_id,
                    chapter_id=chapter_id,
                    scope=scope,
                    timestamp=now,
                    reason="lock not found",
                )
            return EditLockResult(
                success=True,
                book_id=book_id,
                chapter_id=chapter_id,
                scope=scope,
                timestamp=now,
                reason=(
                    f"force-released (was held by {existing.holder_author_id})"
                ),
            )

    # ---- Inspection -------------------------------------------------------

    def is_held(
        self,
        book_id: str,
        chapter_id: str,
        scope: EditScope,
    ) -> bool:
        """True wenn (book_id, chapter_id, scope) aktuell von nicht-expired Author gehalten wird."""
        if not book_id:
            return False
        if not chapter_id:
            return False
        if not isinstance(scope, EditScope):
            return False
        key = (book_id, chapter_id, scope)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                return False
            return not existing.is_expired()

    def get_state(
        self,
        book_id: str,
        chapter_id: str,
        scope: EditScope,
    ) -> EditLockState:
        """Aktueller EditLockState (FREE / LOCKED / EXPIRED)."""
        if not book_id:
            return EditLockState.FREE
        if not chapter_id:
            return EditLockState.FREE
        if not isinstance(scope, EditScope):
            return EditLockState.FREE
        key = (book_id, chapter_id, scope)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                return EditLockState.FREE
            if existing.is_expired():
                return EditLockState.EXPIRED
            return EditLockState.LOCKED

    def sweep_expired(self) -> int:
        """Purge alle expired Leases. Returns Anzahl entfernter Leases.

        Aufruf typischerweise via Periodic-Worker im sweep_interval_s-Takt.
        """
        with self._lock:
            now = time.monotonic()
            expired_keys = [
                key for key, lease in self._leases.items() if lease.is_expired(now)
            ]
            for key in expired_keys:
                del self._leases[key]
            return len(expired_keys)

    def list_active(self) -> tuple[EditLease, ...]:
        """Snapshot aller aktiven (nicht-expired) Leases als Tuple (immutable)."""
        with self._lock:
            now = time.monotonic()
            return tuple(
                lease for lease in self._leases.values() if not lease.is_expired(now)
            )

    def list_active_for_book(self, book_id: str) -> tuple[EditLease, ...]:
        """Snapshot aller aktiven Leases gefiltert auf book_id (immutable Tuple).

        Use-Case: Editor-Dashboard zeigt aktive Edits nur fuer aktuelles Buchprojekt.
        """
        if not book_id:
            return tuple()
        with self._lock:
            now = time.monotonic()
            return tuple(
                lease
                for lease in self._leases.values()
                if lease.book_id == book_id and not lease.is_expired(now)
            )


# CRUX-MK
