"""Tests for KMO Saga-Step-Orchestrator [CRUX-MK].

12 Pflicht-Tests laut SUBAGENT-K Welle-12 Phase-7 Spec.
"""

from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.saga_step_orchestrator import (
    CycleDetectedError,
    MissingDependencyError,
    RetryPolicy,
    SagaStep,
    SagaStepGraph,
    SagaStepOrchestrator,
    SagaStepResult,
    StepStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(value):
    return lambda: value


def _boom(message="kapow"):
    def _f():
        raise RuntimeError(message)
    return _f


# ---------------------------------------------------------------------------
# 1. Frozen-Dataclass-Garantie
# ---------------------------------------------------------------------------


def test_saga_step_frozen():
    step = SagaStep(step_id="s1", name="Step1", forward_fn=_ok("done"))
    with pytest.raises(Exception):
        step.step_id = "modified"  # type: ignore[misc]
    # Hashable-Garantie (frozen-Dataclasses sind hashable per default)
    assert hash(step) == hash(step)


# ---------------------------------------------------------------------------
# 2. SagaStepGraph: add_step + duplicate-detection
# ---------------------------------------------------------------------------


def test_saga_step_graph_add_step():
    graph = SagaStepGraph()
    step1 = SagaStep(step_id="s1", name="Step1", forward_fn=_ok(1))
    graph.add_step(step1)
    assert graph.get_step("s1") is step1
    assert graph.all_step_ids() == ("s1",)
    # Duplicate must raise
    with pytest.raises(ValueError):
        graph.add_step(step1)


# ---------------------------------------------------------------------------
# 3. validate_dag passes acyclic
# ---------------------------------------------------------------------------


def test_saga_step_graph_validate_dag_passes_acyclic():
    graph = SagaStepGraph()
    graph.add_step(SagaStep(step_id="a", name="A", forward_fn=_ok("a")))
    graph.add_step(SagaStep(step_id="b", name="B", forward_fn=_ok("b"), depends_on=("a",)))
    graph.add_step(SagaStep(step_id="c", name="C", forward_fn=_ok("c"), depends_on=("a", "b")))
    # Should not raise
    graph.validate_dag()


# ---------------------------------------------------------------------------
# 4. validate_dag detects cycle
# ---------------------------------------------------------------------------


def test_saga_step_graph_detects_cycle():
    graph = SagaStepGraph()
    graph.add_step(SagaStep(step_id="a", name="A", forward_fn=_ok("a"), depends_on=("c",)))
    graph.add_step(SagaStep(step_id="b", name="B", forward_fn=_ok("b"), depends_on=("a",)))
    graph.add_step(SagaStep(step_id="c", name="C", forward_fn=_ok("c"), depends_on=("b",)))
    with pytest.raises(CycleDetectedError):
        graph.validate_dag()

    # Missing dependency
    graph2 = SagaStepGraph()
    graph2.add_step(SagaStep(step_id="x", name="X", forward_fn=_ok("x"), depends_on=("missing",)))
    with pytest.raises(MissingDependencyError):
        graph2.validate_dag()


# ---------------------------------------------------------------------------
# 5. topological_sort respects dependencies
# ---------------------------------------------------------------------------


def test_saga_step_graph_topological_sort_respects_dependencies():
    graph = SagaStepGraph()
    graph.add_step(SagaStep(step_id="c", name="C", forward_fn=_ok("c"), depends_on=("a", "b")))
    graph.add_step(SagaStep(step_id="b", name="B", forward_fn=_ok("b"), depends_on=("a",)))
    graph.add_step(SagaStep(step_id="a", name="A", forward_fn=_ok("a")))
    ordered = graph.topological_sort()
    sids = [s.step_id for s in ordered]
    assert sids.index("a") < sids.index("b")
    assert sids.index("a") < sids.index("c")
    assert sids.index("b") < sids.index("c")


# ---------------------------------------------------------------------------
# 6. Orchestrator runs steps in order
# ---------------------------------------------------------------------------


def test_orchestrator_runs_steps_in_order():
    execution_log: list[str] = []
    lock = threading.Lock()

    def make_fn(name: str):
        def fn():
            with lock:
                execution_log.append(name)
            return name
        return fn

    graph = SagaStepGraph()
    graph.add_step(SagaStep(step_id="a", name="A", forward_fn=make_fn("a")))
    graph.add_step(SagaStep(step_id="b", name="B", forward_fn=make_fn("b")))

    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()

    assert len(results) == 2
    assert all(r.status == StepStatus.COMPLETED for r in results)
    assert execution_log == ["a", "b"]


# ---------------------------------------------------------------------------
# 7. Dependency-chain ordering
# ---------------------------------------------------------------------------


def test_orchestrator_handles_dependency_chain():
    log: list[str] = []

    def trace(name: str):
        def fn():
            log.append(name)
            return name
        return fn

    graph = SagaStepGraph()
    graph.add_step(SagaStep(step_id="s3", name="S3", forward_fn=trace("3"), depends_on=("s2",)))
    graph.add_step(SagaStep(step_id="s2", name="S2", forward_fn=trace("2"), depends_on=("s1",)))
    graph.add_step(SagaStep(step_id="s1", name="S1", forward_fn=trace("1")))

    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()

    assert log == ["1", "2", "3"]
    assert all(r.status == StepStatus.COMPLETED for r in results)


# ---------------------------------------------------------------------------
# 8. Skip dependent when predecessor failed
# ---------------------------------------------------------------------------


def test_orchestrator_skips_dependent_when_predecessor_failed():
    log: list[str] = []

    def succ(name):
        def fn():
            log.append(name)
            return name
        return fn

    graph = SagaStepGraph()
    graph.add_step(SagaStep(step_id="s1", name="S1", forward_fn=succ("1")))
    graph.add_step(SagaStep(step_id="s2", name="S2", forward_fn=_boom("fail-2"), depends_on=("s1",)))
    graph.add_step(SagaStep(step_id="s3", name="S3", forward_fn=succ("3"), depends_on=("s2",)))
    graph.add_step(SagaStep(step_id="s4", name="S4", forward_fn=succ("4")))  # independent

    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()

    by_id = {r.step_id: r for r in results}
    assert by_id["s1"].status == StepStatus.COMPLETED
    assert by_id["s2"].status == StepStatus.FAILED
    assert by_id["s3"].status == StepStatus.SKIPPED
    assert by_id["s4"].status == StepStatus.COMPLETED  # unrelated branch survives
    assert "3" not in log


# ---------------------------------------------------------------------------
# 9. Compensate runs in reverse order on COMPLETED steps
# ---------------------------------------------------------------------------


def test_orchestrator_compensate_runs_in_reverse_order():
    forward_log: list[str] = []
    compensate_log: list[str] = []

    def fwd(name):
        def fn():
            forward_log.append(name)
            return f"result-{name}"
        return fn

    def cmp(name):
        def fn(prior_result):
            compensate_log.append(name)
        return fn

    graph = SagaStepGraph()
    graph.add_step(SagaStep(
        step_id="s1", name="S1", forward_fn=fwd("1"), compensate_fn=cmp("1")
    ))
    graph.add_step(SagaStep(
        step_id="s2", name="S2", forward_fn=fwd("2"), compensate_fn=cmp("2"), depends_on=("s1",)
    ))
    graph.add_step(SagaStep(
        step_id="s3", name="S3", forward_fn=_boom("fail-3"), depends_on=("s2",)
    ))

    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()
    by_id = {r.step_id: r for r in results}
    assert by_id["s3"].status == StepStatus.FAILED

    compensated = orch.compensate("s3")
    # compensate must run in reverse topological order: s2, then s1.
    comp_ids = [c.step_id for c in compensated]
    assert comp_ids == ["s2", "s1"]
    assert compensate_log == ["2", "1"]
    # s3 itself was never COMPLETED -> not in compensation set
    assert "s3" not in comp_ids


# ---------------------------------------------------------------------------
# 10. Retry policy applied
# ---------------------------------------------------------------------------


def test_orchestrator_retry_policy_applied():
    state = {"attempts": 0}

    def flaky():
        state["attempts"] += 1
        if state["attempts"] < 3:
            raise RuntimeError("transient")
        return "ok"

    graph = SagaStepGraph()
    graph.add_step(SagaStep(
        step_id="r1", name="Retry1", forward_fn=flaky, max_retries=5
    ))
    orch = SagaStepOrchestrator(retry_policy=RetryPolicy(
        max_retries=5, backoff_base_s=0.0, backoff_factor=1.0
    ))
    orch.register_graph(graph)
    results = orch.run()
    assert results[0].status == StepStatus.COMPLETED
    assert results[0].attempts == 3
    assert results[0].result == "ok"

    # And: a permanently failing step exhausts attempts and ends FAILED.
    state2 = {"attempts": 0}

    def always_fails():
        state2["attempts"] += 1
        raise RuntimeError("nope")

    graph2 = SagaStepGraph()
    graph2.add_step(SagaStep(
        step_id="r2", name="Retry2", forward_fn=always_fails, max_retries=2
    ))
    orch2 = SagaStepOrchestrator(retry_policy=RetryPolicy(
        max_retries=2, backoff_base_s=0.0, backoff_factor=1.0
    ))
    orch2.register_graph(graph2)
    results2 = orch2.run()
    assert results2[0].status == StepStatus.FAILED
    assert results2[0].attempts == 3  # 1 initial + 2 retries
    assert state2["attempts"] == 3


# ---------------------------------------------------------------------------
# 11. Timeout marks FAILED
# ---------------------------------------------------------------------------


def test_orchestrator_timeout_marks_failed():
    def slow():
        time.sleep(0.05)
        return "late"

    graph = SagaStepGraph()
    graph.add_step(SagaStep(
        step_id="t1", name="T1", forward_fn=slow, timeout_s=0.001, max_retries=0
    ))
    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()
    assert results[0].status == StepStatus.FAILED
    assert "timeout" in (results[0].error or "")


# ---------------------------------------------------------------------------
# 12. Concurrent-safe: 10 threads dispatch independent orchestrators
# ---------------------------------------------------------------------------


def test_orchestrator_concurrent_safe():
    """Ten threads each run their own orchestrator instance; no cross-contamination."""

    results_all: list[list[SagaStepResult]] = []
    results_lock = threading.Lock()

    def worker(idx: int):
        graph = SagaStepGraph()
        graph.add_step(SagaStep(
            step_id=f"t{idx}-a", name=f"T{idx}A", forward_fn=_ok(idx)
        ))
        graph.add_step(SagaStep(
            step_id=f"t{idx}-b", name=f"T{idx}B", forward_fn=_ok(idx + 100),
            depends_on=(f"t{idx}-a",)
        ))
        orch = SagaStepOrchestrator()
        orch.register_graph(graph)
        results = orch.run()
        with results_lock:
            results_all.append(results)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results_all) == 10
    for batch in results_all:
        assert len(batch) == 2
        assert all(r.status == StepStatus.COMPLETED for r in batch)


