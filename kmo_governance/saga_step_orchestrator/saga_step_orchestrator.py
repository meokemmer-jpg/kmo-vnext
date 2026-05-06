"""KMO Saga-Step-Orchestrator [CRUX-MK].

Welle-12 Phase-7 Modul: Cross-DF-Saga-Step-Coordinator.

Bio-Aequivalent: Mitose-Phasen-Sequencing (synchronisierte Multi-Step-Abfolge).

Pattern-Inspiration:
- saga-pattern/kmo_saga_engine.py (existing Saga-Engine mit do/undo, KEIN Konflikt)
- df_bus_orchestrator (Cross-DF-Bus = Hormonsystem; Saga-Steps = Mitose-Phasen)
- wound_healing/wound_healing_lifecycle.py (4-Phase-Lifecycle als Skeleton-Pattern)

Unterschied zu kmo_saga_engine.py:
- kmo_saga_engine: linear ordered phases (idx-basiert)
- saga_step_orchestrator: DAG-basiert (depends_on Tuple), parallele Branches moeglich

CRUX-Bindung:
- K_0: rollback_on_failure via reverse-DAG-compensation (kein Partial-Commit)
- Q_0: Retry-Policy + Timeout-Handling verhindert silent-fail
- I_min: DAG-Validation (no cycles, all deps resolved) Pre-Run
- W_0: Topological-Sort vermeidet redundante Step-Re-Runs

Usage:
    >>> graph = SagaStepGraph()
    >>> graph.add_step(SagaStep("s1", "Step1", forward_fn=fn1))
    >>> graph.add_step(SagaStep("s2", "Step2", forward_fn=fn2, depends_on=("s1",)))
    >>> graph.validate_dag()
    >>> orch = SagaStepOrchestrator()
    >>> orch.register_graph(graph)
    >>> results = orch.run()
"""

from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CycleDetectedError(Exception):
    """DAG-Validation: Zyklus im depends_on-Graph detektiert."""


