from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import ClassVar


class FaultSeverity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class FamilienChaosScenario:
    scenario_id: str
    fault: str
    severity: FaultSeverity
    visa_days_remaining: int = 90
    wegzugssteuer_audit_score: int = 0
    school_documents_complete: bool = True
    brother_alignment_score: int = 100
    medical_response_minutes: int = 0
    affected_decision: str = "cape_coral_family_move"


@dataclass(frozen=True)
class FamilienChaosOutcome:
    scenario_id: str
    fault: str
    severity: FaultSeverity
    failed: bool
    decision: str
    reason: str
    mitigation: str


@dataclass
class FamilienChaosEngine:
    max_concurrent_chaos: int = 1
    history: list[FamilienChaosOutcome] = field(default_factory=list)

    VISA_DEADLINE_MISS: ClassVar[str] = "VISA_DEADLINE_MISS"
    WEGZUGSSTEUER_AUDIT_TRIGGER: ClassVar[str] = "WEGZUGSSTEUER_AUDIT_TRIGGER"
    SCHOOL_ENROLLMENT_REJECT: ClassVar[str] = "SCHOOL_ENROLLMENT_REJECT"
    BROTHER_DISAGREEMENT: ClassVar[str] = "BROTHER_DISAGREEMENT"
    MEDICAL_EMERGENCY: ClassVar[str] = "MEDICAL_EMERGENCY"

    def __post_init__(self) -> None:
        if self.max_concurrent_chaos < 1:
            raise ValueError("max_concurrent_chaos must be at least 1")
        self._lock = RLock()
        self._active_chaos = 0

    def inject(self, scenario: FamilienChaosScenario) -> FamilienChaosOutcome:
        with self._lock:
            if self._active_chaos >= self.max_concurrent_chaos:
                outcome = FamilienChaosOutcome(
                    scenario_id=scenario.scenario_id,
                    fault=scenario.fault,
                    severity=scenario.severity,
                    failed=True,
                    decision="PAUSE",
                    reason="max_concurrent_chaos exceeded",
                    mitigation="serialize chaos injection before family decision review",
                )
                self.history.append(outcome)
                return outcome
            self._active_chaos += 1

        try:
            outcome = self._evaluate(scenario)
            if outcome.failed:
                with self._lock:
                    self.history.append(outcome)
            return outcome
        finally:
            with self._lock:
                self._active_chaos -= 1

    def failed_outcome(self) -> FamilienChaosOutcome | None:
        with self._lock:
            return self.history[-1] if self.history else None

    def _evaluate(self, scenario: FamilienChaosScenario) -> FamilienChaosOutcome:
        if scenario.fault == self.VISA_DEADLINE_MISS:
            failed = scenario.visa_days_remaining <= 14
            return FamilienChaosOutcome(
                scenario.scenario_id,
                scenario.fault,
                scenario.severity,
                failed,
                "NO_GO" if failed else "GO",
                "visa deadline buffer below family threshold" if failed else "visa buffer acceptable",
                "open immigration counsel escalation and freeze travel commitments",
            )

        if scenario.fault == self.WEGZUGSSTEUER_AUDIT_TRIGGER:
            failed = scenario.wegzugssteuer_audit_score >= 75
            return FamilienChaosOutcome(
                scenario.scenario_id,
                scenario.fault,
                scenario.severity,
                failed,
                "NO_GO" if failed else "GO",
                "wegzugssteuer audit risk triggered" if failed else "tax audit score acceptable",
                "obtain tax ruling package before signing relocation documents",
            )

        if scenario.fault == self.SCHOOL_ENROLLMENT_REJECT:
            failed = not scenario.school_documents_complete
            return FamilienChaosOutcome(
                scenario.scenario_id,
                scenario.fault,
                scenario.severity,
                failed,
                "NO_GO" if failed else "GO",
                "school enrollment rejected due to missing dummy documents" if failed else "school packet accepted",
                "prepare alternate school shortlist and translated document bundle",
            )

        if scenario.fault == self.BROTHER_DISAGREEMENT:
            failed = scenario.brother_alignment_score < 50
            return FamilienChaosOutcome(
                scenario.scenario_id,
                scenario.fault,
                scenario.severity,
                failed,
                "REVIEW" if failed else "GO",
                "brother disagreement below alignment threshold" if failed else "family alignment acceptable",
                "schedule mediated decision review with explicit veto criteria",
            )

        if scenario.fault == self.MEDICAL_EMERGENCY:
            failed = scenario.medical_response_minutes > 30
            return FamilienChaosOutcome(
                scenario.scenario_id,
                scenario.fault,
                scenario.severity,
                failed,
                "NO_GO" if failed else "GO",
                "medical response time exceeds emergency threshold" if failed else "medical response time acceptable",
                "validate insurance, nearest ER route, and emergency contact plan",
            )

        return FamilienChaosOutcome(
            scenario.scenario_id,
            scenario.fault,
            scenario.severity,
            True,
            "REVIEW",
            "unknown family chaos fault",
            "register fault before running Cape Coral family stress test",
        )
