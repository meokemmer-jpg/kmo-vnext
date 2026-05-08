# [CRUX-MK]
"""SAE-v8-Distributed-Trinity-Voting-Lock-Manager [CRUX-MK].

Welle-34 Phase-27 Modul: Trinity-Voting-Round-Lock-Coordinator (TTL-Lease + Auto-Release)
im SAE-v8-Domain (Symbiotic-Agent-Engine v8, AI-First-Hotel-Operations).

Bio-Aequivalent: Synaptische-Verbindung.
    Pre-Synapse        -> holder_voter_id reserviert Trinity-Voting-Round-Slot (Lease)
    Post-Synapse       -> Voting-Round-Slot mit Lease-Time (kurze TTL, 10s Default)
    Aktivitaets-Decay  -> Auto-Release nach TTL-Ablauf (verhindert Stale-Voting-Locks)
    Kompetition        -> Multiple Voter kompetitieren um (slot_id, voting_round_id)

Domain-Mapping (vs. Hotel-distributed_lock_manager / KPM-Variante):
    Hotel.lock_id              -> SAE.(slot_id, voting_round_id)
    Hotel.holder_id            -> SAE.holder_voter_id
    Hotel.ttl_s 30.0           -> SAE.ttl_s 10.0 (Trinity-Round-Window)
    Hotel.sweep_interval 5.0   -> SAE.sweep_interval 1.0 (haeufiger Reaper)
    KPM.position_side          -> SAE.variant_locked (Trinity-Variant-Audit-Marker)

Pattern-Inspiration:
- distributed_lock_manager (Welle-21, Hotel-Domain, Synaptic-Pattern, ~373 LoC)
- kpm_distributed_lock_manager (Welle-26, KPM-Domain, Tupel-Schluessel-Vorlage)
- sae_chaos_engineering_for_aiops (Welle-30, SAE-Domain-Doctrine, no live-tampering)

CRUX-Bindung:
- K_0: lease_token verhindert Voting-Hijacking durch fremde Voter
- Q_0: Auto-Release expired Leases verhindert Voting-Round-Deadlocks
- I_min: uuid.uuid4 Token als kryptographischer Voter-Owner-Beleg
- W_0: Sweep-on-Acquire (amortisierter O(1)-Cleanup) + collections.deque-Audit

Usage:
    >>> mgr = SAEv8DistributedTrinityLockManager(default_ttl_s=10.0)
    >>> r = mgr.acquire(
    ...     slot_id="slot_42",
    ...     voting_round_id="round_2026-05-07_001",
    ...     holder_voter_id="voter_alpha",
    ...     variant_locked=TrinityVariant.CONSERVATIVE,
    ... )
    >>> if r.success:
    ...     # ... run Trinity-Voting Best-of-3 ...
    ...     mgr.release("slot_42", "round_2026-05-07_001", r.lease.lease_token)
"""

from __future__ import annotations

import enum
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrinityVariant(str, enum.Enum):
    """SAE-v8 Trinity-Variant (Conservative / Aggressive / Contrarian).

    Pro Slot existieren genau 3 Variants. Best-of-3 Voting waehlt die
    dominante Variant pro Voting-Round. variant_locked haelt fest welche
    Variant in der aktuellen Voting-Round das Lock haelt (Audit-Marker,
    no live-SAE-tampering).
    """

    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    CONTRARIAN = "contrarian"


