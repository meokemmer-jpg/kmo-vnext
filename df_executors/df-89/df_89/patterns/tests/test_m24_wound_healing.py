from __future__ import annotations

from typing import Any

import pytest

import df_89.patterns.m24_wound_healing as healing
from df_89.patterns.m24_wound_healing import HealingPhase, WoundHealingLifecycle


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self.methodik: list[dict[str, Any]] = []

    def add_methodik(self, name: str, description: str, confidence: float, status: str = "candidate") -> str:
        self.methodik.append({"name": name, "description": description, "confidence": confidence, "status": status})
        return name


class Clock:
    now = 1_000.0

    def tick(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(healing.time, "time", lambda: clock.now)
    return clock


def full_path(lifecycle: WoundHealingLifecycle, incident_id: str) -> None:
    for phase in (HealingPhase.INFLAMMATION, HealingPhase.PROLIFERATION, HealingPhase.REMODELING, HealingPhase.HEALED):
        lifecycle.transition_phase(incident_id, phase)


def phase_list(lifecycle: WoundHealingLifecycle, incident_id: str) -> list[HealingPhase]:
    return [phase for phase, _ in lifecycle.incidents[incident_id].phase_transitions]


def test_start_healing_initializes_incident(clock: Clock) -> None:
    record = WoundHealingLifecycle().start_healing("inc-1", "medium")
    assert record.current_phase is HealingPhase.HEMOSTASIS
    assert record.phase_transitions == [(HealingPhase.HEMOSTASIS, clock.now)]
    assert "start" in record.audit_trail[0]


def test_transition_through_4_phases(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    lifecycle.start_healing("inc-1", "high")
    full_path(lifecycle, "inc-1")
    assert phase_list(lifecycle, "inc-1") == [
        HealingPhase.HEMOSTASIS, HealingPhase.INFLAMMATION, HealingPhase.PROLIFERATION,
        HealingPhase.REMODELING, HealingPhase.HEALED,
    ]


def test_skip_phase_raises(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    lifecycle.start_healing("inc-1", "medium")
    with pytest.raises(ValueError, match="hemostasis -> proliferation"):
        lifecycle.transition_phase("inc-1", HealingPhase.PROLIFERATION)


def test_timebox_violation_detected(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    lifecycle.start_healing("inc-1", "medium")
    clock.tick(WoundHealingLifecycle.PHASE_TIMEBOX_S[HealingPhase.HEMOSTASIS] + 1)
    assert [record.incident_id for record in lifecycle.check_timebox_violations()] == ["inc-1"]
    with pytest.raises(TimeoutError, match="timebox exceeded"):
        lifecycle.transition_phase("inc-1", HealingPhase.INFLAMMATION)


def test_force_termination_breaks_sequence(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    record = lifecycle.start_healing("inc-1", "low")
    lifecycle.force_termination("inc-1", "operator override")
    assert record.current_phase is HealingPhase.HEALED
    assert "force_termination" in record.audit_trail[-1]
    assert lifecycle.healing_metrics()["forced_terminations"] == 1


def test_audit_trail_on_each_transition(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    record = lifecycle.start_healing("inc-1", "medium")
    full_path(lifecycle, "inc-1")
    assert len(record.audit_trail) == len(record.phase_transitions)
    assert sum("regenerative_transition" in entry for entry in record.audit_trail) == 4


def test_concurrent_incidents_isolated(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    first = lifecycle.start_healing("inc-1", "medium")
    second = lifecycle.start_healing("inc-2", "high")
    lifecycle.transition_phase("inc-1", HealingPhase.INFLAMMATION)
    lifecycle.transition_phase("inc-2", HealingPhase.INFLAMMATION)
    lifecycle.transition_phase("inc-2", HealingPhase.PROLIFERATION)
    assert (first.current_phase, second.current_phase) == (HealingPhase.INFLAMMATION, HealingPhase.PROLIFERATION)
    assert (len(first.phase_transitions), len(second.phase_transitions)) == (2, 3)


def test_healing_metrics_computes_mttr(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    lifecycle.start_healing("inc-1", "medium")
    clock.tick(10)
    full_path(lifecycle, "inc-1")
    lifecycle.start_healing("inc-2", "medium")
    clock.tick(30)
    full_path(lifecycle, "inc-2")
    metrics = lifecycle.healing_metrics()
    assert metrics["mttr_s"] == pytest.approx(20.0)
    assert metrics["success_rate"] == pytest.approx(1.0)
    assert metrics["phase_distribution"]["healed"] == 2


def test_critical_severity_skips_inflammation_with_warning(clock: Clock) -> None:
    lifecycle = WoundHealingLifecycle()
    record = lifecycle.start_healing("inc-1", "critical")
    lifecycle.transition_phase("inc-1", HealingPhase.PROLIFERATION)
    assert record.current_phase is HealingPhase.PROLIFERATION
    assert phase_list(lifecycle, "inc-1") == [HealingPhase.HEMOSTASIS, HealingPhase.PROLIFERATION]
    assert "warning=critical fast-path skipped inflammation" in record.audit_trail[-1]


def test_knowledge_store_integration(clock: Clock) -> None:
    store = MemoryKnowledgeStore()
    lifecycle = WoundHealingLifecycle(knowledge_store=store)  # type: ignore[arg-type]
    lifecycle.start_healing("inc-1", "critical")
    lifecycle.transition_phase("inc-1", HealingPhase.PROLIFERATION)
    lifecycle.transition_phase("inc-1", HealingPhase.REMODELING)
    assert len(store.methodik) == 2
    assert all(entry["status"] == "observed" for entry in store.methodik)
    assert "hemostasis->proliferation" in store.methodik[0]["description"]
    assert "warning=critical fast-path skipped inflammation" in store.methodik[0]["description"]
