"""KMO Distributed-Lock-Manager [CRUX-MK].

Welle-21 Phase-14 Modul: Cross-DF-Resource-Lock-Coordinator (TTL-Lease + Auto-Release).

Bio-Aequivalent: Synaptische-Verbindung.
    Pre-Synapse        -> Holder reserviert Neurotransmitter-Reservoir (Lease)
    Post-Synapse       -> Rezipient mit Lease-Time (TTL-Window)
    Aktivitaets-Decay  -> Auto-Release wenn Synapse-Aktivitaet ablaeuft
    Kompetition        -> Multiple konkurrierende Synapsen kompetitieren um Resource

Pattern-Inspiration:
- saga_step_orchestrator/saga_step_orchestrator.py (frozen dataclasses + RLock)
- audit_event_bus (token-validated Operations)
- failover_router (Multi-State-Machine)

CRUX-Bindung:
- K_0: token-validated release verhindert Lock-Hijacking
- Q_0: Auto-Release expired Leases verhindert Deadlocks
- I_min: uuid.uuid4 Token als kryptographischer Owner-Beleg
- W_0: Sweep-on-Acquire (amortisierter O(1)-Cleanup)

Usage:
    >>> mgr = DistributedLockManager(default_ttl_s=30.0)
    >>> r = mgr.acquire("resource-A", "holder-1", ttl_s=60.0)
    >>> if r.success:
    ...     # ... use resource ...
    ...     mgr.release(r.lock_id, r.lease.lease_token)
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


class LockState(str, enum.Enum):
    """Lifecycle-Status eines Distributed-Locks."""

    FREE = "free"
    ACQUIRED = "acquired"
    EXPIRED = "expired"
    RELEASED = "released"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lease:
    """TTL-Lease Beleg fuer einen Distributed-Lock.

    Pre-Conditions:
        lock_id non-empty.
        holder_id non-empty.
        acquired_at >= 0.
        expires_at > acquired_at.
        ttl_s > 0.
        lease_token non-empty (uuid.uuid4().hex).

    Post-Conditions:
        Frozen / hashable / immutable.
    """

    lock_id: str
    holder_id: str
    acquired_at: float
    expires_at: float
    ttl_s: float
    lease_token: str

    def __post_init__(self) -> None:
        if not self.lock_id:
            raise ValueError("lock_id must be non-empty")
        if not self.holder_id:
            raise ValueError("holder_id must be non-empty")
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
class LockResult:
    """Ergebnis einer Lock-Operation (acquire/renew/release/force_release).

    Pre-Conditions:
        lock_id non-empty.
        timestamp >= 0.
        reason non-empty.

    Post-Conditions:
        Frozen / immutable.
    """

    success: bool
    lock_id: str
    timestamp: float
    reason: str
    lease: Optional[Lease] = None
    conflict_holder: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.lock_id:
            raise ValueError("lock_id must be non-empty")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")
        if not self.reason:
            raise ValueError("reason must be non-empty")


# ---------------------------------------------------------------------------
# Distributed-Lock-Manager
# ---------------------------------------------------------------------------


class DistributedLockManager:
    """TTL-Lease basierter Distributed-Lock-Manager mit Auto-Release.

    Pre-Conditions:
        default_ttl_s > 0.
        sweep_interval_s > 0.

    Thread-Safety:
        Alle Operationen sind serialisiert via threading.RLock.

    Auto-Release-Mechanik:
        Sweep-on-Acquire: Bei jedem acquire() wird vorher der Ziel-Lock
        auf Expiry geprueft. Optional kann sweep_expired() explizit aufgerufen
        werden um alle expired Leases zu purgen (z.B. via Cron oder
        Periodic-Worker).
    """

    def __init__(self, default_ttl_s: float = 30.0, sweep_interval_s: float = 5.0) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if sweep_interval_s <= 0:
            raise ValueError("sweep_interval_s must be > 0")
        self._default_ttl_s = default_ttl_s
        self._sweep_interval_s = sweep_interval_s
        self._leases: dict[str, Lease] = {}
        self._lock = threading.RLock()

    # ---- Acquire / Renew / Release ----------------------------------------

    def acquire(
        self,
        lock_id: str,
        holder_id: str,
        ttl_s: Optional[float] = None,
    ) -> LockResult:
        """Versuche, lock_id fuer holder_id zu reservieren.

        Auto-Release: Falls Lock expired ist, wird er vor dem
        Acquire-Versuch automatisch released.

        Returns:
            LockResult.success=True mit Lease bei Erfolg.
            LockResult.success=False mit conflict_holder bei Konflikt.
        """
        if not lock_id:
            raise ValueError("lock_id must be non-empty")
        if not holder_id:
            raise ValueError("holder_id must be non-empty")
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")

        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(lock_id)
            if existing is not None:
                if existing.is_expired(now):
                    # Auto-Release expired Lease vor Reacquire
                    del self._leases[lock_id]
                else:
                    return LockResult(
                        success=False,
                        lock_id=lock_id,
                        timestamp=now,
                        reason=f"lock held by {existing.holder_id}",
                        conflict_holder=existing.holder_id,
                    )
            lease = Lease(
                lock_id=lock_id,
                holder_id=holder_id,
                acquired_at=now,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=uuid.uuid4().hex,
            )
            self._leases[lock_id] = lease
            return LockResult(
                success=True,
                lock_id=lock_id,
                timestamp=now,
                reason="acquired",
                lease=lease,
            )

    def renew(
        self,
        lock_id: str,
        lease_token: str,
        additional_ttl_s: Optional[float] = None,
    ) -> LockResult:
        """Verlaengere Lease um additional_ttl_s (oder default_ttl_s)."""
        if not lock_id:
            raise ValueError("lock_id must be non-empty")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")
        ttl = additional_ttl_s if additional_ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("additional_ttl_s must be > 0")

        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(lock_id)
            if existing is None:
                return LockResult(
                    success=False,
                    lock_id=lock_id,
                    timestamp=now,
                    reason="lock not found",
                )
            if existing.lease_token != lease_token:
                return LockResult(
                    success=False,
                    lock_id=lock_id,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_id,
                )
            if existing.is_expired(now):
                del self._leases[lock_id]
                return LockResult(
                    success=False,
                    lock_id=lock_id,
                    timestamp=now,
                    reason="lease expired before renew",
                )
            renewed = Lease(
                lock_id=existing.lock_id,
                holder_id=existing.holder_id,
                acquired_at=existing.acquired_at,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=existing.lease_token,
            )
            self._leases[lock_id] = renewed
            return LockResult(
                success=True,
                lock_id=lock_id,
                timestamp=now,
                reason="renewed",
                lease=renewed,
            )

    def release(self, lock_id: str, lease_token: str) -> LockResult:
        """Token-validated Release. Nur Owner mit gueltigem Token darf releasen."""
        if not lock_id:
            raise ValueError("lock_id must be non-empty")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(lock_id)
            if existing is None:
                return LockResult(
                    success=False,
                    lock_id=lock_id,
                    timestamp=now,
                    reason="lock not found",
                )
            if existing.lease_token != lease_token:
                return LockResult(
                    success=False,
                    lock_id=lock_id,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_id,
                )
            del self._leases[lock_id]
            return LockResult(
                success=True,
                lock_id=lock_id,
                timestamp=now,
                reason="released",
            )

    def force_release(self, lock_id: str) -> LockResult:
        """Admin-Override: Release ohne Token-Validation."""
        if not lock_id:
            raise ValueError("lock_id must be non-empty")
        with self._lock:
            now = time.monotonic()
            existing = self._leases.pop(lock_id, None)
            if existing is None:
                return LockResult(
                    success=False,
                    lock_id=lock_id,
                    timestamp=now,
                    reason="lock not found",
                )
            return LockResult(
                success=True,
                lock_id=lock_id,
                timestamp=now,
                reason=f"force-released (was held by {existing.holder_id})",
            )

    # ---- Inspection -------------------------------------------------------

    def is_held(self, lock_id: str) -> bool:
        """True wenn lock_id aktuell von einem nicht-expired Holder gehalten wird."""
        if not lock_id:
            return False
        with self._lock:
            existing = self._leases.get(lock_id)
            if existing is None:
                return False
            return not existing.is_expired()

    def get_state(self, lock_id: str) -> LockState:
        """Aktueller LockState (FREE / ACQUIRED / EXPIRED)."""
        if not lock_id:
            return LockState.FREE
        with self._lock:
            existing = self._leases.get(lock_id)
            if existing is None:
                return LockState.FREE
            if existing.is_expired():
                return LockState.EXPIRED
            return LockState.ACQUIRED

    def sweep_expired(self) -> int:
        """Purge alle expired Leases. Returns Anzahl entfernter Leases."""
        with self._lock:
            now = time.monotonic()
            expired_ids = [
                lid for lid, lease in self._leases.items() if lease.is_expired(now)
            ]
            for lid in expired_ids:
                del self._leases[lid]
            return len(expired_ids)

    def list_active(self) -> list[Lease]:
        """Snapshot aller aktiven (nicht-expired) Leases."""
        with self._lock:
            now = time.monotonic()
            return [lease for lease in self._leases.values() if not lease.is_expired(now)]


# CRUX-MK
