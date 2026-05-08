# [CRUX-MK]
"""Tests fuer KPM-Saga-Orchestrator (Welle-27 Phase-20 Bio-Pattern-Lift).

Pflicht-Tests:
- Init-Validation, register_handler, register_compensator
- execute_saga: all-succeed, failure-triggers-compensation
- compensation runs in reverse order
- get_outcome existing / unknown saga_id
- concurrent sagas isolated (3 sagas parallel)
- cancel_in_progress
- handler-exception becomes FAILED state
- compensation-failure logged (not blocking)
- SagaStep + SagaOutcome frozen-immutability

CRUX-MK
"""
from __future__ import annotations

import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.kpm_saga_orchestrator import (
    KPMSagaOrchestrator,
    SagaOutcome,
    SagaPhase,
    SagaState,
    SagaStep,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _step(step_id: str, phase: SagaPhase, instrument: str = "AAPL") -> SagaStep:
    return SagaStep(
        step_id=step_id,
        phase=phase,
        instrument_id=instrument,
        action_data=(("symbol", instrument), ("qty", 100)),
        compensation_data=(("symbol", instrument), ("qty", 100), ("side", "REVERSE")),
    )


def _all_phase_handlers(orch: KPMSagaOrchestrator) -> None:
    """Register no-op handlers fuer alle 5 Phasen (Erfolg-Standard)."""
    for phase in SagaPhase:
        orch.register_handler(phase, lambda step: {"ok": True, "step_id": step.step_id})


def _all_phase_compensators(orch: KPMSagaOrchestrator) -> None:
    """Register no-op compensators fuer alle 5 Phasen."""
    for phase in SagaPhase:
        orch.register_compensator(phase, lambda step: None)


# ---------------------------------------------------------------------------
# Init / Validation
# ---------------------------------------------------------------------------


def test_init_validation():
    """Constructor lehnt default_timeout_s <= 0 ab; default ist 30.0s."""
    orch = KPMSagaOrchestrator()
    assert orch._default_timeout_s == 30.0

    orch = KPMSagaOrchestrator(default_timeout_s=10.0)
    assert orch._default_timeout_s == 10.0

    with pytest.raises(ValueError, match="default_timeout_s must be > 0"):
        KPMSagaOrchestrator(default_timeout_s=0)

    with pytest.raises(ValueError, match="default_timeout_s must be > 0"):
        KPMSagaOrchestrator(default_timeout_s=-1.0)


def test_register_handler():
    """register_handler: callable, phase-Validation, Re-Register erlaubt."""
    orch = KPMSagaOrchestrator()

    def h(step):
        return {"ok": True}

    orch.register_handler(SagaPhase.VALIDATE, h)
    assert orch._handlers[SagaPhase.VALIDATE] is h

    # Re-Register ueberschreibt
    def h2(step):
        return {"ok": False}

    orch.register_handler(SagaPhase.VALIDATE, h2)
    assert orch._handlers[SagaPhase.VALIDATE] is h2

    # Invalid phase
    with pytest.raises(ValueError, match="phase must be a SagaPhase"):
        orch.register_handler("validate", h)  # type: ignore[arg-type]

    # Non-callable
    with pytest.raises(ValueError, match="handler_fn must be callable"):
        orch.register_handler(SagaPhase.RESERVE, "not-callable")  # type: ignore[arg-type]


def test_register_compensator():
    """register_compensator: analog zu register_handler."""
    orch = KPMSagaOrchestrator()

    def c(step):
        return None

    orch.register_compensator(SagaPhase.EXECUTE, c)
    assert orch._compensators[SagaPhase.EXECUTE] is c

    with pytest.raises(ValueError, match="phase must be a SagaPhase"):
        orch.register_compensator("execute", c)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="comp_fn must be callable"):
        orch.register_compensator(SagaPhase.CONFIRM, 42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# execute_saga: success path
# ---------------------------------------------------------------------------


def test_execute_saga_all_succeed():
    """Alle Steps succeed -> state=COMPLETED, completed_steps voll."""
    orch = KPMSagaOrchestrator()
    _all_phase_handlers(orch)

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),
        _step("s3", SagaPhase.EXECUTE),
        _step("s4", SagaPhase.CONFIRM),
        _step("s5", SagaPhase.SETTLE),
    ]
    outcome = orch.execute_saga(steps, saga_id="saga-001")

    assert outcome.saga_id == "saga-001"
    assert outcome.state == SagaState.COMPLETED
    assert outcome.completed_steps == ("s1", "s2", "s3", "s4", "s5")
    assert outcome.failed_step is None
    assert outcome.compensation_log == ()
    assert outcome.elapsed_s >= 0
    assert outcome.timestamp > 0