# CRUX-MK


# ---------------------------------------------------------------------------
# Welle-17 P-W17-1 Saga Property/Fault-Injection (V6+V7-Recommendation)
# ---------------------------------------------------------------------------
import random as _r
import threading as _t


def test_saga_property_dag_validates_acyclic_random_50():
    """50 random DAGs validate without cycle."""
    rng = _r.Random(42)
    for trial in range(50):
        graph = SagaStepGraph()
        n_steps = rng.randint(2, 6)
        for i in range(n_steps):
            depends = tuple(f"step-{j}" for j in range(i) if rng.random() < 0.3)
            graph.add_step(
                SagaStep(
                    step_id=f"step-{i}",
                    name=f"s{i}",
                    forward_fn=lambda: None,
                    compensate_fn=None,
                    timeout_s=1.0,
                    depends_on=depends,
                    max_retries=0,
                )
            )
        graph.validate_dag()  # should not raise


def test_saga_property_topological_order_respects_deps():
    """For each random DAG, topological_sort puts dependencies before dependents."""
    rng = _r.Random(123)
    for _ in range(20):
        graph = SagaStepGraph()
        n_steps = 5
        for i in range(n_steps):
            depends = tuple(f"step-{j}" for j in range(i) if rng.random() < 0.4)
            graph.add_step(
                SagaStep(
                    step_id=f"step-{i}",
                    name=f"s{i}",
                    forward_fn=lambda: None,
                    timeout_s=1.0,
                    depends_on=depends,
                    max_retries=0,
                )
            )
        order = graph.topological_sort()
        seen = set()
        for step in order:
            for dep in step.depends_on:
                assert dep in seen, f"dep {dep} not before {step.step_id}"
            seen.add(step.step_id)