class MissingDependencyError(Exception):
    """DAG-Validation: depends_on referenziert nicht-existierenden step_id."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StepStatus(str, enum.Enum):
    """Lifecycle-Status eines SagaStep."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """Retry-Verhalten fuer einzelne SagaStep-Ausfuehrung.

    Pre-Conditions:
        max_retries >= 0
        backoff_base_s >= 0
        backoff_factor >= 1.0
        jitter_factor in [0, 1]

    Post-Conditions:
        Frozen / hashable.
    """

    max_retries: int = 3
    backoff_base_s: float = 0.01
    backoff_factor: float = 2.0
    jitter_factor: float = 0.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.backoff_base_s < 0:
            raise ValueError("backoff_base_s must be >= 0")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")
        if not (0.0 <= self.jitter_factor <= 1.0):
            raise ValueError("jitter_factor must be in [0, 1]")


DEFAULT_RETRY_POLICY = RetryPolicy(max_retries=0, backoff_base_s=0.0, backoff_factor=1.0)


@dataclass(frozen=True)
class SagaStep:
    """Single step in a saga-step-graph.

    Pre-Conditions:
        step_id non-empty.
        forward_fn callable.
        compensate_fn None or callable.
        timeout_s > 0.
        max_retries >= 0.

    Post-Conditions:
        Frozen / hashable.

    Notes:
        - depends_on is a tuple (frozen) of step_ids.
        - forward_fn signature: () -> Any (result stored in SagaStepResult.result).
        - compensate_fn signature: (forward_result: Any) -> None.
    """

    step_id: str
    name: str
    forward_fn: Callable[[], Any]
    compensate_fn: Optional[Callable[[Any], None]] = None
    timeout_s: float = 30.0
    depends_on: tuple[str, ...] = ()
    max_retries: int = 0

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id must be non-empty")
        if not callable(self.forward_fn):
            raise ValueError("forward_fn must be callable")
        if self.compensate_fn is not None and not callable(self.compensate_fn):
            raise ValueError("compensate_fn must be callable or None")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")


@dataclass(frozen=True)
class SagaStepResult:
    """Outcome eines einzelnen SagaStep.

    Frozen / hashable. status entscheidet ob compensate_fn lauft.
    """

    step_id: str
    status: StepStatus
    result: Any = None
    error: Optional[str] = None
    duration_s: float = 0.0
    attempts: int = 0


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------


class SagaStepGraph:
    """DAG of SagaSteps with topological-sort + cycle-detection.

    Thread-safe via internal RLock.
    """

    def __init__(self) -> None:
        self._steps: dict[str, SagaStep] = {}
        self._lock = threading.RLock()

    def add_step(self, step: SagaStep) -> None:
        """Register step. Pre: step.step_id not yet present.

        Post: step is in graph, retrievable via get_step.
        """
        with self._lock:
            if step.step_id in self._steps:
                raise ValueError(f"step_id '{step.step_id}' already registered")
            self._steps[step.step_id] = step

    def get_step(self, step_id: str) -> SagaStep:
        """Lookup step by id. Raises KeyError if absent."""
        with self._lock:
            if step_id not in self._steps:
                raise KeyError(f"step_id '{step_id}' not found")
            return self._steps[step_id]

    def all_step_ids(self) -> tuple[str, ...]:
        """Snapshot of registered step_ids (insertion-order stable)."""
        with self._lock:
            return tuple(self._steps.keys())

    def validate_dag(self) -> None:
        """Pruefe DAG-Eigenschaften: alle Dependencies resolved, kein Zyklus.

        Raises:
            MissingDependencyError: depends_on points to unknown step.
            CycleDetectedError: cycle in dependency graph.
        """
        with self._lock:
            # Check all dependencies resolved
            for step in self._steps.values():
                for dep_id in step.depends_on:
                    if dep_id not in self._steps:
                        raise MissingDependencyError(
                            f"step '{step.step_id}' depends on unknown step '{dep_id}'"
                        )

            # Cycle-detection via DFS with three colors
            WHITE, GRAY, BLACK = 0, 1, 2
            color: dict[str, int] = {sid: WHITE for sid in self._steps}

            def dfs(node: str) -> None:
                color[node] = GRAY
                for dep_id in self._steps[node].depends_on:
                    if color[dep_id] == GRAY:
                        raise CycleDetectedError(
                            f"cycle detected involving '{node}' -> '{dep_id}'"
                        )
                    if color[dep_id] == WHITE:
                        dfs(dep_id)
                color[node] = BLACK

            for sid in self._steps:
                if color[sid] == WHITE:
                    dfs(sid)

    def topological_sort(self) -> list[SagaStep]:
        """Return steps in topological order (Kahn's algorithm).

        Pre: validate_dag() passes.
        Post: returned list satisfies: for each step, all depends_on appear earlier.
        """
        with self._lock:
            self.validate_dag()

            # Build reverse edges: dep_id -> [dependent_step_id, ...]
            in_degree: dict[str, int] = {sid: 0 for sid in self._steps}
            forward_edges: dict[str, list[str]] = {sid: [] for sid in self._steps}
            for step in self._steps.values():
                for dep_id in step.depends_on:
                    in_degree[step.step_id] += 1
                    forward_edges[dep_id].append(step.step_id)

            # Kahn's: queue of zero-in-degree nodes (preserve insertion order)
            queue: deque[str] = deque(
                sid for sid in self._steps if in_degree[sid] == 0
            )
            ordered: list[SagaStep] = []
            while queue:
                sid = queue.popleft()
                ordered.append(self._steps[sid])
                for dependent in forward_edges[sid]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            if len(ordered) != len(self._steps):
                # validate_dag should have caught this, but defensive
                raise CycleDetectedError("topological_sort failed: cycle present")
            return ordered


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class SagaStepOrchestrator:
    """Executes SagaStepGraph with retry + timeout + compensation.

    Thread-safe via RLock. Run / compensate are mutually exclusive.

    Lifecycle:
        register_graph(graph) -> run() -> [compensate(failed_step_id) if needed]
    """

    def __init__(self, retry_policy: Optional[RetryPolicy] = None) -> None:
        self._lock = threading.RLock()
        self._graph: Optional[SagaStepGraph] = None
        self._results: dict[str, SagaStepResult] = {}
        self._retry_policy: RetryPolicy = retry_policy or DEFAULT_RETRY_POLICY

    def register_graph(self, graph: SagaStepGraph) -> None:
        """Bind graph to orchestrator. Re-registration resets results."""
        with self._lock:
            graph.validate_dag()
            self._graph = graph
            self._results = {}

    def get_results(self) -> dict[str, SagaStepResult]:
        """Snapshot of step_id -> SagaStepResult (post-run)."""
        with self._lock:
            return dict(self._results)

    def run(self) -> list[SagaStepResult]:
        """Execute steps in topological order.

        Pre: register_graph() called.

        Post:
            Each step is COMPLETED, FAILED, or SKIPPED (if predecessor failed).
            self._results contains every registered step_id.

        Returns:
            List of SagaStepResult in execution-order.
        """
        with self._lock:
            if self._graph is None:
                raise RuntimeError("register_graph() must be called before run()")

            ordered = self._graph.topological_sort()
            self._results = {}

            failed_step_ids: set[str] = set()

            for step in ordered:
                # Skip if any dependency failed or was skipped
                if any(
                    dep_id in failed_step_ids for dep_id in step.depends_on
                ):
                    self._results[step.step_id] = SagaStepResult(
                        step_id=step.step_id,
                        status=StepStatus.SKIPPED,
                        attempts=0,
                    )
                    failed_step_ids.add(step.step_id)
                    continue

                result = self._execute_step(step)
                self._results[step.step_id] = result
                if result.status == StepStatus.FAILED:
                    failed_step_ids.add(step.step_id)

            return [self._results[s.step_id] for s in ordered]

    def compensate(self, failed_step_id: str) -> list[SagaStepResult]:
        """Run compensate_fn for all COMPLETED predecessors of failed_step_id
        in reverse topological order.

        Pre: run() must have been called and self._results populated.
            failed_step_id must be a registered step.

        Post:
            Each compensated step's status updated to COMPENSATED.

        Returns:
            List of SagaStepResult for compensated steps in compensation-order.
        """
        with self._lock:
            if self._graph is None:
                raise RuntimeError("register_graph() must be called before compensate()")
            if failed_step_id not in self._graph.all_step_ids():
                raise KeyError(f"unknown step_id '{failed_step_id}'")
            if not self._results:
                raise RuntimeError("compensate() requires prior run()")

            ordered = self._graph.topological_sort()
            # Compensate everything COMPLETED in reverse topological order
            compensated: list[SagaStepResult] = []
            for step in reversed(ordered):
                prior = self._results.get(step.step_id)
                if prior is None or prior.status != StepStatus.COMPLETED:
                    continue
                # Skip the failed step itself (it never produced a forward-result)
                if step.step_id == failed_step_id:
                    continue
                if step.compensate_fn is None:
                    # Mark as compensated (no-op) for accounting
                    new_result = SagaStepResult(
                        step_id=step.step_id,
                        status=StepStatus.COMPENSATED,
                        result=prior.result,
                        duration_s=0.0,
                        attempts=prior.attempts,
                    )
                else:
                    start = time.monotonic()
                    try:
                        step.compensate_fn(prior.result)
                        duration = time.monotonic() - start
                        new_result = SagaStepResult(
                            step_id=step.step_id,
                            status=StepStatus.COMPENSATED,
                            result=prior.result,
                            duration_s=duration,
                            attempts=prior.attempts,
                        )
                    except Exception as exc:  # noqa: BLE001 - aggregate any compensation error
                        duration = time.monotonic() - start
                        new_result = SagaStepResult(
                            step_id=step.step_id,
                            status=StepStatus.FAILED,
                            error=f"compensation-failed: {exc}",
                            duration_s=duration,
                            attempts=prior.attempts,
                        )
                self._results[step.step_id] = new_result
                compensated.append(new_result)

            return compensated

    # -- internals --

    def _execute_step(self, step: SagaStep) -> SagaStepResult:
        """Run a single step with retry / timeout."""
        max_attempts = max(1, step.max_retries + 1)
        start = time.monotonic()
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            attempt_start = time.monotonic()
            try:
                # Cooperative timeout: we cannot kill arbitrary functions in
                # stdlib without signal/multiprocessing. We measure post-hoc
                # and mark FAILED if the call exceeded timeout_s.
                result = step.forward_fn()
                attempt_duration = time.monotonic() - attempt_start
                if attempt_duration > step.timeout_s:
                    last_error = (
                        f"timeout: {attempt_duration:.3f}s > {step.timeout_s}s"
                    )
                    if attempt < max_attempts:
                        time.sleep(self._retry_policy.backoff_base_s)
                        continue
                    return SagaStepResult(
                        step_id=step.step_id,
                        status=StepStatus.FAILED,
                        error=last_error,
                        duration_s=time.monotonic() - start,
                        attempts=attempt,
                    )
                return SagaStepResult(
                    step_id=step.step_id,
                    status=StepStatus.COMPLETED,
                    result=result,
                    duration_s=time.monotonic() - start,
                    attempts=attempt,
                )
            except Exception as exc:  # noqa: BLE001 - aggregate any forward error
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < max_attempts:
                    time.sleep(self._retry_policy.backoff_base_s)
                    continue
                return SagaStepResult(
                    step_id=step.step_id,
                    status=StepStatus.FAILED,
                    error=last_error,
                    duration_s=time.monotonic() - start,
                    attempts=attempt,
                )

        # Unreachable, but defensive
        return SagaStepResult(
            step_id=step.step_id,
            status=StepStatus.FAILED,
            error=last_error or "unknown",
            duration_s=time.monotonic() - start,
            attempts=max_attempts,
        )


# CRUX-MK