# ---------------------------------------------------------------------------
# execute_saga: failure triggers compensation
# ---------------------------------------------------------------------------


def test_execute_saga_failure_triggers_compensation():
    """Step 3 failed -> Steps 1+2 kompensiert, state=COMPENSATED."""
    orch = KPMSagaOrchestrator()

    # Default-Handlers
    for phase in SagaPhase:
        orch.register_handler(phase, lambda step: {"ok": True})

    # Override: EXECUTE failed
    def failing_execute(step):
        raise RuntimeError("broker rejected")

    orch.register_handler(SagaPhase.EXECUTE, failing_execute)

    # Compensation-Tracking
    comp_calls: list[str] = []

    def make_comp(name: str):
        def comp(step):
            comp_calls.append(f"{name}:{step.step_id}")

        return comp

    orch.register_compensator(SagaPhase.VALIDATE, make_comp("VALIDATE-c"))
    orch.register_compensator(SagaPhase.RESERVE, make_comp("RESERVE-c"))
    orch.register_compensator(SagaPhase.EXECUTE, make_comp("EXECUTE-c"))

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),
        _step("s3", SagaPhase.EXECUTE),
    ]
    outcome = orch.execute_saga(steps, saga_id="saga-fail-001")

    assert outcome.state == SagaState.COMPENSATED
    assert outcome.failed_step == "s3"
    assert outcome.completed_steps == ("s1", "s2")
    # 1 handler-fail-log + 2 compensations
    assert len(outcome.compensation_log) == 3
    # Erste Eintrag = handler-failed
    assert outcome.compensation_log[0][0] == "s3"
    assert "handler-failed" in outcome.compensation_log[0][2]
    # 2 Compensation-Eintraege fuer s2 + s1
    comp_step_ids = [entry[0] for entry in outcome.compensation_log[1:]]
    assert comp_step_ids == ["s2", "s1"]


def test_compensation_runs_in_reverse_order():
    """Compensation ruft compensators in reverse-Reihenfolge der completed-Steps."""
    orch = KPMSagaOrchestrator()
    for phase in SagaPhase:
        orch.register_handler(phase, lambda step: {"ok": True})

    # CONFIRM failed
    orch.register_handler(
        SagaPhase.CONFIRM,
        lambda step: (_ for _ in ()).throw(RuntimeError("broker timeout")),
    )

    call_order: list[str] = []

    for phase in SagaPhase:

        def comp_factory(p_name):
            def comp(step):
                call_order.append(f"{p_name}:{step.step_id}")

            return comp

        orch.register_compensator(phase, comp_factory(phase.value))

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),
        _step("s3", SagaPhase.EXECUTE),
        _step("s4", SagaPhase.CONFIRM),
    ]
    outcome = orch.execute_saga(steps, saga_id="saga-rev-001")

    assert outcome.state == SagaState.COMPENSATED
    assert outcome.failed_step == "s4"
    assert outcome.completed_steps == ("s1", "s2", "s3")
    # Reverse-Reihenfolge: s3, s2, s1
    assert call_order == ["execute:s3", "reserve:s2", "validate:s1"]


# ---------------------------------------------------------------------------
# get_outcome
# ---------------------------------------------------------------------------


def test_get_outcome_existing():
    """get_outcome liefert persisted Outcome."""
    orch = KPMSagaOrchestrator()
    _all_phase_handlers(orch)

    steps = [_step("s1", SagaPhase.VALIDATE)]
    orch.execute_saga(steps, saga_id="saga-get-001")

    outcome = orch.get_outcome("saga-get-001")
    assert outcome.saga_id == "saga-get-001"
    assert outcome.state == SagaState.COMPLETED


def test_get_outcome_unknown_saga_id():
    """get_outcome raises KeyError fuer unbekannte saga_id."""
    orch = KPMSagaOrchestrator()
    with pytest.raises(KeyError, match="saga_id 'nope' not found"):
        orch.get_outcome("nope")


def test_get_outcomes_snapshot():
    """get_outcomes liefert tuple aller Outcomes (Insertion-Order stable)."""
    orch = KPMSagaOrchestrator()
    _all_phase_handlers(orch)

    for i in range(3):
        orch.execute_saga(
            [_step(f"s{i}", SagaPhase.VALIDATE)],
            saga_id=f"saga-snap-{i}",
        )

    outcomes = orch.get_outcomes()
    assert len(outcomes) == 3
    assert [o.saga_id for o in outcomes] == ["saga-snap-0", "saga-snap-1", "saga-snap-2"]
    # Snapshot ist tuple (immutable)
    assert isinstance(outcomes, tuple)