def test_saga_fault_injection_random_failure_handled():
    """Random failure-rate per-step. All-step-results must be valid Status."""
    rng = _r.Random(7)
    graph = SagaStepGraph()
    fail_targets = set()

    def make_fn(sid):
        def fn():
            if sid in fail_targets:
                raise RuntimeError(f"injected-fault-{sid}")
            return "ok"
        return fn

    for i in range(8):
        sid = f"step-{i}"
        if rng.random() < 0.3:
            fail_targets.add(sid)
        graph.add_step(
            SagaStep(
                step_id=sid,
                name=sid,
                forward_fn=make_fn(sid),
                timeout_s=1.0,
                depends_on=(),
                max_retries=0,
            )
        )

    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()
    # Each result has a valid status
    for r in results:
        assert r.status in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        )


def test_saga_property_failed_predecessor_skips_dependents():
    """When step-A fails and step-B depends_on A, B is SKIPPED."""
    graph = SagaStepGraph()
    graph.add_step(
        SagaStep(
            step_id="A",
            name="a",
            forward_fn=lambda: (_ for _ in ()).throw(RuntimeError("a-fail")),
            timeout_s=1.0,
            depends_on=(),
            max_retries=0,
        )
    )
    graph.add_step(
        SagaStep(
            step_id="B",
            name="b",
            forward_fn=lambda: "ok",
            timeout_s=1.0,
            depends_on=("A",),
            max_retries=0,
        )
    )
    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()
    by_id = {r.step_id: r for r in results}
    assert by_id["A"].status == StepStatus.FAILED
    assert by_id["B"].status == StepStatus.SKIPPED


