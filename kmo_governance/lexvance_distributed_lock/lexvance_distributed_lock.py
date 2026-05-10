# [CRUX-MK]
"""LexVance-Distributed-Document-Lock Implementation (Welle-41 Phase-34)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DocumentLockState(str, Enum):
    AVAILABLE = "available"
    HELD = "held"
    EXPIRED = "expired"
    CONFLICT_OF_INTEREST = "conflict_of_interest"  # LexVance-spezifisch


@dataclass(frozen=True)
class DocumentLockResult:
    """Lock-Operation-Result."""
    success: bool
    state: DocumentLockState
    mandant_id: str
    document_id: str
    edit_phase: str
    holder_lawyer_id: Optional[str]
    lease_token: Optional[str]
    expires_at: Optional[float]
    timestamp: float


class LexVanceDistributedLock:
    """LexVance-Multi-Mandant-Document-Lock-Manager.

    Pre:
      - default_ttl_s > 0
      - max_locks >= 1

    Conflict-of-Interest: ein lawyer_id kann nicht gleichzeitig Locks bei
    rival_mandanten halten (Pflicht zur Mandanten-Trennung).
    """

    def __init__(
        self,
        default_ttl_s: float = 3600.0,  # 1h default lawyer-editing
        max_locks: int = 500,
    ) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if max_locks < 1:
            raise ValueError("max_locks must be >= 1")
        self._default_ttl = default_ttl_s
        self._max_locks = max_locks
        self._lock = threading.RLock()
        # Key: (mandant_id, document_id, edit_phase) -> (lawyer_id, token, expires_at)
        self._locks: dict[tuple[str, str, str], tuple[str, str, float]] = {}
        # Conflict-of-Interest tracking: rival_mandanten_pairs
        self._rival_pairs: set[frozenset[str]] = set()

    def declare_rival_mandanten(self, mandant_a: str, mandant_b: str) -> tuple[str, ...]:
        """Mark two mandanten as rivals + retroactive-Check (W47-P2 V20-F2-Fix).

        Pre: both non-empty + different
        Returns: tuple of conflict-violator-keys (lawyer_ids that hold both)
                 = empty tuple wenn keine retroactive-Verletzung
        """
        if not mandant_a or not mandant_b:
            raise ValueError("both mandant_ids must be non-empty")
        if mandant_a == mandant_b:
            raise ValueError("mandanten must be different")
        with self._lock:
            self._rival_pairs.add(frozenset({mandant_a, mandant_b}))
            # W47-P2 (V20-F2): retroactive COI-Check
            # Find lawyers that hold locks at BOTH mandant_a AND mandant_b
            lawyers_at_a: set[str] = set()
            lawyers_at_b: set[str] = set()
            for (mid, _, _), (lawyer_id, _, _) in self._locks.items():
                if mid == mandant_a:
                    lawyers_at_a.add(lawyer_id)
                elif mid == mandant_b:
                    lawyers_at_b.add(lawyer_id)
            conflicting_lawyers = tuple(sorted(lawyers_at_a & lawyers_at_b))
            return conflicting_lawyers

    def acquire(
        self,
        mandant_id: str,
        document_id: str,
        edit_phase: str,
        lawyer_id: str,
        ttl_s: Optional[float] = None,
    ) -> DocumentLockResult:
        """Acquire Document-Lock with COI-check."""
        if not mandant_id or not document_id or not edit_phase or not lawyer_id:
            raise ValueError("all lock-key fields + lawyer_id must be non-empty")
        ttl = ttl_s if ttl_s is not None else self._default_ttl
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")
        key = (mandant_id, document_id, edit_phase)
        now = time.monotonic()
        with self._lock:
            self._sweep_expired(now)

            # COI-Check: holds lawyer Locks bei rival_mandant?
            if self._has_conflict_of_interest(lawyer_id, mandant_id):
                return DocumentLockResult(
                    success=False,
                    state=DocumentLockState.CONFLICT_OF_INTEREST,
                    mandant_id=mandant_id,
                    document_id=document_id,
                    edit_phase=edit_phase,
                    holder_lawyer_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )

            if key in self._locks:
                existing_holder, _, expires_at = self._locks[key]
                if existing_holder == lawyer_id:
                    # Re-acquire by same lawyer = renew
                    new_token = str(uuid.uuid4())
                    new_expires = now + ttl
                    self._locks[key] = (lawyer_id, new_token, new_expires)
                    return DocumentLockResult(
                        success=True,
                        state=DocumentLockState.HELD,
                        mandant_id=mandant_id,
                        document_id=document_id,
                        edit_phase=edit_phase,
                        holder_lawyer_id=lawyer_id,
                        lease_token=new_token,
                        expires_at=new_expires,
                        timestamp=time.time(),
                    )
                # Different lawyer
                return DocumentLockResult(
                    success=False,
                    state=DocumentLockState.HELD,
                    mandant_id=mandant_id,
                    document_id=document_id,
                    edit_phase=edit_phase,
                    holder_lawyer_id=existing_holder,
                    lease_token=None,
                    expires_at=expires_at,
                    timestamp=time.time(),
                )

            if len(self._locks) >= self._max_locks:
                return DocumentLockResult(
                    success=False,
                    state=DocumentLockState.AVAILABLE,
                    mandant_id=mandant_id,
                    document_id=document_id,
                    edit_phase=edit_phase,
                    holder_lawyer_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )

            token = str(uuid.uuid4())
            expires = now + ttl
            self._locks[key] = (lawyer_id, token, expires)
            return DocumentLockResult(
                success=True,
                state=DocumentLockState.HELD,
                mandant_id=mandant_id,
                document_id=document_id,
                edit_phase=edit_phase,
                holder_lawyer_id=lawyer_id,
                lease_token=token,
                expires_at=expires,
                timestamp=time.time(),
            )

    def release(
        self,
        mandant_id: str,
        document_id: str,
        edit_phase: str,
        lease_token: str,
    ) -> DocumentLockResult:
        """Release with token-validation (idempotent)."""
        key = (mandant_id, document_id, edit_phase)
        with self._lock:
            if key not in self._locks:
                return DocumentLockResult(
                    success=True,
                    state=DocumentLockState.AVAILABLE,
                    mandant_id=mandant_id,
                    document_id=document_id,
                    edit_phase=edit_phase,
                    holder_lawyer_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )
            _, existing_token, _ = self._locks[key]
            if existing_token != lease_token:
                return DocumentLockResult(
                    success=False,
                    state=DocumentLockState.HELD,
                    mandant_id=mandant_id,
                    document_id=document_id,
                    edit_phase=edit_phase,
                    holder_lawyer_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )
            del self._locks[key]
            return DocumentLockResult(
                success=True,
                state=DocumentLockState.AVAILABLE,
                mandant_id=mandant_id,
                document_id=document_id,
                edit_phase=edit_phase,
                holder_lawyer_id=None,
                lease_token=None,
                expires_at=None,
                timestamp=time.time(),
            )

    def _has_conflict_of_interest(self, lawyer_id: str, target_mandant_id: str) -> bool:
        """Check if lawyer holds locks at rival_mandant."""
        for (mid, _, _), (lid, _, _) in self._locks.items():
            if lid == lawyer_id and mid != target_mandant_id:
                # Are mid + target_mandant_id rivals?
                if frozenset({mid, target_mandant_id}) in self._rival_pairs:
                    return True
        return False

    def _sweep_expired(self, now: float) -> None:
        expired_keys = [
            k for k, (_, _, expires_at) in self._locks.items()
            if expires_at <= now
        ]
        for k in expired_keys:
            del self._locks[k]

    def active_locks_count(self) -> int:
        with self._lock:
            self._sweep_expired(time.monotonic())
            return len(self._locks)


# CRUX-MK
