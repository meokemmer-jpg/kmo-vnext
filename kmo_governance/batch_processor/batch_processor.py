"""KMO Batch-Processor [CRUX-MK].

Welle-21 Phase-14 Modul-2/2: Bulk-Operations mit Progress-Tracking + Failure-Isolation.

Bio-Aequivalent: Peristaltische-Wellen (Verdauungs-Trakt).
    Bolus-Bildung    -> submit() konsolidiert Items zu Batch.
    Peristaltik      -> chunked synchroner Item-Lauf (chunk_size).
    Pause-Reflex     -> pause()/resume() unterbrechen die Welle.
    Skip-Reflex      -> Per-Item-Failure isoliert (SKIPPED), max_failures terminiert.
    Progress-Marker  -> BatchProgress liefert percent_complete + ETA.

Komplement zu saga_step_orchestrator:
- saga_step_orchestrator: ordered DAG-Steps mit Compensation
- batch_processor: bulk Items, alle gleichartig, Failure-Isolation pro Item

CRUX-Bindung:
- K_0: max_failures-Threshold stoppt Batch vor Fehler-Kaskade.
- Q_0: Per-Item-Status verhindert silent-fail.
- I_min: Frozen-Dataclasses + RLock garantieren Status-Konsistenz.
- W_0: Chunked-Execution + ETA erlauben Pareto-aware Pause-Decisions.
"""

from __future__ import annotations

import enum
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional


class ItemStatus(str, enum.Enum):
    """Lifecycle-Status eines einzelnen Item im Batch."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class BatchStatus(str, enum.Enum):
    """Lifecycle-Status eines kompletten Batch."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ItemResult:
    """Outcome eines einzelnen Item-Processing. Frozen / hashable."""

    item_id: str
    status: ItemStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    elapsed_s: float = 0.0
    attempt_number: int = 1


@dataclass(frozen=True)
class BatchProgress:
    """Aktueller Progress-Snapshot. Frozen / hashable."""

    batch_id: str
    status: BatchStatus
    total_items: int
    completed: int
    failed: int
    skipped: int
    percent_complete: float
    elapsed_s: float
    eta_s: Optional[float] = None


@dataclass(frozen=True)
class BatchResult:
    """Endgueltiges Batch-Ergebnis. Frozen / hashable (items als tuple)."""

    batch_id: str
    status: BatchStatus
    total_items: int
    items: tuple[ItemResult, ...]
    aggregate_elapsed_s: float
    completion_timestamp: float


@dataclass
class _BatchState:
    """Mutable internal state per Batch (nicht in Public-API)."""

    batch_id: str
    items: list[Any]
    processor_fn: Callable[[Any], Any]
    max_failures: int
    chunk_size: int
    status: BatchStatus = BatchStatus.CREATED
    item_results: list[ItemResult] = field(default_factory=list)
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    pause_requested: bool = False
    cancel_requested: bool = False


