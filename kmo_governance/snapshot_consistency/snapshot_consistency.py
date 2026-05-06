# [CRUX-MK]
"""Snapshot Consistency Engine (Welle-15 Phase-10.2)."""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional


class SnapshotStatus(str, Enum):
    PENDING = "pending"
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    FAILED = "failed"


@dataclass(frozen=True)
class ModuleSnapshot:
    """Single module-snapshot with hash."""

    module_id: str
    state_hash: str
    timestamp: float
    state_size: int

    def __post_init__(self) -> None:
        if not self.module_id:
            raise ValueError("module_id required")
        if not self.state_hash:
            raise ValueError("state_hash required")


@dataclass(frozen=True)
class SnapshotResult:
    """Multi-module snapshot result."""

    snapshot_id: str
    status: SnapshotStatus
    snapshots: tuple  # tuple of ModuleSnapshot
    consistency_check: str
    duration_s: float


class SnapshotConsistencyEngine:
    """Coordinates multi-module snapshots with consistency-checks.

    Pre: at least 1 module registered before snapshot()
    Post: thread-safe; produces SnapshotResult with all module-states
    """

    def __init__(self) -> None:
        self._capture_fns: dict[str, Callable[[], Any]] = {}
        self._counter: int = 0
        self._lock = threading.RLock()

    def register_module(self, module_id: str, capture_fn: Callable[[], Any]) -> None:
        if not module_id:
            raise ValueError("module_id required")
        if not callable(capture_fn):
            raise TypeError("capture_fn must be callable")
        with self._lock:
            self._capture_fns[module_id] = capture_fn

    def unregister_module(self, module_id: str) -> None:
        with self._lock:
            self._capture_fns.pop(module_id, None)

    def _next_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"snap-{int(time.time() * 1000)}-{self._counter}"

    def _hash_state(self, state: Any) -> tuple[str, int]:
        """Stable hash of state-representation."""
        rep = repr(state).encode("utf-8")
        return hashlib.sha256(rep).hexdigest()[:16], len(rep)

    def snapshot(self) -> SnapshotResult:
        """Capture all module-states atomically (best-effort)."""
        snapshot_id = self._next_id()
        start = time.time()
        with self._lock:
            modules = dict(self._capture_fns)
        if not modules:
            return SnapshotResult(
                snapshot_id=snapshot_id,
                status=SnapshotStatus.FAILED,
                snapshots=(),
                consistency_check="no modules registered",
                duration_s=time.time() - start,
            )

        snapshots = []
        failed = []
        for module_id, fn in modules.items():
            try:
                state = fn()
                state_hash, state_size = self._hash_state(state)
                snapshots.append(
                    ModuleSnapshot(
                        module_id=module_id,
                        state_hash=state_hash,
                        timestamp=time.time(),
                        state_size=state_size,
                    )
                )
            except Exception as e:
                failed.append((module_id, str(e)))

        if failed:
            return SnapshotResult(
                snapshot_id=snapshot_id,
                status=SnapshotStatus.FAILED,
                snapshots=tuple(snapshots),
                consistency_check=f"capture failed: {failed}",
                duration_s=time.time() - start,
            )

        # Consistency-Check: timestamps within 100ms window
        timestamps = [s.timestamp for s in snapshots]
        spread = max(timestamps) - min(timestamps)
        is_consistent = spread <= 0.1

        return SnapshotResult(
            snapshot_id=snapshot_id,
            status=SnapshotStatus.CONSISTENT
            if is_consistent
            else SnapshotStatus.INCONSISTENT,
            snapshots=tuple(snapshots),
            consistency_check=f"timestamp_spread={spread:.4f}s",
            duration_s=time.time() - start,
        )

    def compare_snapshots(
        self, snap_a: SnapshotResult, snap_b: SnapshotResult
    ) -> dict:
        """Compare two snapshots, return per-module diff."""
        diffs = {}
        a_map = {s.module_id: s for s in snap_a.snapshots}
        b_map = {s.module_id: s for s in snap_b.snapshots}
        for module_id in set(a_map) | set(b_map):
            a = a_map.get(module_id)
            b = b_map.get(module_id)
            if a is None:
                diffs[module_id] = "missing in A"
            elif b is None:
                diffs[module_id] = "missing in B"
            elif a.state_hash != b.state_hash:
                diffs[module_id] = f"hash differs: {a.state_hash} -> {b.state_hash}"
            else:
                diffs[module_id] = "unchanged"
        return diffs


# CRUX-MK
