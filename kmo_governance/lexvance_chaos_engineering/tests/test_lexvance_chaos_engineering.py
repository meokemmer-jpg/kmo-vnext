from __future__ import annotations

import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.lexvance_chaos_engineering import (  # noqa: E402
    FaultSeverity,
    LegalChaosEngine,
    LegalChaosFault,
    LegalChaosOutcome,
    LegalChaosScenario,
)


def make_scenario(
    fault: LegalChaosFault = LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS,
    severity: FaultSeverity = FaultSeverity.MEDIUM,
) -> LegalChaosScenario:
    return LegalChaosScenario(
        fault=fault,
        severity=severity,
        mandant_id="mandant-17",
        document_id="doc-42",
        pipeline_stage="review",
    )


def test_fault_enum_contains_lexvance_faults() -> None:
    assert {fault.name for fault in LegalChaosFault} == {
        "DOCUMENT_REVIEW_DEADLINE_MISS",
        "COURT_FILING_PORTAL_DOWN",
        "DSGVO_AUDIT_TRIGGER",
        "EVIDENCE_CHAIN_BREAK",
        "MANDANT_CONFLICT_OF_INTEREST",
    }


def test_fault_severity_ordering_is_explicit() -> None:
    assert FaultSeverity.LOW.value < FaultSeverity.MEDIUM.value
    assert FaultSeverity.HIGH.value < FaultSeverity.CRITICAL.value


def test_scenario_and_outcome_are_frozen() -> None:
    engine = LegalChaosEngine()
    scenario = make_scenario()
    outcome = engine.inject(scenario)

    with pytest.raises(FrozenInstanceError):
        scenario.document_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        outcome.succeeded = False  # type: ignore[misc]


def test_inject_returns_successful_outcome_and_records_history() -> None:
    engine = LegalChaosEngine()
    scenario = make_scenario()

    outcome = engine.inject(scenario)

    assert outcome.succeeded is True
    assert outcome.fault is LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS
    assert outcome.mandant_id == "mandant-17"
    assert outcome.document_id == "doc-42"
    assert outcome.blocked_stage == "review"
    assert engine.history() == (outcome,)


def test_document_review_deadline_miss_reason_is_domain_specific() -> None:
    engine = LegalChaosEngine()
    outcome = engine.inject(make_scenario())

    assert "document review deadline missed" in outcome.reason
    assert 0.0 < outcome.impact_score <= 1.0


def test_court_filing_portal_down_blocks_filing_stage() -> None:
    engine = LegalChaosEngine()
    outcome = engine.inject(
        make_scenario(
            LegalChaosFault.COURT_FILING_PORTAL_DOWN,
            FaultSeverity.HIGH,
        )
    )

    assert outcome.succeeded is True
    assert outcome.blocked_stage == "court_filing"
    assert outcome.recovery_required is True
    assert "court filing portal unavailable" in outcome.reason


def test_dsgvo_audit_trigger_requires_recovery_for_critical_fault() -> None:
    engine = LegalChaosEngine()
    outcome = engine.inject(
        make_scenario(
            LegalChaosFault.DSGVO_AUDIT_TRIGGER,
            FaultSeverity.CRITICAL,
        )
    )

    assert outcome.blocked_stage == "compliance_audit"
    assert outcome.recovery_required is True
    assert outcome.impact_score > 0.75
    assert "DSGVO audit" in outcome.reason


def test_evidence_chain_break_has_high_impact() -> None:
    engine = LegalChaosEngine()
    outcome = engine.inject(
        make_scenario(
            LegalChaosFault.EVIDENCE_CHAIN_BREAK,
            FaultSeverity.HIGH,
        )
    )

    assert outcome.blocked_stage == "evidence_chain"
    assert outcome.impact_score > 0.8
    assert "chain of custody" in outcome.reason


def test_mandant_conflict_of_interest_maps_to_conflict_check() -> None:
    engine = LegalChaosEngine()
    outcome = engine.inject(
        make_scenario(
            LegalChaosFault.MANDANT_CONFLICT_OF_INTEREST,
            FaultSeverity.CRITICAL,
        )
    )

    assert outcome.blocked_stage == "mandant_conflict_check"
    assert outcome.recovery_required is True
    assert "conflict of interest" in outcome.reason


def test_paused_injection_returns_failed_outcome_and_appends_history() -> None:
    engine = LegalChaosEngine()
    scenario = make_scenario()
    engine.pause()

    outcome = engine.inject(scenario)

    assert outcome.succeeded is False
    assert outcome.recovery_required is True
    assert "paused" in outcome.reason
    assert engine.history() == (outcome,)


def test_max_concurrent_chaos_returns_failed_outcome_and_appends_history() -> None:
    engine = LegalChaosEngine(max_concurrent_chaos=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_handler(scenario: LegalChaosScenario) -> LegalChaosOutcome:
        started.set()
        release.wait(timeout=2.0)
        return LegalChaosOutcome(
            scenario=scenario,
            succeeded=True,
            fault=scenario.fault,
            severity=scenario.severity,
            mandant_id=scenario.mandant_id,
            document_id=scenario.document_id,
            blocked_stage="review",
            recovery_required=False,
            impact_score=0.2,
            reason="blocked handler completed",
            started_at=1.0,
            completed_at=2.0,
        )

    engine.register_handler(
        LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS,
        blocking_handler,
    )

    thread = threading.Thread(target=engine.inject, args=(make_scenario(),))
    thread.start()
    assert started.wait(timeout=2.0)

    failed = engine.inject(make_scenario(LegalChaosFault.COURT_FILING_PORTAL_DOWN))
    release.set()
    thread.join(timeout=2.0)

    assert failed.succeeded is False
    assert failed.recovery_required is True
    assert "max_concurrent_chaos exceeded" in failed.reason
    assert failed in engine.history()


def test_history_limit_truncates_old_outcomes_and_reset_clears() -> None:
    engine = LegalChaosEngine(history_limit=2)

    first = engine.inject(make_scenario(LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS))
    second = engine.inject(make_scenario(LegalChaosFault.COURT_FILING_PORTAL_DOWN))
    third = engine.inject(make_scenario(LegalChaosFault.DSGVO_AUDIT_TRIGGER))

    assert engine.history() == (second, third)
    assert first not in engine.history()

    engine.reset_history()
    assert engine.history() == ()
