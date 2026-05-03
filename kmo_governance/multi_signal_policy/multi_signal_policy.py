"""KMO Multi-Signal-Policy [CRUX-MK].

Welle-9γ Phase-3 Modul 3.1: Hill-Funktion-Aggregator mit N Eingaengen +
Markov-State-Machine fuer Policy-Modes + Backwards-Compat zu binary approval-gate.

Bio-Aequivalent: Allosterische Regulation (MWC-Modell). Multi-Site-Bindung mit
Cooperativity. Pro Signal eigene K_d (Schwelle) und n (Hill-Coefficient).

Anorg-Mapping: A-12 Wang-Tiles (Constraint-Satisfaction).

Math:
    Score = Σ_i w_i * S_i^n_i / (K_i^n_i + S_i^n_i)
    State-Transitions: probabilistisch nach Score-Schwellen + Hysterese
    Master-Gleichung: dP(s)/dt = Σ k_ij P(j) - Σ k_ji P(s)
"""

from __future__ import annotations

import enum
import math
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class SignalSpec:
    """Specification for one Hill-input signal."""

    name: str
    K_d: float          # half-saturation threshold
    hill_n: float       # Hill-coefficient (cooperativity)
    weight: float = 1.0  # contribution-weight in aggregate

    def __post_init__(self) -> None:
        if self.K_d <= 0:
            raise ValueError(f"K_d must be > 0, got {self.K_d}")
        if self.hill_n <= 0:
            raise ValueError(f"hill_n must be > 0, got {self.hill_n}")
        if self.weight < 0:
            raise ValueError(f"weight must be >= 0, got {self.weight}")


class PolicyState(str, enum.Enum):
    """Markov-State-Model fuer Policy-Modes."""

    AGGRESSIVE = "aggressive"
    MODERATE = "moderate"
    CONSERVATIVE = "conservative"
    EMERGENCY = "emergency"
    MAINTENANCE = "maintenance"


# Default state-transition score-thresholds (Hill-Y-aggregate space).
# Hysterese: enter > exit to avoid flapping (Schmitt-Trigger).
DEFAULT_TRANSITIONS: dict[PolicyState, dict[str, float]] = {
    PolicyState.AGGRESSIVE: {
        "exit_to_moderate": 0.65,
    },
    PolicyState.MODERATE: {
        "enter_aggressive": 0.80,
        "exit_to_conservative": 0.40,
    },
    PolicyState.CONSERVATIVE: {
        "enter_moderate": 0.50,
        "exit_to_emergency": 0.20,
    },
    PolicyState.EMERGENCY: {
        "enter_conservative": 0.35,
    },
    PolicyState.MAINTENANCE: {
        "enter_conservative": 0.30,
    },
}


class MultiSignalAggregator:
    """N-input Hill-aggregator with per-signal K_d, n, weight.

    Pre: signal_specs is dict[name, SignalSpec]
    Post: aggregate_score(signals_dict) returns weighted sum of Hill-Y values
    """

    def __init__(self, signal_specs: dict[str, SignalSpec]) -> None:
        if not signal_specs:
            raise ValueError("at least one signal_spec required")
        self.signal_specs = signal_specs

    def hill_y(self, name: str, signal_value: float) -> float:
        spec = self.signal_specs.get(name)
        if spec is None:
            raise KeyError(f"unknown signal {name!r}")
        if signal_value < 0:
            return 0.0
        sn = signal_value ** spec.hill_n
        return sn / (spec.K_d ** spec.hill_n + sn)

    def aggregate_score(self, signals: dict[str, float]) -> float:
        """Score = Σ w_i * Hill-Y_i / Σ w_i  (normalized to [0,1])."""
        total_weight = 0.0
        weighted_sum = 0.0
        for name, value in signals.items():
            spec = self.signal_specs.get(name)
            if spec is None:
                continue
            y = self.hill_y(name, value)
            weighted_sum += spec.weight * y
            total_weight += spec.weight
        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight


class PolicyStateMachine:
    """Markov-State-Machine with Hill-aggregate-driven transitions + hysterese.

    Pre: aggregator is MultiSignalAggregator
    Post:
        - tick(signals) updates current_state based on aggregate-score + transition-rules
        - transitions are hysteresis-protected (enter > exit thresholds)
    """

    def __init__(
        self,
        aggregator: MultiSignalAggregator,
        initial_state: PolicyState = PolicyState.MODERATE,
        transitions: Optional[dict] = None,
    ) -> None:
        self.aggregator = aggregator
        self._state = initial_state
        self._transitions = transitions if transitions is not None else DEFAULT_TRANSITIONS
        self._lock = threading.RLock()
        self._history: list[tuple[float, PolicyState]] = []

    @property
    def state(self) -> PolicyState:
        return self._state

    def tick(self, signals: dict[str, float], force: Optional[PolicyState] = None) -> PolicyState:
        """Compute aggregate-score + apply transitions. Returns new state."""
        with self._lock:
            if force is not None:
                self._transition_to(force)
                return self._state
            score = self.aggregator.aggregate_score(signals)
            new_state = self._state
            rules = self._transitions.get(self._state, {})
            # Try transitions in deterministic order
            if self._state == PolicyState.AGGRESSIVE and score < rules.get("exit_to_moderate", 0):
                new_state = PolicyState.MODERATE
            elif self._state == PolicyState.MODERATE:
                if score >= rules.get("enter_aggressive", 1):
                    new_state = PolicyState.AGGRESSIVE
                elif score < rules.get("exit_to_conservative", 0):
                    new_state = PolicyState.CONSERVATIVE
            elif self._state == PolicyState.CONSERVATIVE:
                if score >= rules.get("enter_moderate", 1):
                    new_state = PolicyState.MODERATE
                elif score < rules.get("exit_to_emergency", 0):
                    new_state = PolicyState.EMERGENCY
            elif self._state == PolicyState.EMERGENCY:
                if score >= rules.get("enter_conservative", 1):
                    new_state = PolicyState.CONSERVATIVE
            elif self._state == PolicyState.MAINTENANCE:
                if score >= rules.get("enter_conservative", 1):
                    new_state = PolicyState.CONSERVATIVE
            if new_state != self._state:
                self._transition_to(new_state)
            return self._state

    def _transition_to(self, new_state: PolicyState) -> None:
        if new_state != self._state:
            self._state = new_state
            self._history.append((len(self._history), new_state))


def binary_approval_adapter(
    multi_check: Callable[[dict], float], threshold: float = 0.5
) -> Callable[[dict], bool]:
    """Backwards-Compat-Adapter: multi-signal score -> bool via threshold.

    Wraps a multi-signal aggregator into the legacy `exit_criteria_func: -> bool` API.
    """
    if not (0 <= threshold <= 1):
        raise ValueError("threshold must be in [0,1]")

    def adapted(signals: dict) -> bool:
        return multi_check(signals) >= threshold

    return adapted


# CRUX-MK