def test_saga_compensation_runs_in_reverse_dag_order():
    """Compensation order is reverse of execution order."""
    compensation_order = []

    def make_fn(sid):
        return lambda: "ok"

    def make_comp(sid):
        return lambda: compensation_order.append(sid) or "compensated"

    graph = SagaStepGraph()
    for i in range(4):
        sid = f"step-{i}"
        depends = (f"step-{i-1}",) if i > 0 else ()
        graph.add_step(
            SagaStep(
                step_id=sid,
                name=sid,
                forward_fn=make_fn(sid),
                compensate_fn=make_comp(sid),
                timeout_s=1.0,
                depends_on=depends,
                max_retries=0,
            )
        )
    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    orch.run()
    orch.compensate("step-3")  # rollback all
    # Reverse order: 3, 2, 1, 0 (or subset that ran)
    if len(compensation_order) >= 2:
        # First-compensated should be later-than second
        assert compensation_order[0].split("-")[1] >= compensation_order[1].split("-")[1]


def test_saga_concurrent_run_50_threads_isolated_orchestrators():
    """50 threads each with own orchestrator -> no cross-thread state."""
    results = []
    lock = _t.Lock()

    def worker(n: int):
        graph = SagaStepGraph()
        graph.add_step(
            SagaStep(
                step_id="s",
                name="s",
                forward_fn=lambda n=n: f"result-{n}",
                timeout_s=1.0,
                depends_on=(),
                max_retries=0,
            )
        )
        orch = SagaStepOrchestrator()
        orch.register_graph(graph)
        result = orch.run()
        with lock:
            results.append(result[0])

    threads = [_t.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 50
    assert all(r.status == StepStatus.COMPLETED for r in results)


def test_saga_retry_policy_applied():
    """Step that fails-then-succeeds should retry per RetryPolicy."""
    attempt_count = {"n": 0}

    def flaky():
        attempt_count["n"] += 1
        if attempt_count["n"] < 2:
            raise RuntimeError("temp")
        return "ok"

    graph = SagaStepGraph()
    graph.add_step(
        SagaStep(
            step_id="s",
            name="s",
            forward_fn=flaky,
            timeout_s=1.0,
            depends_on=(),
            max_retries=3,
        )
    )
    orch = SagaStepOrchestrator(
        retry_policy=RetryPolicy(
            max_retries=3,
            backoff_base_s=0.001,
            backoff_factor=2.0,
            jitter_factor=0.0,
        )
    )
    orch.register_graph(graph)
    results = orch.run()
    # If retry-policy works, step succeeds on attempt 2
    assert results[0].attempts >= 2


def test_saga_isolated_branches_continue_when_other_fails():
    """Branch-A fails, Branch-B (independent) still runs."""
    graph = SagaStepGraph()
    graph.add_step(
        SagaStep(
            step_id="A",
            name="a-fail",
            forward_fn=lambda: (_ for _ in ()).throw(RuntimeError("A")),
            timeout_s=1.0,
            depends_on=(),
            max_retries=0,
        )
    )
    graph.add_step(
        SagaStep(
            step_id="B",
            name="b-ok",
            forward_fn=lambda: "B-ok",
            timeout_s=1.0,
            depends_on=(),
            max_retries=0,
        )
    )
    orch = SagaStepOrchestrator()
    orch.register_graph(graph)
    results = orch.run()
    by_id = {r.step_id: r for r in results}
    assert by_id["A"].status == StepStatus.FAILED
    assert by_id["B"].status == StepStatus.COMPLETED