class BatchProcessor:
    """Bulk-Item-Executor mit Progress-Tracking + Failure-Isolation.

    Thread-safe via RLock. submit() ist synchron (blockiert bis terminal).
    Multiple concurrent submit() werden isoliert verfolgt (state pro batch_id).

    Lifecycle:
        submit(items, processor_fn) -> batch_id   (synchron, terminal-blocking)
        get_progress(batch_id)      -> BatchProgress
        get_result(batch_id)        -> BatchResult (only after terminal)
        pause/resume/cancel(batch_id) -> BatchProgress
    """

    def __init__(
        self,
        default_max_failures: int = 0,
        default_chunk_size: int = 100,
    ) -> None:
        if default_max_failures < 0:
            raise ValueError("default_max_failures must be >= 0")
        if default_chunk_size < 1:
            raise ValueError("default_chunk_size must be >= 1")
        self._lock = threading.RLock()
        self._batches: dict[str, _BatchState] = {}
        self._default_max_failures = default_max_failures
        self._default_chunk_size = default_chunk_size

    def submit(
        self,
        items: Iterable[Any],
        processor_fn: Callable[[Any], Any],
        batch_id: Optional[str] = None,
        max_failures: Optional[int] = None,
        chunk_size: Optional[int] = None,
    ) -> str:
        """Submit a batch synchronously. Blocks until terminal state.

        Pre: items non-empty; processor_fn callable; max_failures None or >= 0;
        chunk_size None or >= 1.

        Post: batch_id registered; state.status in {COMPLETED, FAILED, CANCELLED, PAUSED}.
        """
        items_list = list(items)
        if not items_list:
            raise ValueError("items must be non-empty")
        if not callable(processor_fn):
            raise ValueError("processor_fn must be callable")

        eff_max_fail = (
            max_failures if max_failures is not None else self._default_max_failures
        )
        if eff_max_fail < 0:
            raise ValueError("max_failures must be >= 0")
        eff_chunk = chunk_size if chunk_size is not None else self._default_chunk_size
        if eff_chunk < 1:
            raise ValueError("chunk_size must be >= 1")

        bid = batch_id or str(uuid.uuid4())
        with self._lock:
            if bid in self._batches:
                raise ValueError(f"batch_id '{bid}' already registered")
            self._batches[bid] = _BatchState(
                batch_id=bid,
                items=items_list,
                processor_fn=processor_fn,
                max_failures=eff_max_fail,
                chunk_size=eff_chunk,
            )

        self._run_batch(bid)
        return bid

    def get_progress(self, batch_id: str) -> BatchProgress:
        """Snapshot current progress. Pre: batch_id registered."""
        with self._lock:
            return self._snapshot_progress(self._require(batch_id))

    def get_result(self, batch_id: str) -> BatchResult:
        """Final result. Pre: state in terminal status. Raises RuntimeError otherwise."""
        with self._lock:
            state = self._require(batch_id)
            if state.status not in (
                BatchStatus.COMPLETED,
                BatchStatus.FAILED,
                BatchStatus.CANCELLED,
            ):
                raise RuntimeError(
                    f"batch '{batch_id}' not terminal (status={state.status.value})"
                )
            elapsed = state.end_time - state.start_time if state.start_time else 0.0
            return BatchResult(
                batch_id=state.batch_id,
                status=state.status,
                total_items=len(state.items),
                items=tuple(state.item_results),
                aggregate_elapsed_s=elapsed,
                completion_timestamp=state.end_time,
            )

    def pause(self, batch_id: str) -> BatchProgress:
        """Request pause (effective at next chunk-boundary). Synchronous-submit:
        only effective if called from another thread."""
        with self._lock:
            state = self._require(batch_id)
            if state.status == BatchStatus.RUNNING:
                state.pause_requested = True
            return self._snapshot_progress(state)

    def resume(self, batch_id: str) -> BatchProgress:
        """Reset pause flag. Caller must re-invoke run if state PAUSED."""
        with self._lock:
            state = self._require(batch_id)
            state.pause_requested = False
            if state.status == BatchStatus.PAUSED:
                state.status = BatchStatus.RUNNING
            return self._snapshot_progress(state)

    def cancel(self, batch_id: str) -> BatchProgress:
        """Request cancellation (effective at next chunk-boundary)."""
        with self._lock:
            state = self._require(batch_id)
            state.cancel_requested = True
            return self._snapshot_progress(state)

    def list_batches(self) -> list[str]:
        """Snapshot of all registered batch_ids (insertion-order stable)."""
        with self._lock:
            return list(self._batches.keys())

    # -- internals --

    def _require(self, batch_id: str) -> _BatchState:
        if batch_id not in self._batches:
            raise KeyError(f"unknown batch_id '{batch_id}'")
        return self._batches[batch_id]

    def _snapshot_progress(self, state: _BatchState) -> BatchProgress:
        total = len(state.items)
        done = state.completed_count + state.failed_count + state.skipped_count
        percent = (done / total * 100.0) if total else 100.0

        if state.start_time == 0.0:
            elapsed = 0.0
        elif state.end_time:
            elapsed = state.end_time - state.start_time
        else:
            elapsed = time.monotonic() - state.start_time

        eta: Optional[float] = None
        if done > 0 and elapsed > 0 and done < total:
            eta = (elapsed / done) * (total - done)

        return BatchProgress(
            batch_id=state.batch_id,
            status=state.status,
            total_items=total,
            completed=state.completed_count,
            failed=state.failed_count,
            skipped=state.skipped_count,
            percent_complete=percent,
            elapsed_s=elapsed,
            eta_s=eta,
        )

    def _run_batch(self, batch_id: str) -> None:
        """Synchronous run-loop. Releases RLock during processor_fn calls so
        pause/cancel from another thread take effect at chunk-boundaries."""
        with self._lock:
            state = self._batches[batch_id]
            state.status = BatchStatus.RUNNING
            state.start_time = time.monotonic()

        idx = 0
        total = len(state.items)
        while idx < total:
            with self._lock:
                if state.cancel_requested:
                    state.status = BatchStatus.CANCELLED
                    state.end_time = time.monotonic()
                    return
                if state.pause_requested:
                    state.status = BatchStatus.PAUSED
                    state.end_time = time.monotonic()
                    return

            chunk_end = min(idx + state.chunk_size, total)
            for chunk_idx in range(idx, chunk_end):
                if self._process_one(state, chunk_idx, total):
                    return  # terminal failure
            idx = chunk_end

        with self._lock:
            state.status = BatchStatus.COMPLETED
            state.end_time = time.monotonic()

    def _process_one(self, state: _BatchState, chunk_idx: int, total: int) -> bool:
        """Process one item. Returns True iff batch terminated FAILED here."""
        item = state.items[chunk_idx]
        item_id = f"{state.batch_id}-item-{chunk_idx}"
        attempt_start = time.monotonic()
        try:
            output = state.processor_fn(item)
            elapsed = time.monotonic() - attempt_start
            with self._lock:
                state.item_results.append(
                    ItemResult(
                        item_id=item_id,
                        status=ItemStatus.SUCCEEDED,
                        output=output,
                        elapsed_s=elapsed,
                    )
                )
                state.completed_count += 1
            return False
        except Exception as exc:  # noqa: BLE001 - aggregate any processor error
            elapsed = time.monotonic() - attempt_start
            error_msg = f"{type(exc).__name__}: {exc}"
            with self._lock:
                state.item_results.append(
                    ItemResult(
                        item_id=item_id,
                        status=ItemStatus.FAILED,
                        error=error_msg,
                        elapsed_s=elapsed,
                    )
                )
                state.failed_count += 1
                if state.failed_count > state.max_failures:
                    # Skip remaining and terminate FAILED.
                    for skip_idx in range(chunk_idx + 1, total):
                        state.item_results.append(
                            ItemResult(
                                item_id=f"{state.batch_id}-item-{skip_idx}",
                                status=ItemStatus.SKIPPED,
                                error="batch failed: max_failures exceeded",
                                attempt_number=0,
                            )
                        )
                        state.skipped_count += 1
                    state.status = BatchStatus.FAILED
                    state.end_time = time.monotonic()
                    return True
            return False


# CRUX-MK
