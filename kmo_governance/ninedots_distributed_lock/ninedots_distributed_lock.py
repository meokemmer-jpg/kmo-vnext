# [CRUX-MK]
"""9dots-Distributed-Project-Lock Implementation (Welle-38 Phase-31 W38-T3)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProjectLockState(str, Enum):
    AVAILABLE = "available"
    HELD = "held"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ProjectLockResult:
    """Lock-Operation-Result.

    Pre:
      - state in ProjectLockState
      - holder_session_id non-empty when state=HELD
    """
    success: bool
    state: ProjectLockState
    project_id: str
    phase: str
    owner_role: str
    holder_session_id: Optional[str]
    lease_token: Optional[str]
    expires_at: Optional[float]
    timestamp: float


class NineDotsDistributedLock:
    """9dots-PMO Multi-Project-Lock-Manager.

    Pre:
      - default_ttl_s > 0
      - max_locks >= 1
    """

    def __init__(
        self,
        default_ttl_s: float = 1800.0,  # 30 min PMO-Workshop default
        max_locks: int = 100,
    ) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if max_locks < 1:
            raise ValueError("max_locks must be >= 1")
        self._default_ttl = default_ttl_s
        self._max_locks = max_locks
        self._lock = threading.RLock()
        # Key: (project_id, phase, owner_role) -> (holder_session_id, lease_token, expires_at)
        self._locks: dict[tuple[str, str, str], tuple[str, str, float]] = {}

    def acquire(
        self,
        project_id: str,
        phase: str,
        owner_role: str,
        holder_session_id: str,
        ttl_s: Optional[float] = None,
    ) -> ProjectLockResult:
        """Acquire Lock fuer (project_id, phase, owner_role)."""
        if not project_id or not phase or not owner_role or not holder_session_id:
            raise ValueError("all lock-key fields must be non-empty")
        ttl = ttl_s if ttl_s is not None else self._default_ttl
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")
        key = (project_id, phase, owner_role)
        now = time.monotonic()
        with self._lock:
            self._sweep_expired(now)
            if key in self._locks:
                existing_holder, _, expires_at = self._locks[key]
                # Re-acquire by same holder = renew TTL
                if existing_holder == holder_session_id:
                    new_token = str(uuid.uuid4())
                    new_expires = now + ttl
                    self._locks[key] = (holder_session_id, new_token, new_expires)
                    return ProjectLockResult(
                        success=True,
                        state=ProjectLockState.HELD,
                        project_id=project_id,
                        phase=phase,
                        owner_role=owner_role,
                        holder_session_id=holder_session_id,
                        lease_token=new_token,
                        expires_at=new_expires,
                        timestamp=time.time(),
                    )
                # Different holder, lock is held
                return ProjectLockResult(
                    success=False,
                    state=ProjectLockState.HELD,
                    project_id=project_id,
                    phase=phase,
                    owner_role=owner_role,
                    holder_session_id=existing_holder,
                    lease_token=None,
                    expires_at=expires_at,
                    timestamp=time.time(),
                )
            # Free slot
            if len(self._locks) >= self._max_locks:
                return ProjectLockResult(
                    success=False,
                    state=ProjectLockState.AVAILABLE,
                    project_id=project_id,
                    phase=phase,
                    owner_role=owner_role,
                    holder_session_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )
            token = str(uuid.uuid4())
            expires = now + ttl
            self._locks[key] = (holder_session_id, token, expires)
            return ProjectLockResult(
                success=True,
                state=ProjectLockState.HELD,
                project_id=project_id,
                phase=phase,
                owner_role=owner_role,
                holder_session_id=holder_session_id,
                lease_token=token,
                expires_at=expires,
                timestamp=time.time(),
            )

    def release(
        self,
        project_id: str,
        phase: str,
        owner_role: str,
        lease_token: str,
    ) -> ProjectLockResult:
        """Release Lock by lease_token (token-validated, idempotent)."""
        key = (project_id, phase, owner_role)
        with self._lock:
            if key not in self._locks:
                return ProjectLockResult(
                    success=True,  # idempotent
                    state=ProjectLockState.AVAILABLE,
                    project_id=project_id,
                    phase=phase,
                    owner_role=owner_role,
                    holder_session_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )
            _, existing_token, _ = self._locks[key]
            if existing_token != lease_token:
                # Wrong token (race-condition), DO NOT release
                return ProjectLockResult(
                    success=False,
                    state=ProjectLockState.HELD,
                    project_id=project_id,
                    phase=phase,
                    owner_role=owner_role,
                    holder_session_id=None,
                    lease_token=None,
                    expires_at=None,
                    timestamp=time.time(),
                )
            del self._locks[key]
            return ProjectLockResult(
                success=True,
                state=ProjectLockState.AVAILABLE,
                project_id=project_id,
                phase=phase,
                owner_role=owner_role,
                holder_session_id=None,
                lease_token=None,
                expires_at=None,
                timestamp=time.time(),
            )

    def get_holder(
        self,
        project_id: str,
        phase: str,
        owner_role: str,
    ) -> Optional[str]:
        """Returns current holder_session_id or None if AVAILABLE/EXPIRED."""
        key = (project_id, phase, owner_role)
        now = time.monotonic()
        with self._lock:
            self._sweep_expired(now)
            if key in self._locks:
                holder, _, _ = self._locks[key]
                return holder
            return None

    def active_locks_count(self) -> int:
        with self._lock:
            self._sweep_expired(time.monotonic())
            return len(self._locks)

    def _sweep_expired(self, now: float) -> None:
        """Internal: drop expired locks (caller must hold self._lock)."""
        expired_keys = [
            k for k, (_, _, expires_at) in self._locks.items()
            if expires_at <= now
        ]
        for k in expired_keys:
            del self._locks[k]


# CRUX-MK