class VotingLockState(str, enum.Enum):
    """Lifecycle-Status eines Trinity-Voting-Round-Locks (synaptische Verbindung)."""

    FREE = "free"
    ACQUIRED = "acquired"
    EXPIRED = "expired"
    RELEASED = "released"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrinityVotingLease:
    """TTL-Lease Beleg fuer einen Trinity-Voting-Round-Lock.

    Pre-Conditions:
        slot_id non-empty.
        voting_round_id non-empty.
        holder_voter_id non-empty.
        variant_locked ist TrinityVariant-Instanz.
        acquired_at >= 0.
        expires_at > acquired_at.
        ttl_s > 0.
        lease_token non-empty (uuid.uuid4().hex).

    Post-Conditions:
        Frozen / hashable / immutable.
    """

    slot_id: str
    voting_round_id: str
    holder_voter_id: str
    variant_locked: TrinityVariant
    acquired_at: float
    expires_at: float
    ttl_s: float
    lease_token: str

    def __post_init__(self) -> None:
        if not self.slot_id:
            raise ValueError("slot_id must be non-empty")
        if not self.voting_round_id:
            raise ValueError("voting_round_id must be non-empty")
        if not self.holder_voter_id:
            raise ValueError("holder_voter_id must be non-empty")
        if not isinstance(self.variant_locked, TrinityVariant):
            raise ValueError("variant_locked must be a TrinityVariant enum")
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
class TrinityVotingLockResult:
    """Ergebnis einer Trinity-Voting-Lock-Operation.

    (acquire / renew / release / force_release)

    Pre-Conditions:
        slot_id non-empty.
        voting_round_id non-empty.
        timestamp >= 0.
        reason non-empty.

    Post-Conditions:
        Frozen / immutable.
    """

    success: bool
    slot_id: str
    voting_round_id: str
    timestamp: float
    reason: str
    lease: Optional[TrinityVotingLease] = None
    conflict_holder: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.slot_id:
            raise ValueError("slot_id must be non-empty")
        if not self.voting_round_id:
            raise ValueError("voting_round_id must be non-empty")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")
        if not self.reason:
            raise ValueError("reason must be non-empty")


# ---------------------------------------------------------------------------
# SAE-v8-Distributed-Trinity-Voting-Lock-Manager
# ---------------------------------------------------------------------------


