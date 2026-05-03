"""KMO Wound-Healing Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-1.2.3 (Tests-Block).

Pflicht (7):
- test_wound_healing_4_phase_sequence
- test_wound_healing_hemostasis_circuit_break
- test_wound_healing_inflammation_cleanup
- test_wound_healing_proliferation_restart
- test_wound_healing_remodeling_optimization
- test_wound_healing_integrates_with_saga_compensation
- test_wound_healing_mttr_metrics
"""

from __future__ import annotations

import pytest

from kmo_governance.wound_healing import (
    HealingContext,
    HealingPhase,
    PhaseTransitionError,
    WoundHealingLifecycle,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def fixed_clock():
    state = {"t": 1_000_000.0}

    def clock():
        return state["t"]

    def tick(dt):
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def healing(fixed_clock):
    return WoundHealingLifecycle(
        saga_run_id="run-1", hotel_id="hotel-A", clock=fixed_clock
    )


# ---------------- Pflicht-Tests ----------------


def test_wound_healing_4_phase_sequence(healing, fixed_clock):
    """Forward-only 4-phase walk: NOT_STARTED -> H -> I -> P -> R -> HEALED."""
    assert healing.phase == HealingPhase.NOT_STARTED
    healing.start_hemostasis("phase-3-timeout")
    assert healing.phase == HealingPhase.HEMOSTASIS
    fixed_clock.tick(2.0)
    healing.transition_to_inflammation()
    assert healing.phase == HealingPhase.INFLAMMATION
    fixed_clock.tick(5.0)
    healing.transition_to_proliferation()
    assert healing.phase == HealingPhase.PROLIFERATION
    fixed_clock.tick(3.0)
    healing.transition_to_remodeling()
    assert healing.phase == HealingPhase.REMODELING
    fixed_clock.tick(4.0)
    healing.complete()
    assert healing.phase == HealingPhase.HEALED
    # 5 transitions logged: H, I, P, R, HEALED (NOT_STARTED is implicit)
    assert len(healing.context.phase_log) == 5


def test_wound_healing_hemostasis_circuit_break(healing):
    """Hemostasis records failure_reason; illegal back-transition raises."""
    healing.start_hemostasis("payment-gateway-down")
    assert healing.phase == HealingPhase.HEMOSTASIS
    assert healing.context.failure_reason == "payment-gateway-down"
    # Illegal: cannot go backward
    with pytest.raises(PhaseTransitionError):
        healing.start_hemostasis("again")
    # Illegal: cannot skip phases (HEMOSTASIS -> PROLIFERATION not allowed)
    with pytest.raises(PhaseTransitionError):
        healing.transition_to_proliferation()


def test_wound_healing_inflammation_cleanup(fixed_clock):
    """Inflammation phase invokes cleanup_callback with HealingContext."""
    cleanup_called: list[HealingContext] = []

    def cleanup(ctx: HealingContext) -> None:
        cleanup_called.append(ctx)
        ctx.cleanup_artifacts.append("freed-lock-X")

    h = WoundHealingLifecycle(
        saga_run_id="run-1",
        hotel_id="hotel-A",
        cleanup_callback=cleanup,
        clock=fixed_clock,
    )
    h.start_hemostasis("crash")
    h.transition_to_inflammation()
    assert len(cleanup_called) == 1
    assert cleanup_called[0].saga_run_id == "run-1"
    assert h.context.cleanup_artifacts == ["freed-lock-X"]


def test_wound_healing_proliferation_restart(fixed_clock):
    """Proliferation invokes restart_callback + increments restart_attempts."""
    restart_called: list[int] = []

    def restart(ctx: HealingContext) -> None:
        restart_called.append(ctx.restart_attempts)

    h = WoundHealingLifecycle(
        saga_run_id="run-1", hotel_id="hotel-A",
        restart_callback=restart, clock=fixed_clock,
    )
    h.start_hemostasis("crash")
    h.transition_to_inflammation()
    h.transition_to_proliferation()
    assert h.context.restart_attempts == 1
    assert restart_called == [1]


def test_wound_healing_remodeling_optimization(fixed_clock):
    """Remodeling invokes optimize_callback (gradual re-optimization)."""
    optimize_called: list[bool] = []

    def optimize(ctx: HealingContext) -> None:
        optimize_called.append(True)
        ctx.optimization_notes.append("schema-migration-v2")

    h = WoundHealingLifecycle(
        saga_run_id="run-1", hotel_id="hotel-A",
        optimize_callback=optimize, clock=fixed_clock,
    )
    h.start_hemostasis("c")
    h.transition_to_inflammation()
    h.transition_to_proliferation()
    h.transition_to_remodeling()
    assert optimize_called == [True]
    assert h.context.optimization_notes == ["schema-migration-v2"]


def test_wound_healing_integrates_with_saga_compensation(fixed_clock):
    """Saga-FAILED handler instantiates Wound-Healing instead of direct compensation.

    Simulates: Saga-Engine catches phase-failure -> creates lifecycle -> walks all phases.
    """
    compensation_log: list[str] = []

    def cleanup(ctx: HealingContext) -> None:
        compensation_log.append(f"undo-phase-{ctx.failure_reason}")

    def restart(ctx: HealingContext) -> None:
        compensation_log.append("re-execute-saga")

    h = WoundHealingLifecycle(
        saga_run_id="saga-99",
        hotel_id="hotel-A",
        cleanup_callback=cleanup,
        restart_callback=restart,
        clock=fixed_clock,
    )
    # Simulated Saga-FAILED entry-point
    h.start_hemostasis("phase-3-failed")
    h.transition_to_inflammation()
    h.transition_to_proliferation()
    h.transition_to_remodeling()
    h.complete()

    assert h.phase == HealingPhase.HEALED
    assert compensation_log == ["undo-phase-phase-3-failed", "re-execute-saga"]
    assert h.context.restart_attempts == 1


def test_wound_healing_mttr_metrics(healing, fixed_clock):
    """MTTR (Mean-Time-To-Recovery) recorded per-phase + total."""
    healing.start_hemostasis("c")
    fixed_clock.tick(2.0)
    healing.transition_to_inflammation()  # records HEMOSTASIS-duration
    fixed_clock.tick(5.0)
    healing.transition_to_proliferation()  # records INFLAMMATION-duration
    fixed_clock.tick(3.0)
    healing.transition_to_remodeling()  # records PROLIFERATION-duration
    fixed_clock.tick(4.0)
    healing.complete()  # records REMODELING-duration + total

    snap = healing.metrics.snapshot()
    assert snap["total_count"] == 1
    assert snap["avg_total_mttr_sec"] == pytest.approx(14.0)  # 2+5+3+4
    assert snap["avg_phase_duration_sec"][str(HealingPhase.HEMOSTASIS)] == pytest.approx(2.0)
    assert snap["avg_phase_duration_sec"][str(HealingPhase.INFLAMMATION)] == pytest.approx(5.0)


# ---------------- Edge: Abort path ----------------


def test_wound_healing_abort_terminal(healing):
    """Abort transitions to terminal ABORTED; further transitions raise."""
    healing.start_hemostasis("c")
    healing.abort("gateway-permanent-down")
    assert healing.phase == HealingPhase.ABORTED
    assert healing.context.extra["aborted_reason"] == "gateway-permanent-down"
    with pytest.raises(PhaseTransitionError):
        healing.transition_to_inflammation()


# ---------------- Edge: callback exceptions do not break state-machine ----------------


def test_callback_exception_does_not_break_state(fixed_clock):
    def bad_cb(ctx):
        raise RuntimeError("boom")

    h = WoundHealingLifecycle(
        saga_run_id="run-1", hotel_id="hotel-A",
        cleanup_callback=bad_cb,
        clock=fixed_clock,
    )
    h.start_hemostasis("c")
    h.transition_to_inflammation()  # bad_cb raises but state still advances
    assert h.phase == HealingPhase.INFLAMMATION
    assert "cleanup_errors" in h.context.extra


# ---------------- Edge: Constructor validation ----------------


def test_wound_healing_requires_saga_id_and_hotel_id():
    with pytest.raises(ValueError):
        WoundHealingLifecycle(saga_run_id="", hotel_id="hotel-A")
    with pytest.raises(ValueError):
        WoundHealingLifecycle(saga_run_id="run-1", hotel_id="")