# ---------------------------------------------------------------------------
# Concurrent Sagas
# ---------------------------------------------------------------------------


def test_concurrent_sagas_isolated():
    """3 Sagas parallel — Outcomes sind isoliert (keine State-Verschraenkung)."""
    orch = KPMSagaOrchestrator()

    # Handler mit kurzer Verzoegerung um Concurrency zu provozieren
    def slow_handler(step):
        time.sleep(0.01)
        return {"ok": True, "step_id": step.step_id}

    for phase in SagaPhase:
        orch.register_handler(phase, slow_handler)

    results: dict[int, SagaOutcome] = {}
    errors: list[BaseException] = []

    def run_saga(idx: int):
        try:
            steps = [
                _step(f"s{idx}-1", SagaPhase.VALIDATE, instrument=f"INST-{idx}"),
                _step(f"s{idx}-2", SagaPhase.EXECUTE, instrument=f"INST-{idx}"),
            ]
            results[idx] = orch.execute_saga(steps, saga_id=f"concurrent-{idx}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run_saga, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 3
    for idx in range(3):
        outcome = results[idx]
        assert outcome.saga_id == f"concurrent-{idx}"
        assert outcome.state == SagaState.COMPLETED
        # completed_steps gehoeren NUR zu dieser Saga
        assert outcome.completed_steps == (f"s{idx}-1", f"s{idx}-2")


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def test_cancel_in_progress():
    """cancel_in_progress markiert laufende Saga + bricht Steps ab."""
    orch = KPMSagaOrchestrator()

    cancel_event = threading.Event()
    saga_started = threading.Event()

    def slow_handler(step):
        saga_started.set()
        # Erste Step laesst cancel_in_progress den Trigger setzen
        cancel_event.wait(timeout=2.0)
        return {"ok": True}

    orch.register_handler(SagaPhase.VALIDATE, slow_handler)
    # Andere Phasen normal
    for phase in (SagaPhase.RESERVE, SagaPhase.EXECUTE, SagaPhase.CONFIRM, SagaPhase.SETTLE):
        orch.register_handler(phase, lambda step: {"ok": True})

    # Compensator fuer VALIDATE
    orch.register_compensator(SagaPhase.VALIDATE, lambda step: None)

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),
        _step("s3", SagaPhase.EXECUTE),
    ]

    outcome_holder: list[SagaOutcome] = []

    def run_saga():
        outcome_holder.append(orch.execute_saga(steps, saga_id="cancel-001"))

    saga_thread = threading.Thread(target=run_saga)
    saga_thread.start()

    # Warte bis erste Step laeuft, dann cancel
    saga_started.wait(timeout=2.0)
    result = orch.cancel_in_progress("cancel-001")
    assert result is True

    cancel_event.set()
    saga_thread.join(timeout=3.0)

    assert len(outcome_holder) == 1
    outcome = outcome_holder[0]
    # Erste Step (s1) wurde fertiggestellt, dann Cancel-Check, dann Compensation
    # Outcome state: COMPENSATED weil completed_steps=("s1",) -> compensated
    # Failed_step = "s2" (der naechste der vom Cancel-Check abgebrochen wurde)
    assert outcome.state in (SagaState.COMPENSATED, SagaState.FAILED)
    # cancel_in_progress fuer unbekannte saga_id -> False
    assert orch.cancel_in_progress("nope") is False


# ---------------------------------------------------------------------------
# Handler-Exception
# ---------------------------------------------------------------------------


def test_handler_exception_becomes_failed_state():
    """handler raising Exception -> Step im compensation_log als handler-failed."""
    orch = KPMSagaOrchestrator()

    orch.register_handler(SagaPhase.VALIDATE, lambda step: {"ok": True})
    orch.register_handler(
        SagaPhase.RESERVE,
        lambda step: (_ for _ in ()).throw(ValueError("margin insufficient")),
    )
    # Default-Compensators fehlen — soll trotzdem laufen
    orch.register_compensator(SagaPhase.VALIDATE, lambda step: None)

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),
    ]
    outcome = orch.execute_saga(steps, saga_id="handler-exc-001")

    assert outcome.state == SagaState.COMPENSATED
    assert outcome.failed_step == "s2"
    assert outcome.completed_steps == ("s1",)
    # compensation_log: 1 handler-fail + 1 compensation
    assert len(outcome.compensation_log) == 2
    assert "handler-failed: ValueError: margin insufficient" in outcome.compensation_log[0][2]
    assert outcome.compensation_log[1][0] == "s1"
    assert outcome.compensation_log[1][2] == "compensated"