class SAEv8DistributedTrinityLockManager:
    """TTL-Lease basierter Distributed-Trinity-Voting-Lock-Manager mit Auto-Release.

    Pre-Conditions:
        default_ttl_s > 0 (SAE-Default 10.0s = Trinity-Round-Window).
        sweep_interval_s > 0 (Default 1.0s, haeufiger Reaper).

    Thread-Safety:
        Alle Operationen sind serialisiert via threading.RLock (re-entrant).

    Lock-Key:
        (slot_id, voting_round_id) als Tupel — verschiedene voting_round_ids
        auf demselben slot_id sind unabhaengige Locks (separate Synapsen).

    Auto-Release-Mechanik:
        Sweep-on-Acquire: Bei jedem acquire() wird vorher der Ziel-Lock
        auf Expiry geprueft. Optional kann sweep_expired() explizit aufgerufen
        werden (z.B. via Cron oder Periodic-Worker mit sweep_interval_s).

    Audit-Trail:
        collections.deque (maxlen=1024) haelt letzte Lock-Events fuer
        Forensik bei Voting-Anomalien (no live-SAE-tampering, observer-only).
    """

    _AUDIT_CAPACITY = 1024

    def __init__(
        self,
        default_ttl_s: float = 10.0,
        sweep_interval_s: float = 1.0,
    ) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if sweep_interval_s <= 0:
            raise ValueError("sweep_interval_s must be > 0")
        self._default_ttl_s = default_ttl_s
        self._sweep_interval_s = sweep_interval_s
        self._leases: dict[tuple[str, str], TrinityVotingLease] = {}
        self._lock = threading.RLock()
        self._audit: deque[tuple[float, str, str, str]] = deque(
            maxlen=self._AUDIT_CAPACITY
        )

    # ---- Acquire / Renew / Release ----------------------------------------

    def acquire(
        self,
        slot_id: str,
        voting_round_id: str,
        holder_voter_id: str,
        variant_locked: TrinityVariant,
        ttl_s: Optional[float] = None,
    ) -> TrinityVotingLockResult:
        """Versuche, (slot_id, voting_round_id) fuer holder_voter_id zu reservieren.

        variant_locked haelt fest welche Trinity-Variant das Lock haelt
        (Audit-Marker, beeinflusst Lock-Granularitaet nicht — Lock-Key bleibt
        (slot_id, voting_round_id)).

        Auto-Release: Falls Lock expired ist, wird er vor dem
        Acquire-Versuch automatisch released.

        Returns:
            TrinityVotingLockResult.success=True mit TrinityVotingLease bei Erfolg.
            TrinityVotingLockResult.success=False mit conflict_holder bei Konflikt.
        """
        if not slot_id:
            raise ValueError("slot_id must be non-empty")
        if not voting_round_id:
            raise ValueError("voting_round_id must be non-empty")
        if not holder_voter_id:
            raise ValueError("holder_voter_id must be non-empty")
        if not isinstance(variant_locked, TrinityVariant):
            raise ValueError("variant_locked must be a TrinityVariant enum")
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")

        key = (slot_id, voting_round_id)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is not None:
                if existing.is_expired(now):
                    # Auto-Release expired Lease vor Reacquire
                    del self._leases[key]
                    self._audit.append((now, slot_id, voting_round_id, "auto-released"))
                else:
                    self._audit.append((now, slot_id, voting_round_id, "conflict"))
                    return TrinityVotingLockResult(
                        success=False,
                        slot_id=slot_id,
                        voting_round_id=voting_round_id,
                        timestamp=now,
                        reason=f"voting-lock held by {existing.holder_voter_id}",
                        conflict_holder=existing.holder_voter_id,
                    )
            lease = TrinityVotingLease(
                slot_id=slot_id,
                voting_round_id=voting_round_id,
                holder_voter_id=holder_voter_id,
                variant_locked=variant_locked,
                acquired_at=now,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=uuid.uuid4().hex,
            )
            self._leases[key] = lease
            self._audit.append((now, slot_id, voting_round_id, "acquired"))
            return TrinityVotingLockResult(
                success=True,
                slot_id=slot_id,
                voting_round_id=voting_round_id,
                timestamp=now,
                reason="acquired",
                lease=lease,
            )

    def renew(
        self,
        slot_id: str,
        voting_round_id: str,
        lease_token: str,
        additional_ttl_s: Optional[float] = None,
    ) -> TrinityVotingLockResult:
        """Verlaengere Lease um additional_ttl_s (oder default_ttl_s)."""
        if not slot_id:
            raise ValueError("slot_id must be non-empty")
        if not voting_round_id:
            raise ValueError("voting_round_id must be non-empty")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")
        ttl = additional_ttl_s if additional_ttl_s is not None else self._default_ttl_s
        if ttl <= 0:
            raise ValueError("additional_ttl_s must be > 0")

        key = (slot_id, voting_round_id)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is None:
                return TrinityVotingLockResult(
                    success=False,
                    slot_id=slot_id,
                    voting_round_id=voting_round_id,
                    timestamp=now,
                    reason="voting-lock not found",
                )
            if existing.lease_token != lease_token:
                return TrinityVotingLockResult(
                    success=False,
                    slot_id=slot_id,
                    voting_round_id=voting_round_id,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_voter_id,
                )
            if existing.is_expired(now):
                del self._leases[key]
                self._audit.append((now, slot_id, voting_round_id, "expired-on-renew"))
                return TrinityVotingLockResult(
                    success=False,
                    slot_id=slot_id,
                    voting_round_id=voting_round_id,
                    timestamp=now,
                    reason="lease expired before renew",
                )
            renewed = TrinityVotingLease(
                slot_id=existing.slot_id,
                voting_round_id=existing.voting_round_id,
                holder_voter_id=existing.holder_voter_id,
                variant_locked=existing.variant_locked,
                acquired_at=existing.acquired_at,
                expires_at=now + ttl,
                ttl_s=ttl,
                lease_token=existing.lease_token,
            )
            self._leases[key] = renewed
            self._audit.append((now, slot_id, voting_round_id, "renewed"))
            return TrinityVotingLockResult(
                success=True,
                slot_id=slot_id,
                voting_round_id=voting_round_id,
                timestamp=now,
                reason="renewed",
                lease=renewed,
            )

    def release(
        self,
        slot_id: str,
        voting_round_id: str,
        lease_token: str,
    ) -> TrinityVotingLockResult:
        """Token-validated Release. Nur Owner mit gueltigem Token darf releasen."""
        if not slot_id:
            raise ValueError("slot_id must be non-empty")
        if not voting_round_id:
            raise ValueError("voting_round_id must be non-empty")
        if not lease_token:
            raise ValueError("lease_token must be non-empty")

        key = (slot_id, voting_round_id)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(key)
            if existing is None:
                return TrinityVotingLockResult(
                    success=False,
                    slot_id=slot_id,
                    voting_round_id=voting_round_id,
                    timestamp=now,
                    reason="voting-lock not found",
                )
            if existing.lease_token != lease_token:
                return TrinityVotingLockResult(
                    success=False,
                    slot_id=slot_id,
                    voting_round_id=voting_round_id,
                    timestamp=now,
                    reason="invalid lease_token",
                    conflict_holder=existing.holder_voter_id,
                )
            del self._leases[key]
            self._audit.append((now, slot_id, voting_round_id, "released"))
            return TrinityVotingLockResult(
                success=True,
                slot_id=slot_id,
                voting_round_id=voting_round_id,
                timestamp=now,
                reason="released",
            )

    def force_release(
        self,
        slot_id: str,
        voting_round_id: str,
    ) -> TrinityVotingLockResult:
        """Admin-Override: Release ohne Token-Validation."""
        if not slot_id:
            raise ValueError("slot_id must be non-empty")
        if not voting_round_id:
            raise ValueError("voting_round_id must be non-empty")

        key = (slot_id, voting_round_id)
        with self._lock:
            now = time.monotonic()
            existing = self._leases.pop(key, None)
            if existing is None:
                return TrinityVotingLockResult(
                    success=False,
                    slot_id=slot_id,
                    voting_round_id=voting_round_id,
                    timestamp=now,
                    reason="voting-lock not found",
                )
            self._audit.append((now, slot_id, voting_round_id, "force-released"))
            return TrinityVotingLockResult(
                success=True,
                slot_id=slot_id,
                voting_round_id=voting_round_id,
                timestamp=now,
                reason=(
                    f"force-released (was held by {existing.holder_voter_id})"
                ),
            )

    # ---- Inspection -------------------------------------------------------

    def is_held(
        self,
        slot_id: str,
        voting_round_id: str,
    ) -> bool:
        """True wenn (slot_id, voting_round_id) von nicht-expired Holder gehalten."""
        if not slot_id or not voting_round_id:
            return False
        key = (slot_id, voting_round_id)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                return False
            return not existing.is_expired()

    def get_state(
        self,
        slot_id: str,
        voting_round_id: str,
    ) -> VotingLockState:
        """Aktueller VotingLockState (FREE / ACQUIRED / EXPIRED)."""
        if not slot_id or not voting_round_id:
            return VotingLockState.FREE
        key = (slot_id, voting_round_id)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                return VotingLockState.FREE
            if existing.is_expired():
                return VotingLockState.EXPIRED
            return VotingLockState.ACQUIRED

    def sweep_expired(self) -> int:
        """Purge alle expired Leases. Returns Anzahl entfernter Leases."""
        with self._lock:
            now = time.monotonic()
            expired_keys = [
                k for k, lease in self._leases.items() if lease.is_expired(now)
            ]
            for k in expired_keys:
                del self._leases[k]
                self._audit.append((now, k[0], k[1], "swept"))
            return len(expired_keys)

    def list_active(self) -> tuple[TrinityVotingLease, ...]:
        """Snapshot aller aktiven (nicht-expired) Leases als Tuple (immutable)."""
        with self._lock:
            now = time.monotonic()
            return tuple(
                lease for lease in self._leases.values() if not lease.is_expired(now)
            )

    def list_active_for_slot(self, slot_id: str) -> tuple[TrinityVotingLease, ...]:
        """Snapshot aller aktiven Leases fuer einen slot_id ueber alle voting_rounds.

        Liefert alle gleichzeitig aktiven Trinity-Voting-Locks auf demselben Slot
        (verschiedene voting_round_ids = unabhaengige Synapsen, koennen koexistieren).
        """
        if not slot_id:
            return ()
        with self._lock:
            now = time.monotonic()
            return tuple(
                lease
                for (sid, _vrid), lease in self._leases.items()
                if sid == slot_id and not lease.is_expired(now)
            )


# CRUX-MK
