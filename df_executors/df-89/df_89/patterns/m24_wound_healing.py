"""CRUX-MK M-24: Wound-Healing 4-phase lifecycle (Welle-11.1)."""

from __future__ import annotations

from enum import Enum
import statistics
import time
from typing import Any, Literal

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from df_89.knowledge import KnowledgeStore

Severity = Literal["low", "medium", "high", "critical"]


class HealingPhase(Enum):
    HEMOSTASIS = "hemostasis"
    INFLAMMATION = "inflammation"
    PROLIFERATION = "proliferation"
    REMODELING = "remodeling"
    HEALED = "healed"


@dataclass(config=ConfigDict(validate_assignment=True, arbitrary_types_allowed=True))
class IncidentRecord:
    """Incident state. Pre: valid id/severity. Post: audit and transitions are present."""

    incident_id: str
    severity: Severity
    started_at: float
    current_phase: HealingPhase
    phase_transitions: list[tuple[HealingPhase, float]] = Field(default_factory=list)
    audit_trail: list[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        """Pre: pydantic assigned fields. Post: DF-89 invariants hold."""
        if not self.incident_id.strip():
            raise ValueError("incident_id must not be blank")
        if self.started_at < 0.0:
            raise ValueError("started_at must be non-negative")


class WoundHealingLifecycle:
    """4-Phase Healing-Lifecycle mit Time-Box pro Phase.

    Pre: incidents enter HEMOSTASIS. Post: transitions are ordered, audited, and logged.
    """

    PHASE_TIMEBOX_S = {
        HealingPhase.HEMOSTASIS: 60,
        HealingPhase.INFLAMMATION: 300,
        HealingPhase.PROLIFERATION: 1800,
        HealingPhase.REMODELING: 3600,
    }
    _ORDER = [
        HealingPhase.HEMOSTASIS,
        HealingPhase.INFLAMMATION,
        HealingPhase.PROLIFERATION,
        HealingPhase.REMODELING,
        HealingPhase.HEALED,
    ]

    def __init__(self, knowledge_store: KnowledgeStore | None = None):
        """Pre: store is None or add_methodik-compatible. Post: registry is empty."""
        self.knowledge_store = knowledge_store
        self.incidents: dict[str, IncidentRecord] = {}
        self._healed_at: dict[str, float] = {}
        self._forced: dict[str, str] = {}

    def start_healing(self, incident_id: str, severity: str) -> IncidentRecord:
        """Start hemostasis. Pre: unique id and valid severity. Post: incident is active."""
        if incident_id in self.incidents:
            raise ValueError(f"incident already exists: {incident_id}")
        if severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")
        now = self._now()
        record = IncidentRecord(
            incident_id=incident_id,
            severity=severity,  # type: ignore[arg-type]
            started_at=now,
            current_phase=HealingPhase.HEMOSTASIS,
            phase_transitions=[(HealingPhase.HEMOSTASIS, now)],
            audit_trail=[self._audit_line(now, "start", HealingPhase.HEMOSTASIS, severity)],
        )
        self.incidents[incident_id] = record
        return record

    def transition_phase(self, incident_id: str, target: HealingPhase) -> IncidentRecord:
        """Advance phase. Pre: target is legal and in time-box. Post: transition is logged."""
        record = self._incident(incident_id)
        if record.current_phase is HealingPhase.HEALED:
            raise ValueError("healed incident cannot transition")
        if not isinstance(target, HealingPhase):
            raise TypeError("target must be a HealingPhase")
        now = self._now()
        self._raise_if_timebox_exceeded(record, now)
        warning = self._transition_warning(record, target)
        previous = record.current_phase
        record.current_phase = target
        record.phase_transitions.append((target, now))
        record.audit_trail.append(self._marker(now, previous, target, warning))
        if target is HealingPhase.HEALED:
            self._healed_at[incident_id] = now
        self._log_transition(record, previous, target, now, warning)
        return record

    def check_timebox_violations(self) -> list[IncidentRecord]:
        """Find overdue phases. Pre: any lifecycle state. Post: returns active violations."""
        now = self._now()
        return [
            record
            for record in self.incidents.values()
            if record.current_phase in self.PHASE_TIMEBOX_S
            and now - record.phase_transitions[-1][1] > self.PHASE_TIMEBOX_S[record.current_phase]
        ]

    def force_termination(self, incident_id: str, reason: str) -> None:
        """Override sequence. Pre: reason is non-empty. Post: incident is terminal."""
        if not reason.strip():
            raise ValueError("reason must not be blank")
        record = self._incident(incident_id)
        now = self._now()
        previous = record.current_phase
        record.current_phase = HealingPhase.HEALED
        record.phase_transitions.append((HealingPhase.HEALED, now))
        record.audit_trail.append(self._audit_line(now, "force_termination", HealingPhase.HEALED, reason))
        self._forced[incident_id] = reason
        self._healed_at[incident_id] = now
        self._log_transition(record, previous, HealingPhase.HEALED, now, f"forced: {reason}")

    def healing_metrics(self) -> dict[str, Any]:
        """Compute MTTR and distribution. Pre: incidents optional. Post: metrics dict."""
        durations = [
            healed_at - self.incidents[incident_id].started_at
            for incident_id, healed_at in self._healed_at.items()
            if incident_id not in self._forced
        ]
        total = len(self.incidents)
        successes = len([incident_id for incident_id in self._healed_at if incident_id not in self._forced])
        distribution = {phase.value: 0 for phase in HealingPhase}
        for record in self.incidents.values():
            distribution[record.current_phase.value] += 1
        return {
            "mttr_s": statistics.fmean(durations) if durations else 0.0,
            "success_rate": successes / total if total else 0.0,
            "phase_distribution": distribution,
            "active_incidents": total - len(self._healed_at),
            "forced_terminations": len(self._forced),
        }

    def _transition_warning(self, record: IncidentRecord, target: HealingPhase) -> str | None:
        expected = self._ORDER[self._ORDER.index(record.current_phase) + 1]
        if target is expected:
            return None
        if (
            record.severity == "critical"
            and record.current_phase is HealingPhase.HEMOSTASIS
            and target is HealingPhase.PROLIFERATION
        ):
            return "critical fast-path skipped inflammation"
        raise ValueError(f"invalid phase transition: {record.current_phase.value} -> {target.value}")

    def _raise_if_timebox_exceeded(self, record: IncidentRecord, now: float) -> None:
        budget = self.PHASE_TIMEBOX_S.get(record.current_phase)
        elapsed = now - record.phase_transitions[-1][1]
        if budget is not None and elapsed > budget:
            raise TimeoutError(
                f"timebox exceeded for {record.incident_id}:{record.current_phase.value} "
                f"elapsed={elapsed:.3f}s budget={budget}s"
            )

    def _log_transition(
        self, record: IncidentRecord, previous: HealingPhase, target: HealingPhase, ts: float, warning: str | None
    ) -> None:
        if self.knowledge_store is None:
            return
        description = (
            f"incident={record.incident_id}; severity={record.severity}; "
            f"transition={previous.value}->{target.value}; ts={ts:.6f}"
        )
        if warning:
            description = f"{description}; warning={warning}"
        self.knowledge_store.add_methodik(
            name=f"m24_wound_healing:{record.incident_id}:{target.value}:{len(record.phase_transitions)}",
            description=description,
            confidence=0.82,
            status="observed",
        )

    def _incident(self, incident_id: str) -> IncidentRecord:
        if incident_id not in self.incidents:
            raise KeyError(f"unknown incident: {incident_id}")
        return self.incidents[incident_id]

    @classmethod
    def _marker(cls, ts: float, previous: HealingPhase, target: HealingPhase, warning: str | None) -> str:
        detail = f"{previous.value}->{target.value}"
        if warning:
            detail = f"{detail}; warning={warning}"
        return cls._audit_line(ts, "regenerative_transition", target, detail)

    @staticmethod
    def _audit_line(ts: float, event: str, phase: HealingPhase, detail: str) -> str:
        return f"{ts:.6f} | {event} | phase={phase.value} | {detail}"

    @staticmethod
    def _now() -> float:
        return time.time()


__all__ = ["HealingPhase", "IncidentRecord", "WoundHealingLifecycle"]
