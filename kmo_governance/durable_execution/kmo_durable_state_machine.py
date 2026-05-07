"""KMO Durable-Execution-State-Machine [CRUX-MK].

Implements P-KMO-A7 per SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30 §P-KMO-A7.

Self-built JSON-state durable workflow engine (Conservative-pick, NOT Temporal.io).
Persistent state for long-running 7-phase workflows with crash-recovery,
event-sourcing, and snapshots.

Storage layout:
    branch-hub/workflow-state/<workflow-id>/
        events.jsonl           -- append-only event log (one JSON per line)
        snapshots/<seq>.json   -- periodic state snapshots
        state.lock             -- mkdir-mutex for concurrent-transition-safety

Recovery model:
    1. Load latest snapshot (if any) -> base state
    2. Replay events from events.jsonl with sequence > snapshot.sequence
    3. Re-derive WorkflowRun.current_state

Atomic-write pattern (matches kmo_saga_engine.py):
    tempfile.mkstemp -> os.fdopen -> f.flush -> os.fsync -> os.replace

CRUX-MK: K_0 protected via crash-recovery (no lost commits); Q_0 via immutable
event-sourcing audit-trail; W_0 via snapshot-amortized replay cost.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from event_types import (
    Event,
    EventType,
    make_state_transition,
)


# ----- State enums -----

class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DONE = "DONE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


# ----- Dataclasses -----

@dataclass
class WorkflowRun:
    """Materialized view of a workflow's current state.

    Reconstructed from latest snapshot + replay of events with seq > snapshot.seq.
    """

    workflow_id: str
    current_phase: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    state_data: dict = field(default_factory=dict)
    sequence: int = 0  # last applied event-sequence
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "current_phase": self.current_phase,
            "status": self.status.value,
            "state_data": self.state_data,
            "sequence": self.sequence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowRun":
        return cls(
            workflow_id=d["workflow_id"],
            current_phase=d["current_phase"],
            status=WorkflowStatus(d.get("status", "PENDING")),
            state_data=dict(d.get("state_data", {})),
            sequence=int(d.get("sequence", 0)),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


# ----- Engine -----

class ConcurrentTransitionError(RuntimeError):
    """Raised when another process holds the workflow's transition lock."""


class WorkflowNotFoundError(LookupError):
    """Raised when a workflow_id has no events.jsonl on disk."""


