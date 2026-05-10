from __future__ import annotations

import sys
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.ninedots_pmo_homeostasis import (  # noqa: E402
    NineDotsPMOHomeostasis,
    VelocityDecision,
    VelocitySample,
    VelocityState,
)


def sample(
    sprint_id: str = "s1",
    team_id: str = "team-a",
    planned_pts: float = 40.0,
    completed_pts: float = 40.0,
    blocked_pts: float = 0.0,
) -> VelocitySample:
    return VelocitySample(
        sprint_id=sprint_id,
        team_id=team_id,
        planned_pts=planned_pts,
        completed_pts=completed_pts,
        blocked_pts=blocked_pts,
    )


def test_velocity_sample_is_frozen():
    s = sample()
    with pytest.raises(Exception):
        s.completed_pts = 10.0


def test_velocity_decision_is_frozen():
    d = NineDotsPMOHomeostasis(setpoint=40.0).record_sample(sample())
    assert isinstance(d, VelocityDecision)
    with pytest.raises(Exception):
        d.state = VelocityState.CRITICAL


def test_constructor_validates_setpoint_and_history_window():
    with pytest.raises(ValueError):
        NineDotsPMOHomeostasis(setpoint=0.0)
    with pytest.raises(ValueError):
        NineDotsPMOHomeostasis(setpoint=40.0, history_window=0)


def test_constructor_validates_threshold_ordering():
    with pytest.raises(ValueError):
        NineDotsPMOHomeostasis(setpoint=40.0, critical_under_ratio=0.90)
    with pytest.raises(ValueError):
        NineDotsPMOHomeostasis(setpoint=40.0, critical_over_ratio=1.10)


def test_record_sample_rejects_invalid_sample_values():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    with pytest.raises(ValueError):
        engine.record_sample(sample(sprint_id=""))
    with pytest.raises(ValueError):
        engine.record_sample(sample(team_id=""))
    with pytest.raises(ValueError):
        engine.record_sample(sample(planned_pts=10.0, completed_pts=9.0, blocked_pts=2.0))


def test_normal_state_when_velocity_matches_setpoint():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    decision = engine.record_sample(sample(completed_pts=40.0))
    assert decision.state is VelocityState.NORMAL
    assert decision.rolling_velocity == pytest.approx(40.0)
    assert decision.deviation_ratio == pytest.approx(1.0)


def test_mild_deviation_state_within_under_over_band():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    decision = engine.record_sample(sample(completed_pts=35.0))
    assert decision.state is VelocityState.MILD_DEVIATION
    assert decision.action == "monitor_and_rebalance_next_planning"


def test_under_velocity_state_when_rolling_average_is_low():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    decision = engine.record_sample(sample(completed_pts=30.0))
    assert decision.state is VelocityState.UNDER_VELOCITY
    assert decision.deviation_ratio == pytest.approx(0.75)


def test_over_velocity_state_when_rolling_average_is_high():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    decision = engine.record_sample(sample(planned_pts=60.0, completed_pts=50.0))
    assert decision.state is VelocityState.OVER_VELOCITY
    assert decision.deviation_ratio == pytest.approx(1.25)


def test_critical_state_for_extreme_under_velocity():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    decision = engine.record_sample(sample(completed_pts=20.0))
    assert decision.state is VelocityState.CRITICAL
    assert "critical velocity stress" in decision.reason


def test_critical_state_for_high_blocked_ratio():
    engine = NineDotsPMOHomeostasis(setpoint=40.0)
    decision = engine.record_sample(sample(planned_pts=40.0, completed_pts=20.0, blocked_pts=20.0))
    assert decision.state is VelocityState.CRITICAL
    assert decision.action == "escalate_pmo_intervention_and_rebaseline_commitments"


def test_per_team_rolling_average_is_isolated_and_windowed():
    engine = NineDotsPMOHomeostasis(setpoint=40.0, history_window=2)
    engine.record_sample(sample(sprint_id="a1", team_id="alpha", completed_pts=40.0))
    engine.record_sample(sample(sprint_id="b1", team_id="beta", completed_pts=20.0))
    decision = engine.record_sample(sample(sprint_id="a2", team_id="alpha", completed_pts=30.0))

    assert decision.team_id == "alpha"
    assert decision.rolling_velocity == pytest.approx(35.0)
    assert engine.last_decision("beta").rolling_velocity == pytest.approx(20.0)
    assert len(engine.samples_for_team("alpha")) == 2
    assert engine.tracked_teams() == ("alpha", "beta")
