from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.cape_familien_chaos_engineering import (
    FamilienChaosEngine,
    FamilienChaosOutcome,
    FamilienChaosScenario,
    FaultSeverity,
)


def test_scenario_is_frozen() -> None:
    scenario = FamilienChaosScenario("dummy-001", "VISA_DEADLINE_MISS", FaultSeverity.HIGH)

    with pytest.raises(FrozenInstanceError):
        scenario.scenario_id = "real-data-not-allowed"


def test_outcome_is_frozen() -> None:
    outcome = FamilienChaosOutcome("dummy-002", "BROTHER_DISAGREEMENT", FaultSeverity.LOW, False, "GO", "ok", "none")

    with pytest.raises(FrozenInstanceError):
        outcome.failed = True


def test_visa_deadline_miss_fails_and_enters_history() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario("dummy-003", "VISA_DEADLINE_MISS", FaultSeverity.CRITICAL, visa_days_remaining=3)

    outcome = engine.inject(scenario)

    assert outcome.failed is True
    assert outcome.decision == "NO_GO"
    assert engine.failed_outcome() == outcome


def test_visa_deadline_with_buffer_passes_without_history() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario("dummy-004", "VISA_DEADLINE_MISS", FaultSeverity.MEDIUM, visa_days_remaining=45)

    outcome = engine.inject(scenario)

    assert outcome.failed is False
    assert engine.history == []


def test_wegzugssteuer_audit_trigger_fails() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario(
        "dummy-005",
        "WEGZUGSSTEUER_AUDIT_TRIGGER",
        FaultSeverity.HIGH,
        wegzugssteuer_audit_score=90,
    )

    outcome = engine.inject(scenario)

    assert outcome.failed is True
    assert "wegzugssteuer" in outcome.reason


def test_school_enrollment_reject_fails_when_dummy_documents_missing() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario(
        "dummy-006",
        "SCHOOL_ENROLLMENT_REJECT",
        FaultSeverity.HIGH,
        school_documents_complete=False,
    )

    outcome = engine.inject(scenario)

    assert outcome.failed is True
    assert outcome.decision == "NO_GO"


def test_brother_disagreement_routes_to_review() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario(
        "dummy-007",
        "BROTHER_DISAGREEMENT",
        FaultSeverity.MEDIUM,
        brother_alignment_score=20,
    )

    outcome = engine.inject(scenario)

    assert outcome.failed is True
    assert outcome.decision == "REVIEW"


def test_medical_emergency_fails_when_response_time_is_too_high() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario(
        "dummy-008",
        "MEDICAL_EMERGENCY",
        FaultSeverity.CRITICAL,
        medical_response_minutes=45,
    )

    outcome = engine.inject(scenario)

    assert outcome.failed is True
    assert "medical" in outcome.reason


def test_unknown_fault_fails_closed() -> None:
    engine = FamilienChaosEngine()
    scenario = FamilienChaosScenario("dummy-009", "UNREGISTERED_FAULT", FaultSeverity.LOW)

    outcome = engine.inject(scenario)

    assert outcome.failed is True
    assert outcome.decision == "REVIEW"


def test_failed_outcome_tracks_latest_failure_only() -> None:
    engine = FamilienChaosEngine()

    first = engine.inject(FamilienChaosScenario("dummy-010", "VISA_DEADLINE_MISS", FaultSeverity.HIGH, visa_days_remaining=1))
    engine.inject(FamilienChaosScenario("dummy-011", "VISA_DEADLINE_MISS", FaultSeverity.LOW, visa_days_remaining=60))
    second = engine.inject(
        FamilienChaosScenario("dummy-012", "BROTHER_DISAGREEMENT", FaultSeverity.MEDIUM, brother_alignment_score=10)
    )

    assert first.failed is True
    assert engine.failed_outcome() == second
    assert len(engine.history) == 2


def test_max_concurrent_chaos_must_be_positive() -> None:
    with pytest.raises(ValueError):
        FamilienChaosEngine(max_concurrent_chaos=0)


def test_max_concurrent_chaos_records_failed_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = FamilienChaosEngine(max_concurrent_chaos=1)
    entered = threading.Event()
    release = threading.Event()

    def slow_evaluate(scenario: FamilienChaosScenario) -> FamilienChaosOutcome:
        entered.set()
        release.wait(timeout=2)
        return FamilienChaosOutcome(scenario.scenario_id, scenario.fault, scenario.severity, False, "GO", "ok", "none")

    monkeypatch.setattr(engine, "_evaluate", slow_evaluate)
    first = FamilienChaosScenario("dummy-013", "VISA_DEADLINE_MISS", FaultSeverity.LOW)
    second = FamilienChaosScenario("dummy-014", "MEDICAL_EMERGENCY", FaultSeverity.CRITICAL)
    thread = threading.Thread(target=engine.inject, args=(first,))
    thread.start()
    assert entered.wait(timeout=1)

    outcome = engine.inject(second)
    release.set()
    thread.join(timeout=2)

    assert outcome.failed is True
    assert outcome.reason == "max_concurrent_chaos exceeded"
    assert engine.failed_outcome() == outcome
