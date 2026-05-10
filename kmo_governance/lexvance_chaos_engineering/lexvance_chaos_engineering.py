"""LexVance Legal-Document-Pipeline-Failure-Stress chaos engine [CRUX-MK]."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping


DEFAULT_MAX_CONCURRENT_CHAOS = 2
DEFAULT_HISTORY_LIMIT = 100


class LegalChaosFault(Enum):
    DOCUMENT_REVIEW_DEADLINE_MISS = "document_review_deadline_miss"
    COURT_FILING_PORTAL_DOWN = "court_filing_portal_down"
    DSGVO_AUDIT_TRIGGER = "dsgvo_audit_trigger"
    EVIDENCE_CHAIN_BREAK = "evidence_chain_break"
    MANDANT_CONFLICT_OF_INTEREST = "mandant_conflict_of_interest"


class FaultSeverity(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass(frozen=True)
class LegalChaosScenario:
    fault: LegalChaosFault
    severity: FaultSeverity
    mandant_id: str
    document_id: str
    pipeline_stage: str = "intake"
    expected_recovery_s: float = 60.0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mandant_id:
            raise ValueError("mandant_id must be non-empty")
        if not self.document_id:
            raise ValueError("document_id must be non-empty")
        if not self.pipeline_stage:
            raise ValueError("pipeline_stage must be non-empty")
        if self.expected_recovery_s < 0:
            raise ValueError("expected_recovery_s must be >= 0")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class LegalChaosOutcome:
    scenario: LegalChaosScenario
    succeeded: bool
    fault: LegalChaosFault
    severity: FaultSeverity
    mandant_id: str
    document_id: str
    blocked_stage: str
    recovery_required: bool
    impact_score: float
    reason: str
    started_at: float
    completed_at: float


ChaosHandler = Callable[[LegalChaosScenario], LegalChaosOutcome]


class LegalChaosEngine:
    """Thread-safe LexVance chaos injector for legal-document pipeline faults."""

    _FAULT_IMPACT_BASE = {
        LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS: 0.45,
        LegalChaosFault.COURT_FILING_PORTAL_DOWN: 0.62,
        LegalChaosFault.DSGVO_AUDIT_TRIGGER: 0.76,
        LegalChaosFault.EVIDENCE_CHAIN_BREAK: 0.90,
        LegalChaosFault.MANDANT_CONFLICT_OF_INTEREST: 0.95,
    }

    _FAULT_STAGE = {
        LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS: "review",
        LegalChaosFault.COURT_FILING_PORTAL_DOWN: "court_filing",
        LegalChaosFault.DSGVO_AUDIT_TRIGGER: "compliance_audit",
        LegalChaosFault.EVIDENCE_CHAIN_BREAK: "evidence_chain",
        LegalChaosFault.MANDANT_CONFLICT_OF_INTEREST: "mandant_conflict_check",
    }

    _FAULT_REASON = {
        LegalChaosFault.DOCUMENT_REVIEW_DEADLINE_MISS: "document review deadline missed",
        LegalChaosFault.COURT_FILING_PORTAL_DOWN: "court filing portal unavailable",
        LegalChaosFault.DSGVO_AUDIT_TRIGGER: "DSGVO audit triggered for legal document",
        LegalChaosFault.EVIDENCE_CHAIN_BREAK: "evidence chain of custody broken",
        LegalChaosFault.MANDANT_CONFLICT_OF_INTEREST: "mandant conflict of interest detected",
    }

    def __init__(
        self,
        *,
        max_concurrent_chaos: int = DEFAULT_MAX_CONCURRENT_CHAOS,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_concurrent_chaos <= 0:
            raise ValueError("max_concurrent_chaos must be > 0")
        if history_limit <= 0:
            raise ValueError("history_limit must be > 0")

        self.max_concurrent_chaos = int(max_concurrent_chaos)
        self._clock = clock
        self._lock = threading.RLock()
        self._active_chaos = 0
        self._paused = False
        self._history: deque[LegalChaosOutcome] = deque(maxlen=int(history_limit))
        self._handlers: dict[LegalChaosFault, ChaosHandler] = {
            fault: self._default_handler for fault in LegalChaosFault
        }

    def inject(self, scenario: LegalChaosScenario) -> LegalChaosOutcome:
        if not isinstance(scenario, LegalChaosScenario):
            raise TypeError("scenario must be LegalChaosScenario")

        with self._lock:
            if self._paused:
                return self._record_failed_outcome(scenario, "chaos injection paused")
            if self._active_chaos >= self.max_concurrent_chaos:
                return self._record_failed_outcome(
                    scenario,
                    "max_concurrent_chaos exceeded",
                )
            self._active_chaos += 1
            handler = self._handlers[scenario.fault]

        try:
            outcome = handler(scenario)
        except Exception as exc:  # pragma: no cover - defensive failure path
            outcome = self._build_outcome(
                scenario,
                succeeded=False,
                reason=f"chaos handler failed: {exc}",
            )

        with self._lock:
            self._active_chaos -= 1
            self._history.append(outcome)
            return outcome

    def register_handler(self, fault: LegalChaosFault, handler: ChaosHandler) -> None:
        if not isinstance(fault, LegalChaosFault):
            raise TypeError("fault must be LegalChaosFault")
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            self._handlers[fault] = handler

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    @property
    def active_chaos(self) -> int:
        with self._lock:
            return self._active_chaos

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def history(self) -> tuple[LegalChaosOutcome, ...]:
        with self._lock:
            return tuple(self._history)

    def reset_history(self) -> None:
        with self._lock:
            self._history.clear()

    def _record_failed_outcome(
        self,
        scenario: LegalChaosScenario,
        reason: str,
    ) -> LegalChaosOutcome:
        outcome = self._build_outcome(scenario, succeeded=False, reason=reason)
        self._history.append(outcome)
        return outcome

    def _default_handler(self, scenario: LegalChaosScenario) -> LegalChaosOutcome:
        return self._build_outcome(
            scenario,
            succeeded=True,
            reason=self._FAULT_REASON[scenario.fault],
        )

    def _build_outcome(
        self,
        scenario: LegalChaosScenario,
        *,
        succeeded: bool,
        reason: str,
    ) -> LegalChaosOutcome:
        started = self._clock()
        severity_factor = scenario.severity.value / FaultSeverity.CRITICAL.value
        impact_score = min(
            1.0,
            self._FAULT_IMPACT_BASE[scenario.fault] * (0.55 + severity_factor),
        )
        recovery_required = (
            not succeeded
            or scenario.severity in {FaultSeverity.HIGH, FaultSeverity.CRITICAL}
            or scenario.expected_recovery_s > 120.0
        )

        return LegalChaosOutcome(
            scenario=scenario,
            succeeded=succeeded,
            fault=scenario.fault,
            severity=scenario.severity,
            mandant_id=scenario.mandant_id,
            document_id=scenario.document_id,
            blocked_stage=self._FAULT_STAGE[scenario.fault],
            recovery_required=recovery_required,
            impact_score=impact_score,
            reason=reason,
            started_at=started,
            completed_at=self._clock(),
        )
