# [CRUX-MK]
"""KPM-Distributed-Trade-Lock-Manager [CRUX-MK].

Welle-26 Phase-19 Modul: Strategy-Lock-Coordinator fuer concurrent trades
(TTL-Lease + Auto-Release) im KPM-Trading-Domain.

Bio-Aequivalent: Synaptische-Verbindung.
    Pre-Synapse        -> holder_strategy_id reserviert Trade-Slot (Lease)
    Post-Synapse       -> Order-Slot mit Lease-Time (kurze TTL, 5s Default)
    Aktivitaets-Decay  -> Auto-Release nach TTL-Ablauf (verhindert Stale-Locks)
    Kompetition        -> Multiple Strategien kompetitieren um (instrument, side)

Domain-Mapping (vs. Hotel-distributed_lock_manager):
    Hotel.lock_id              -> Trading.(instrument_id, position_side)
    Hotel.holder_id            -> Trading.holder_strategy_id
    Hotel.ttl_s 30.0           -> Trading.ttl_s 5.0 (Trading kurzlebig)
    Hotel.sweep_interval 5.0   -> Trading.sweep_interval 1.0 (haeufiger)

Pattern-Inspiration:
- distributed_lock_manager (Welle-21, Synaptic-Pattern, 373 LoC)
- kpm_trading_failover (Welle-23, Domain-Mapping-Vorlage)

CRUX-Bindung:
- K_0: lease_token verhindert Order-Hijacking durch fremde Strategien
- Q_0: Auto-Release expired Leases verhindert Strategy-Deadlocks
- I_min: uuid.uuid4 Token als kryptographischer Strategy-Owner-Beleg
- W_0: Sweep-on-Acquire (amortisierter O(1)-Cleanup)

Usage:
    >>> mgr = KPMDistributedTradeLockManager(default_ttl_s=5.0)
    >>> r = mgr.acquire("BTCUSDT", PositionSide.LONG, "kelly-0.4-strat", ttl_s=3.0)
    >>> if r.success:
    ...     # ... place order ...
    ...     mgr.release("BTCUSDT", PositionSide.LONG, r.lease.lease_token)
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


class PositionSide(str, enum.Enum):
    """Trading-Side: LONG / SHORT / FLAT.

    LONG und SHORT auf gleichem Instrument sind unabhaengige Locks
    (separate Synapsen). FLAT als neutraler Zustand (i.d.R. nicht gelockt).
    """

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class TradeLockState(str, enum.Enum):
    """Lifecycle-Status eines Trade-Locks (synaptische Verbindung)."""

    FREE = "free"
    ACQUIRED = "acquired"
    EXPIRED = "expired"
    RELEASED = "released"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeLease:
    """TTL-Lease Beleg fuer einen Trade-Lock.

    Pre-Conditions:
        instrument_id non-empty.
        position_side ist PositionSide-Instanz (LONG / SHORT / FLAT).
        holder_strategy_id non-empty.
        acquired_at >= 0.
        expires_at > acquired_at.
        ttl_s > 0.
        lease_token non-empty (uuid.uuid4().hex).

    Post-Conditions:
        Frozen / hashable / immutable.
    """

    instrument_id: str
    position_side: PositionSide
    holder_strategy_id: str
    acquired_at: float
    expires_at: float
    ttl_s: float
    lease_token: str

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(self.position_side, PositionSide):
            raise ValueError("position_side must be a PositionSide enum")
        if not self.holder_strategy_id:
            raise ValueError("holder_strategy_id must be non-empty")
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
class TradeLockResult:
    """Ergebnis einer Trade-Lock-Operation (acquire/renew/release/force_release).

    Pre-Conditions:
        instrument_id non-empty.
        position_side ist PositionSide-Instanz.
        timestamp >= 0.
        reason non-empty.

    Post-Conditions:
        Frozen / immutable.
    """

    success: bool
    instrument_id: str
    position_side: PositionSide
    timestamp: float
    reason: str
    lease: Optional[TradeLease] = None
    conflict_holder: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(self.position_side, PositionSide):
            raise ValueError("position_side must be a PositionSide enum")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")
        if not self.reason:
            raise ValueError("reason must be non-empty")


# ---------------------------------------------------------------------------
# KPM-Distributed-Trade-Lock-Manager
# ---------------------------------------------------------------------------


class KPMDistributedTradeLockManager:
    """TTL-Lease basierter Distributed-Trade-Lock-Manager mit Auto-Release.

    Pre-Conditions:
        default_ttl_s > 0 (Trading-Default 5.0s, kurzlebig).
        sweep_interval_s > 0 (Default 1.0s, haeufiger als Hotel).

    Thread-Safety:
        Alle Operationen sind serialisiert via threading.RLock.

    Lock-Key:
        (instrument_id, position_side) als Tupel — LONG und SHORT auf
        gleichem Instrument sind unabhaengige Locks.

    Auto-Release-Mechanik:
        Sweep-on-Acquire: Bei jedem acquire() wird vorher der Ziel-Lock
        auf Expiry geprueft. Optional kann sweep_expired() explizit aufgerufen
        werden (z.B. via Cron oder Periodic-Worker mit sweep_interval_s).
    """

    def __init__(
        self,
        default_ttl_s: float = 5.0,
        sweep_interval_s: float = 1.0,
    ) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if sweep_interval_s <= 0:
            raise ValueError("sweep_interval_s must be > 0")
        self._default_ttl_s = default_ttl_s
        self._sweep_interval_s = sweep_interval_s
        self._leases: dict[tuple[str, PositionSide], TradeLease] = {}
        self._lock = threading.RLock()

    # ---- Acquire / Renew / Release ----------------------------------------

    def acquire(
        self,
        instrument_id: str,
        position_side: PositionSide,
        holder_strategy_id: str,
        ttl_s: Optional[float] = None,
    ) -> TradeLockResult:
        """Versuche, (instrument_id, position_side) fuer holder_strategy_id zu reservieren.

        Auto-Release: Falls Lock expired ist, wird er vor dem
        Acquire-Versuch automatisch released.

        Returns:
            TradeLockResult.success=True mit TradeLease bei Erfolg.
            TradeLockResult.success=False mit conflict_holder bei Konflikt.
        """
        if not instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(position_side, PositionSide):
            raise ValueError("position_side must be a PositionSide enum")
        if not holder_strategy_id:
            raise ValueError("holder_strategy_id must be non-empty")
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")

        key = (instrument_id, position_side)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is not None:
                if existing.is_expired(now):
                    # Auto-Release expired Lease vor Reacquire
                    del self._leases[key]
                else:
                    return TradeLockResult(
                        success=False,
                        instrument_id=instrument_id,
                        position_side=position_side,
                        timestamp=now,
                        reason=f"lock held by {existing.holder_strategy_id}",
                        conflict_holder=existing.holder_strategy_id,
                    )
            lease = TradeLease(
                instrument_id=instrument_id,
                position_side=position_side,
                holder_strategy_id=holder_strategy_id,
                acquired_at=now,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=uuid.uuid4().hex,
            )
            self._leases[key] = lease
            return TradeLockResult(
                success=True,
                instrument_id=instrument_id,
                position_side=position_side,
                timestamp=now,
                reason="acquired",
                lease=lease,
            )

    def renew(
        self,
        instrument_id: str,
        position_side: PositionSide,
        lease_token: str,
        additional_ttl_s: Optional[float] = None,
    ) -> TradeLockResult:
        """Verlaengere Lease um additional_ttl_s (oder default_ttl_s)."""
        if not instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(position_side, PositionSide):
            raise ValueError("position_side must be a PositionSide enum")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")
        ttl = additional_ttl_s if additional_ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("additional_ttl_s must be > 0")

        key = (instrument_id, position_side)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is None:
                return TradeLockResult(
                    success=False,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    timestamp=now,
                    reason="lock not found",
                )
            if existing.lease_token != lease_token:
                return TradeLockResult(
                    success=False,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_strategy_id,
                )
            if existing.is_expired(now):
                del self._leases[key]
                return TradeLockResult(
                    success=False,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    timestamp=now,
                    reason="lease expired before renew",
                )
            renewed = TradeLease(
                instrument_id=existing.instrument_id,
                position_side=existing.position_side,
                holder_strategy_id=existing.holder_strategy_id,
                acquired_at=existing.acquired_at,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=existing.lease_token,
            )
            self._leases[key] = renewed
            return TradeLockResult(
                success=True,
                instrument_id=instrument_id,
                position_side=position_side,
                timestamp=now,
                reason="renewed",
                lease=renewed,
            )

    def release(
        self,
        instrument_id: str,
        position_side: PositionSide,
        lease_token: str,
    ) -> TradeLockResult:
        """Token-validated Release. Nur Owner mit gueltigem Token darf releasen."""
        if not instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(position_side, PositionSide):
            raise ValueError("position_side must be a PositionSide enum")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")

        key = (instrument_id, position_side)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is None:
                return TradeLockResult(
                    success=False,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    timestamp=now,
                    reason="lock not found",
                )
            if existing.lease_token != lease_token:
                return TradeLockResult(
                    success=False,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_strategy_id,
                )
            del self._leases[key]
            return TradeLockResult(
                success=True,
                instrument_id=instrument_id,
                position_side=position_side,
                timestamp=now,
                reason="released",
            )

    def force_release(
        self,
        instrument_id: str,
        position_side: PositionSide,
    ) -> TradeLockResult:
        """Admin-Override: Release ohne Token-Validation."""
        if not instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(position_side, PositionSide):
            raise ValueError("position_side must be a PositionSide enum")

        key = (instrument_id, position_side)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.pop(key, None)
            if existing is None:
                return TradeLockResult(
                    success=False,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    timestamp=now,
                    reason="lock not found",
                )
            return TradeLockResult(
                success=True,
                instrument_id=instrument_id,
                position_side=position_side,
                timestamp=now,
                reason=(
                    f"force-released (was held by {existing.holder_strategy_id})"
                ),
            )

    # ---- Inspection -------------------------------------------------------

    def is_held(
        self,
        instrument_id: str,
        position_side: PositionSide,
    ) -> bool:
        """True wenn (instrument_id, position_side) aktuell von nicht-expired Holder gehalten wird."""
        if not instrument_id:
            return False
        if not isinstance(position_side, PositionSide):
            return False
        key = (instrument_id, position_side)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                return False
            return not existing.is_expired()

    def get_state(
        self,
        instrument_id: str,
        position_side: PositionSide,
    ) -> TradeLockState:
        """Aktueller TradeLockState (FREE / ACQUIRED / EXPIRED)."""
        if not instrument_id:
            return TradeLockState.FREE
        if not isinstance(position_side, PositionSide):
            return TradeLockState.FREE
        key = (instrument_id, position_side)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                return TradeLockState.FREE
            if existing.is_expired():
                return TradeLockState.EXPIRED
            return TradeLockState.ACQUIRED

    def sweep_expired(self) -> int:
        """Purge alle expired Leases. Returns Anzahl entfernter Leases."""
        with self._lock:
            now = time.monotonic()
            expired_keys = [
                key for key, lease in self._leases.items() if lease.is_expired(now)
            ]
            for key in expired_keys:
                del self._leases[key]
            return len(expired_keys)

    def list_active(self) -> tuple[TradeLease, ...]:
        """Snapshot aller aktiven (nicht-expired) Leases als Tuple (immutable)."""
        with self._lock:
            now = time.monotonic()
            return tuple(
                lease for lease in self._leases.values() if not lease.is_expired(now)
            )


# CRUX-MK
