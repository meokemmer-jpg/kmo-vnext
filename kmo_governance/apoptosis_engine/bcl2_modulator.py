"""KMO Bcl-2 Modulator [CRUX-MK].

Anti-Apoptose-Lock-Manager. Pro Cell + active Decision: opt-in Protection
verschiebt eff_threshold der Apoptose-Engine nach oben (= Cell ist
geschuetzt vor vorzeitigem Tod).

Bio-Aequivalent: Bcl-2-Familie (BCL-2, BCL-XL = Anti-Apoptose; BAX, BAK = Pro-Apoptose).
Hier: Anti-Apoptose-Modulation. Pro-Apoptose-Signale leben in apoptosis_engine.signal().

Use-Case (Phase-1 Stub):
    bcl2 = Bcl2Modulator()
    token = bcl2.protect_pending_decision(
        cell_id="cell-1", hotel_id="hotel-A",
        decision_id="approval-pending-token-X",
        ttl_sec=300,
    )
    # ... waehrend kritische Entscheidung laeuft, ist Cell geschuetzt ...
    bcl2.release_protection(token)

Mathematisch:
    offset(n) = log1p(n_active)   # raises eff_threshold by log(1 + n_active)
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional


DEFAULT_PROTECTION_TTL_SEC: float = 300.0


@dataclass(frozen=True)
class ProtectionToken:
    """Immutable token for an active anti-apoptose protection."""

    token_id: str
    cell_id: str
    hotel_id: str
    decision_id: str
    issued_at: float
    expires_at: float


class Bcl2Modulator:
    """In-process anti-apoptose protection registry, thread-safe.

    Pre-Conditions:
        - clock injectable for tests
    Post-Conditions:
        - protect_pending_decision -> token; release_protection(token) is idempotent
        - count_active_protections excludes expired entries
        - Concurrent protect/release operations are atomic
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._tokens: dict[str, ProtectionToken] = {}

    def protect_pending_decision(
        self,
        cell_id: str,
        hotel_id: str,
        decision_id: str,
        ttl_sec: float = DEFAULT_PROTECTION_TTL_SEC,
    ) -> str:
        """Register an anti-apoptose protection. Returns token_id."""
        if not cell_id or not hotel_id or not decision_id:
            raise ValueError("cell_id, hotel_id, decision_id required")
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")
        now = self._clock()
        token_id = str(uuid.uuid4())
        token = ProtectionToken(
            token_id=token_id,
            cell_id=cell_id,
            hotel_id=hotel_id,
            decision_id=decision_id,
            issued_at=now,
            expires_at=now + float(ttl_sec),
        )
        with self._lock:
            self._tokens[token_id] = token
        return token_id

    def release_protection(self, token_id: str) -> bool:
        """Release a protection by token. Idempotent (returns False if unknown)."""
        with self._lock:
            return self._tokens.pop(token_id, None) is not None

    def count_active_protections(self, cell_id: str, hotel_id: str) -> int:
        """Count non-expired protections for (cell_id, hotel_id)."""
        now = self._clock()
        with self._lock:
            return sum(
                1
                for t in self._tokens.values()
                if t.cell_id == cell_id and t.hotel_id == hotel_id and t.expires_at > now
            )

    def list_active(self, cell_id: str, hotel_id: str) -> list[ProtectionToken]:
        """Snapshot of active protections for diagnostics."""
        now = self._clock()
        with self._lock:
            return [
                t
                for t in self._tokens.values()
                if t.cell_id == cell_id and t.hotel_id == hotel_id and t.expires_at > now
            ]

    def purge_expired(self) -> int:
        """Remove expired entries. Returns number removed."""
        now = self._clock()
        with self._lock:
            expired_ids = [tid for tid, t in self._tokens.items() if t.expires_at <= now]
            for tid in expired_ids:
                del self._tokens[tid]
            return len(expired_ids)


# CRUX-MK
