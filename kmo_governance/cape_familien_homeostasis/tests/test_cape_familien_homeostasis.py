# [CRUX-MK]
"""Tests fuer Cape-Familien-Homeostasis (Welle-38 Phase-31 W38-T2)."""
from __future__ import annotations

import pytest

from kmo_governance.cape_familien_homeostasis import (
    CapeFamilienHomeostasis,
    FamilienHomeostasisDecision,
    FamilienRebalanceAction,
    FamilienState,
    MentalLoadSample,
)


def _sample(score: float, member: str = "martin") -> MentalLoadSample:
    return MentalLoadSample(
        sample_id="s-001",
        family_member_id=member,
        mental_load_score=score,
        timestamp=0.0,
    )


def test_init_validation() -> None:
    CapeFamilienHomeostasis()  # default OK
    with pytest.raises(ValueError):
        CapeFamilienHomeostasis(setpoint=1.5)
    with pytest.raises(ValueError):
        CapeFamilienHomeostasis(history_window=0)
    with pytest.raises(ValueError):
        CapeFamilienHomeostasis(mild_threshold_pct=30, critical_threshold_pct=20)


def test_sample_validation() -> None:
    with pytest.raises(ValueError):
        MentalLoadSample(sample_id="", family_member_id="m", mental_load_score=0.5, timestamp=0.0)
    with pytest.raises(ValueError):
        MentalLoadSample(sample_id="s", family_member_id="", mental_load_score=0.5, timestamp=0.0)
    with pytest.raises(ValueError):
        MentalLoadSample(sample_id="s", family_member_id="m", mental_load_score=1.5, timestamp=0.0)


def test_normal_state_at_setpoint() -> None:
    """Conservative: setpoint=0.5, sample=0.5 -> NORMAL."""
    h = CapeFamilienHomeostasis(setpoint=0.5)
    decision = h.record_sample(_sample(0.5))
    assert decision.state == FamilienState.NORMAL
    assert decision.action is None


def test_engage_relief_when_high() -> None:
    """High mental-load -> ENGAGE_RELIEF + REDUCE_LOAD action."""
    h = CapeFamilienHomeostasis(setpoint=0.5, mild_threshold_pct=10)
    # 0.6 = +20% from 0.5 -> deviation 20% >= mild -> ENGAGE_RELIEF or CRITICAL
    decision = h.record_sample(_sample(0.62))
    assert decision.state in (FamilienState.ENGAGE_RELIEF, FamilienState.CRITICAL)
    assert decision.action is not None


def test_enable_progress_when_low() -> None:
    """Low mental-load -> ENABLE_PROGRESS + INCREASE_LOAD."""
    h = CapeFamilienHomeostasis(setpoint=0.5, mild_threshold_pct=10)
    decision = h.record_sample(_sample(0.4))  # 20% below setpoint
    assert decision.state in (FamilienState.ENABLE_PROGRESS, FamilienState.CRITICAL)


def test_critical_state() -> None:
    """Severe deviation -> CRITICAL + HALT."""
    h = CapeFamilienHomeostasis(setpoint=0.5, critical_threshold_pct=20)
    decision = h.record_sample(_sample(0.95))  # +90% deviation
    assert decision.state == FamilienState.CRITICAL
    assert decision.action.action_type.value == "halt"
    assert decision.action.reason == "critical_deviation_l13_pflicht"


def test_decision_frozen_immutability() -> None:
    h = CapeFamilienHomeostasis()
    d = h.record_sample(_sample(0.5))
    with pytest.raises(Exception):
        d.state = FamilienState.CRITICAL  # type: ignore[misc]


def test_rolling_avg_smoothing() -> None:
    """history_window=3 smooths sudden spikes."""
    h = CapeFamilienHomeostasis(setpoint=0.5, history_window=3, critical_threshold_pct=40)
    h.record_sample(_sample(0.5))
    h.record_sample(_sample(0.5))
    # Single spike to 0.9 averaged with 0.5+0.5 = 0.633 -> not critical
    decision = h.record_sample(_sample(0.9))
    assert 0.6 <= decision.current_score <= 0.7


def test_samples_total_tracking() -> None:
    h = CapeFamilienHomeostasis(history_window=2)
    for _ in range(5):
        h.record_sample(_sample(0.5))
    assert h.get_samples_total() == 5


def test_reset_clears_history() -> None:
    h = CapeFamilienHomeostasis()
    h.record_sample(_sample(0.5))
    h.reset()
    assert h.get_samples_total() == 0


def test_get_setpoint() -> None:
    h = CapeFamilienHomeostasis(setpoint=0.7)
    assert h.get_setpoint() == 0.7


def test_action_target_member_propagates() -> None:
    h = CapeFamilienHomeostasis(setpoint=0.5)
    decision = h.record_sample(_sample(0.95, member="gerdi"))
    assert decision.action.target_member == "gerdi"


def test_normal_to_critical_transition() -> None:
    """State transitions: NORMAL -> CRITICAL with delta sample."""
    h = CapeFamilienHomeostasis(setpoint=0.5, history_window=1, critical_threshold_pct=20)
    d1 = h.record_sample(_sample(0.5))
    assert d1.state == FamilienState.NORMAL
    d2 = h.record_sample(_sample(0.95))
    assert d2.state == FamilienState.CRITICAL


# ---------------------------------------------------------------------------
# W39-P2: Real-L13-Trigger via Audit-Bus (Codex V19 W19-I3)
# ---------------------------------------------------------------------------


def test_w39p2_critical_publishes_l13_event_to_audit_bus() -> None:
    """W39-P2: CRITICAL state publishes l13_phronesis_required in audit_bus."""
    from kmo_governance.cape_familien_audit_bus import CapeFamilienAuditBus
    bus = CapeFamilienAuditBus()
    h = CapeFamilienHomeostasis(setpoint=0.5, history_window=1, audit_bus=bus)
    h.record_sample(_sample(0.95))  # CRITICAL deviation
    events = bus.query()
    assert len(events) == 1
    metadata_dict = dict(events[0].metadata)
    assert metadata_dict["event_type"] == "l13_phronesis_required"


def test_w39p2_normal_does_not_publish_l13() -> None:
    """W39-P2: NORMAL state does NOT trigger L13."""
    from kmo_governance.cape_familien_audit_bus import CapeFamilienAuditBus
    bus = CapeFamilienAuditBus()
    h = CapeFamilienHomeostasis(setpoint=0.5, history_window=1, audit_bus=bus)
    h.record_sample(_sample(0.5))  # NORMAL
    events = bus.query()
    assert len(events) == 0


def test_w39p2_no_audit_bus_does_not_crash() -> None:
    """W39-P2: ohne audit_bus arg -> CRITICAL state laeuft trotzdem ohne Crash."""
    h = CapeFamilienHomeostasis(setpoint=0.5, history_window=1)
    decision = h.record_sample(_sample(0.95))
    assert decision.state == FamilienState.CRITICAL  # state-logic unverändert


# CRUX-MK