# ---------------------------------------------------------------------------
# Compensation-failure logged (not blocking)
# ---------------------------------------------------------------------------


def test_compensation_failure_logged():
    """compensator raising -> Log-Eintrag, weitere compensations laufen weiter."""
    orch = KPMSagaOrchestrator()

    for phase in SagaPhase:
        orch.register_handler(phase, lambda step: {"ok": True})

    # EXECUTE failed
    orch.register_handler(
        SagaPhase.EXECUTE,
        lambda step: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    comp_calls: list[str] = []

    # RESERVE-Compensation failed
    def reserve_comp_fail(step):
        comp_calls.append(f"RESERVE:{step.step_id}")
        raise RuntimeError("margin-release failed")

    def validate_comp_ok(step):
        comp_calls.append(f"VALIDATE:{step.step_id}")

    orch.register_compensator(SagaPhase.VALIDATE, validate_comp_ok)
    orch.register_compensator(SagaPhase.RESERVE, reserve_comp_fail)

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),
        _step("s3", SagaPhase.EXECUTE),
    ]
    outcome = orch.execute_saga(steps, saga_id="comp-fail-001")

    # State = FAILED (degraded) weil eine Compensation failed
    assert outcome.state == SagaState.FAILED
    assert outcome.failed_step == "s3"
    assert outcome.completed_steps == ("s1", "s2")
    # Beide Compensations wurden VERSUCHT
    assert "RESERVE:s2" in comp_calls
    assert "VALIDATE:s1" in comp_calls
    # Log enthaelt: handler-fail + compensation-failed + compensated
    log_statuses = [entry[2] for entry in outcome.compensation_log]
    assert any("handler-failed" in s for s in log_statuses)
    assert any("compensation-failed" in s for s in log_statuses)
    assert "compensated" in log_statuses


# ---------------------------------------------------------------------------
# Frozen-Immutability
# ---------------------------------------------------------------------------


def test_step_frozen_immutability():
    """SagaStep ist frozen — Mutation raises FrozenInstanceError."""
    step = SagaStep(
        step_id="s1",
        phase=SagaPhase.VALIDATE,
        instrument_id="AAPL",
        action_data=(("symbol", "AAPL"),),
    )
    with pytest.raises(FrozenInstanceError):
        step.step_id = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        step.phase = SagaPhase.EXECUTE  # type: ignore[misc]


def test_outcome_frozen_immutability():
    """SagaOutcome ist frozen."""
    outcome = SagaOutcome(
        saga_id="s",
        state=SagaState.COMPLETED,
        completed_steps=("s1",),
        failed_step=None,
        compensation_log=(),
        elapsed_s=0.1,
        timestamp=time.time(),
    )
    with pytest.raises(FrozenInstanceError):
        outcome.state = SagaState.FAILED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        outcome.completed_steps = ("changed",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validation: Step-Field-Validation
# ---------------------------------------------------------------------------


def test_saga_step_validation():
    """SagaStep raises bei invalid fields (zusaetzlicher Coverage)."""
    with pytest.raises(ValueError, match="step_id must be non-empty"):
        SagaStep(step_id="", phase=SagaPhase.VALIDATE, instrument_id="AAPL")
    with pytest.raises(ValueError, match="phase must be a SagaPhase"):
        SagaStep(step_id="s1", phase="validate", instrument_id="AAPL")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="instrument_id must be non-empty"):
        SagaStep(step_id="s1", phase=SagaPhase.VALIDATE, instrument_id="")
    with pytest.raises(ValueError, match="action_data must be tuple"):
        SagaStep(
            step_id="s1",
            phase=SagaPhase.VALIDATE,
            instrument_id="AAPL",
            action_data=[("symbol", "AAPL")],  # type: ignore[arg-type]
        )


def test_execute_saga_missing_handler_raises():
    """execute_saga raises ValueError wenn Handler fuer Step-Phase fehlt."""
    orch = KPMSagaOrchestrator()
    # Nur VALIDATE registriert
    orch.register_handler(SagaPhase.VALIDATE, lambda step: {"ok": True})

    steps = [
        _step("s1", SagaPhase.VALIDATE),
        _step("s2", SagaPhase.RESERVE),  # kein Handler
    ]
    with pytest.raises(ValueError, match="no handler registered for phase 'reserve'"):
        orch.execute_saga(steps, saga_id="missing-h-001")


def test_execute_saga_empty_steps_raises():
    """execute_saga raises bei leerer steps-Liste."""
    orch = KPMSagaOrchestrator()
    _all_phase_handlers(orch)
    with pytest.raises(ValueError, match="steps must be non-empty"):
        orch.execute_saga([], saga_id="empty-001")


# CRUX-MK