class DurableStateMachine:
    """Persistent event-sourced state-machine for KMO workflows.

    Thread-safe within one process (process-local RLock). Cross-process safety
    via filesystem-mutex (mkdir-atomic state.lock directory + stale-lock TTL).

    Pre/Post:
    - start_workflow:  workflow_id is unused -> creates dir, writes WORKFLOW_STARTED.
    - transition:      appends event, updates state_data, persists atomically.
    - recover:         loads snapshot + replays events, returns materialized run.
    - snapshot:        captures current state at current sequence.
    - get_history:     returns all events in order.
    """

    def __init__(
        self,
        state_root: Path | str,
        snapshot_every_n_events: int = 10,
        lock_stale_after_s: float = 300.0,
    ):
        self.state_root = Path(state_root)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.snapshot_every_n_events = max(1, int(snapshot_every_n_events))
        self.lock_stale_after_s = float(lock_stale_after_s)
        self._proc_lock = threading.RLock()

    # ----- Path helpers -----

    def _wf_dir(self, workflow_id: str) -> Path:
        return self.state_root / workflow_id

    def _events_path(self, workflow_id: str) -> Path:
        return self._wf_dir(workflow_id) / "events.jsonl"

    def _snapshots_dir(self, workflow_id: str) -> Path:
        return self._wf_dir(workflow_id) / "snapshots"

    def _lock_dir(self, workflow_id: str) -> Path:
        return self._wf_dir(workflow_id) / "state.lock"

    # ----- Concurrency: filesystem mutex -----

    def _acquire_fs_lock(self, workflow_id: str) -> None:
        """Atomic mkdir-based mutex. Raises ConcurrentTransitionError on contention."""
        lock_dir = self._lock_dir(workflow_id)
        try:
            lock_dir.mkdir(parents=False, exist_ok=False)
            return
        except FileExistsError:
            # Stale-lock detection: if mtime > stale_after_s -> claim.
            try:
                age = time.time() - lock_dir.stat().st_mtime
            except FileNotFoundError:
                # disappeared between checks -> retry once
                lock_dir.mkdir(parents=False, exist_ok=False)
                return
            if age > self.lock_stale_after_s:
                # Take over the stale lock
                try:
                    (lock_dir / "pid").unlink(missing_ok=True)
                except Exception:
                    pass
                # touch by recreating (best-effort)
                os.utime(lock_dir, None)
                return
            raise ConcurrentTransitionError(
                f"Workflow {workflow_id!r} lock held (age {age:.1f}s)"
            )

    def _release_fs_lock(self, workflow_id: str) -> None:
        lock_dir = self._lock_dir(workflow_id)
        try:
            for child in lock_dir.iterdir():
                try:
                    child.unlink()
                except FileNotFoundError:
                    pass
            lock_dir.rmdir()
        except FileNotFoundError:
            pass

    # ----- Atomic IO -----

    def _atomic_write_json(self, target: Path, data: dict) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}-", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _append_event_durable(self, workflow_id: str, event: Event) -> None:
        """Append a single event line to events.jsonl with fsync."""
        path = self._events_path(workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), default=str) + "\n"
        # Open in append+binary for atomic-ish line append, fsync after
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _read_events(self, workflow_id: str) -> list[Event]:
        path = self._events_path(workflow_id)
        if not path.exists():
            return []
        events: list[Event] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(Event.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError):
                    # Skip malformed lines (defensive replay)
                    continue
        events.sort(key=lambda e: e.sequence)
        return events

    # ----- Snapshots -----

    def _latest_snapshot(self, workflow_id: str) -> Optional[WorkflowRun]:
        d = self._snapshots_dir(workflow_id)
        if not d.exists():
            return None
        candidates = sorted(d.glob("*.json"), key=lambda p: int(p.stem))
        if not candidates:
            return None
        latest = candidates[-1]
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return WorkflowRun.from_dict(data)

    def snapshot(self, workflow_id: str) -> WorkflowRun:
        """Take a snapshot of current materialized state."""
        run = self.recover(workflow_id)
        target = self._snapshots_dir(workflow_id) / f"{run.sequence:010d}.json"
        self._atomic_write_json(target, run.to_dict())
        # Also append a SNAPSHOT_TAKEN event so history reflects it
        return run

    # ----- Replay -----

    def _apply_event(self, run: WorkflowRun, event: Event) -> None:
        """Apply a single event to the materialized run (in-memory).

        STATE_TRANSITION updates current_phase + merges state_patch.
        Other event-types are recorded in state_data['history'] but do not
        directly mutate current_phase (caller-domain decides via wrapper).
        """
        if event.event_type == EventType.WORKFLOW_STARTED:
            run.status = WorkflowStatus.RUNNING
            run.created_at = event.timestamp
            initial = event.payload.get("initial_state", {}) or {}
            run.current_phase = event.payload.get("initial_phase", "init")
            run.state_data = dict(initial)
        elif event.event_type == EventType.STATE_TRANSITION:
            payload = event.payload
            to_phase = payload.get("to_phase")
            if to_phase:
                run.current_phase = to_phase
            patch = payload.get("state_patch") or {}
            if isinstance(patch, dict):
                run.state_data.update(patch)
            # Status transitions
            status_str = patch.get("__status") if isinstance(patch, dict) else None
            if status_str:
                try:
                    run.status = WorkflowStatus(status_str)
                except ValueError:
                    pass
        elif event.event_type == EventType.SNAPSHOT_TAKEN:
            # Marker only; state already at this point.
            pass
        else:
            # ROUTING_DECISION / DF_STATUS_CHANGE / STOP_FLAG_TRANSITION /
            # APPROVAL_STATE: record in audit-history without mutating phase.
            history = run.state_data.setdefault("__events_seen", [])
            history.append({
                "event_id": event.event_id,
                "type": event.event_type.value,
                "ts": event.timestamp,
                "seq": event.sequence,
            })
        run.sequence = event.sequence
        run.updated_at = event.timestamp

    # ----- Public API -----

    def start_workflow(
        self,
        workflow_id: str,
        initial_state: Optional[dict] = None,
        initial_phase: str = "init",
    ) -> WorkflowRun:
        """Start a new workflow. Fails if workflow_id already exists."""
        with self._proc_lock:
            if self._events_path(workflow_id).exists():
                raise ValueError(f"Workflow {workflow_id!r} already exists")
            self._wf_dir(workflow_id).mkdir(parents=True, exist_ok=True)
            event = Event(
                event_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                event_type=EventType.WORKFLOW_STARTED,
                timestamp=time.time(),
                sequence=1,
                payload={
                    "initial_state": dict(initial_state or {}),
                    "initial_phase": initial_phase,
                },
                actor="state-machine",
            )
            self._append_event_durable(workflow_id, event)
            run = self.recover(workflow_id)
            return run

    def transition(
        self,
        workflow_id: str,
        event_type: EventType,
        payload: dict,
        actor: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> WorkflowRun:
        """Append an event + update materialized state atomically.

        Concurrent-transition safety: filesystem-mutex prevents two writers
        from interleaving sequence-numbers.
        """
        with self._proc_lock:
            if not self._events_path(workflow_id).exists():
                raise WorkflowNotFoundError(
                    f"Workflow {workflow_id!r} not found (call start_workflow first)"
                )
            self._acquire_fs_lock(workflow_id)
            try:
                # Re-derive sequence under lock to avoid races
                events = self._read_events(workflow_id)
                next_seq = (events[-1].sequence + 1) if events else 1
                event = Event(
                    event_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type=event_type,
                    timestamp=time.time(),
                    sequence=next_seq,
                    payload=dict(payload or {}),
                    actor=actor,
                    correlation_id=correlation_id,
                )
                self._append_event_durable(workflow_id, event)
                # Auto-snapshot every N events
                if next_seq % self.snapshot_every_n_events == 0:
                    run = self.recover(workflow_id)
                    target = self._snapshots_dir(workflow_id) / f"{run.sequence:010d}.json"
                    self._atomic_write_json(target, run.to_dict())
                return self.recover(workflow_id)
            finally:
                self._release_fs_lock(workflow_id)

    def transition_phase(
        self,
        workflow_id: str,
        from_phase: str,
        to_phase: str,
        state_patch: Optional[dict] = None,
        actor: Optional[str] = None,
    ) -> WorkflowRun:
        """Convenience: emit a STATE_TRANSITION event."""
        return self.transition(
            workflow_id=workflow_id,
            event_type=EventType.STATE_TRANSITION,
            payload={
                "from_phase": from_phase,
                "to_phase": to_phase,
                "state_patch": dict(state_patch or {}),
            },
            actor=actor,
        )

    def recover(self, workflow_id: str) -> WorkflowRun:
        """Load latest snapshot + replay newer events. Materialize current state."""
        if not self._events_path(workflow_id).exists():
            raise WorkflowNotFoundError(f"Workflow {workflow_id!r} not found")

        snapshot = self._latest_snapshot(workflow_id)
        if snapshot is not None:
            run = snapshot
        else:
            run = WorkflowRun(
                workflow_id=workflow_id,
                current_phase="init",
                status=WorkflowStatus.PENDING,
            )

        events = self._read_events(workflow_id)
        for e in events:
            if e.sequence <= run.sequence:
                continue
            self._apply_event(run, e)
        return run

    def get_history(self, workflow_id: str) -> list[Event]:
        """Return all events in sequence-order."""
        if not self._events_path(workflow_id).exists():
            raise WorkflowNotFoundError(f"Workflow {workflow_id!r} not found")
        return self._read_events(workflow_id)

    def list_workflows(self) -> list[str]:
        """Enumerate workflow_ids that have events.jsonl."""
        out: list[str] = []
        if not self.state_root.exists():
            return out
        for child in sorted(self.state_root.iterdir()):
            if child.is_dir() and (child / "events.jsonl").exists():
                out.append(child.name)
        return out
