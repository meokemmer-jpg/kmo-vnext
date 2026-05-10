from __future__ import annotations

import enum
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


DEFAULT_HISTORY_WINDOW: int = 5
DEFAULT_MILD_TOLERANCE: float = 0.10
DEFAULT_UNDER_RATIO: float = 0.80
DEFAULT_OVER_RATIO: float = 1.20
DEFAULT_CRITICAL_UNDER_RATIO: float = 0.50
DEFAULT_CRITICAL_OVER_RATIO: float = 1.50
DEFAULT_CRITICAL_BLOCKED_RATIO: float = 0.40


class VelocityState(str, enum.Enum):
    NORMAL = "normal"
    MILD_DEVIATION = "mild_deviation"
    UNDER_VELOCITY = "under_velocity"
    OVER_VELOCITY = "over_velocity"
    CRITICAL = "critical"


@dataclass(frozen=True)
class VelocitySample:
    sprint_id: str
    team_id: str
    planned_pts: float
    completed_pts: float
    blocked_pts: float


@dataclass(frozen=True)
class VelocityDecision:
    sprint_id: str
    team_id: str
    state: VelocityState
    rolling_velocity: float
    setpoint: float
    deviation_ratio: float
    sample_count: int
    action: str
    reason: str


class NineDotsPMOHomeostasis:
    """Project-velocity homeostasis for 9dots PMO teams.

    Setpoint is the ideal sprint velocity in story-points per week.
    Each team receives an independent rolling average over recent samples.
    """

    def __init__(
        self,
        setpoint: float,
        history_window: int = DEFAULT_HISTORY_WINDOW,
        mild_tolerance: float = DEFAULT_MILD_TOLERANCE,
        under_ratio: float = DEFAULT_UNDER_RATIO,
        over_ratio: float = DEFAULT_OVER_RATIO,
        critical_under_ratio: float = DEFAULT_CRITICAL_UNDER_RATIO,
        critical_over_ratio: float = DEFAULT_CRITICAL_OVER_RATIO,
        critical_blocked_ratio: float = DEFAULT_CRITICAL_BLOCKED_RATIO,
    ) -> None:
        if setpoint <= 0:
            raise ValueError("setpoint must be > 0")
        if history_window <= 0:
            raise ValueError("history_window must be > 0")
        if not (0 <= mild_tolerance < 1):
            raise ValueError("mild_tolerance must be in [0, 1)")
        if not (0 < critical_under_ratio < under_ratio < 1):
            raise ValueError("critical_under_ratio < under_ratio < 1 required")
        if not (1 < over_ratio < critical_over_ratio):
            raise ValueError("1 < over_ratio < critical_over_ratio required")
        if not (0 <= critical_blocked_ratio <= 1):
            raise ValueError("critical_blocked_ratio must be in [0, 1]")

        self.setpoint = float(setpoint)
        self.history_window = int(history_window)
        self.mild_tolerance = float(mild_tolerance)
        self.under_ratio = float(under_ratio)
        self.over_ratio = float(over_ratio)
        self.critical_under_ratio = float(critical_under_ratio)
        self.critical_over_ratio = float(critical_over_ratio)
        self.critical_blocked_ratio = float(critical_blocked_ratio)

        self._samples_by_team: dict[str, Deque[VelocitySample]] = {}
        self._last_decision_by_team: dict[str, VelocityDecision] = {}
        self._lock = threading.RLock()

    def record_sample(self, sample: VelocitySample) -> VelocityDecision:
        self._validate_sample(sample)

        with self._lock:
            team_samples = self._samples_by_team.setdefault(
                sample.team_id,
                deque(maxlen=self.history_window),
            )
            team_samples.append(sample)

            rolling_velocity = self._rolling_velocity(team_samples)
            deviation_ratio = rolling_velocity / self.setpoint
            state = self._classify(deviation_ratio, sample)
            decision = VelocityDecision(
                sprint_id=sample.sprint_id,
                team_id=sample.team_id,
                state=state,
                rolling_velocity=rolling_velocity,
                setpoint=self.setpoint,
                deviation_ratio=deviation_ratio,
                sample_count=len(team_samples),
                action=self._action_for(state),
                reason=self._reason_for(state, deviation_ratio, sample),
            )
            self._last_decision_by_team[sample.team_id] = decision
            return decision

    def last_decision(self, team_id: str) -> Optional[VelocityDecision]:
        with self._lock:
            return self._last_decision_by_team.get(team_id)

    def samples_for_team(self, team_id: str) -> tuple[VelocitySample, ...]:
        with self._lock:
            return tuple(self._samples_by_team.get(team_id, ()))

    def reset_team(self, team_id: str) -> None:
        with self._lock:
            self._samples_by_team.pop(team_id, None)
            self._last_decision_by_team.pop(team_id, None)

    def tracked_teams(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._samples_by_team))

    def _classify(self, deviation_ratio: float, sample: VelocitySample) -> VelocityState:
        planned_total = sample.completed_pts + sample.blocked_pts
        blocked_ratio = sample.blocked_pts / planned_total if planned_total > 0 else 0.0

        if (
            deviation_ratio <= self.critical_under_ratio
            or deviation_ratio >= self.critical_over_ratio
            or blocked_ratio >= self.critical_blocked_ratio
        ):
            return VelocityState.CRITICAL
        if deviation_ratio < self.under_ratio:
            return VelocityState.UNDER_VELOCITY
        if deviation_ratio > self.over_ratio:
            return VelocityState.OVER_VELOCITY
        if abs(1.0 - deviation_ratio) > self.mild_tolerance:
            return VelocityState.MILD_DEVIATION
        return VelocityState.NORMAL

    def _action_for(self, state: VelocityState) -> str:
        return {
            VelocityState.NORMAL: "maintain_current_sprint_cadence",
            VelocityState.MILD_DEVIATION: "monitor_and_rebalance_next_planning",
            VelocityState.UNDER_VELOCITY: "reduce_wip_and_remove_delivery_blockers",
            VelocityState.OVER_VELOCITY: "validate_quality_capacity_and_prevent_burnout",
            VelocityState.CRITICAL: "escalate_pmo_intervention_and_rebaseline_commitments",
        }[state]

    def _reason_for(
        self,
        state: VelocityState,
        deviation_ratio: float,
        sample: VelocitySample,
    ) -> str:
        percent = round(deviation_ratio * 100.0, 2)
        if state is VelocityState.NORMAL:
            return f"rolling velocity is within tolerance at {percent}% of setpoint"
        if state is VelocityState.MILD_DEVIATION:
            return f"rolling velocity is mildly outside tolerance at {percent}% of setpoint"
        if state is VelocityState.UNDER_VELOCITY:
            return f"rolling velocity is below under-velocity threshold at {percent}% of setpoint"
        if state is VelocityState.OVER_VELOCITY:
            return f"rolling velocity is above over-velocity threshold at {percent}% of setpoint"
        return (
            "critical velocity stress detected "
            f"at {percent}% of setpoint with {sample.blocked_pts} blocked points"
        )

    @staticmethod
    def _rolling_velocity(samples: Deque[VelocitySample]) -> float:
        return sum(sample.completed_pts for sample in samples) / len(samples)

    @staticmethod
    def _validate_sample(sample: VelocitySample) -> None:
        if not sample.sprint_id:
            raise ValueError("sprint_id must not be empty")
        if not sample.team_id:
            raise ValueError("team_id must not be empty")
        if sample.planned_pts < 0:
            raise ValueError("planned_pts must be >= 0")
        if sample.completed_pts < 0:
            raise ValueError("completed_pts must be >= 0")
        if sample.blocked_pts < 0:
            raise ValueError("blocked_pts must be >= 0")
        if sample.completed_pts + sample.blocked_pts > sample.planned_pts:
            raise ValueError("completed_pts + blocked_pts must not exceed planned_pts")
