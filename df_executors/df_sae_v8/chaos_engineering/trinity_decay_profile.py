"""Trinity-Decay-Profile (Domain-Extension-Module) [CRUX-MK].

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

Domain-Extension-Module: SAE-Trinity-spezifische variant-Decay-Curves.
Conservative=exp-recovery, Aggressive=linear-ramp-down, Contrarian=binaer.

This is OPTIONAL: the Pattern-Core (`apoptose_core`) is profile-agnostic
and runs with any DecayProfile. Trinity is one specific profile-set; a
consumer outside SAE can plug in their own (e.g., SARS-CoV-spike-decay,
linear-burnout, step-function).

Activation:
    `ChaosOrchestratorConfig(use_trinity_decay=True)` (default for SAE).
    `False` -> falls back to no-decay (binary CONTRARIAN-style).
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass


# Trinity-spezifische Defaults (Domain-Extension)
DEFAULT_RECOVERY_TIME_CONSTANT_SEC: float = 30.0
DEFAULT_AGGRESSIVE_RAMP_PER_SEC: float = 0.1
DEFAULT_RECOVERY_DEADLINE_CONSERVATIVE_SEC: float = 60.0
DEFAULT_RECOVERY_DEADLINE_AGGRESSIVE_SEC: float = 180.0
DEFAULT_RECOVERY_DEADLINE_CONTRARIAN_SEC: float = float("inf")


class SlotVariant(str, enum.Enum):
    """SAE-Trinity-Slot-Varianten (Domain-Extension)."""
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    CONTRARIAN = "contrarian"


@dataclass(frozen=True)
class ConservativeDecay:
    """Exponential recovery (apoptotic-Bcl-2 self-rescue style)."""

    name: str = "conservative"
    tau: float = DEFAULT_RECOVERY_TIME_CONSTANT_SEC
    deadline_sec: float = DEFAULT_RECOVERY_DEADLINE_CONSERVATIVE_SEC

    def compute_health(self, baseline: float, dt: float, is_crashed: bool) -> float:
        if is_crashed:
            return 0.0
        if dt <= 0:
            return baseline
        missing = 1.0 - baseline
        recovered = missing * (1.0 - math.exp(-dt / self.tau))
        return min(1.0, baseline + recovered)

    def recovery_time_to_threshold(
        self, current_health: float, threshold: float, is_crashed: bool,
    ) -> float:
        if is_crashed:
            return float("inf")
        if current_health >= threshold:
            return 0.0
        if 1.0 - current_health <= 0:
            return float("inf")
        ratio = (threshold - current_health) / (1.0 - current_health)
        if ratio >= 1.0:
            return float("inf")
        return -self.tau * math.log(1.0 - ratio)

    def recovery_deadline_sec(self) -> float:
        return self.deadline_sec


@dataclass(frozen=True)
class AggressiveDecay:
    """Linear ramp-down without recovery (no auto-rescue)."""

    name: str = "aggressive"
    ramp_per_sec: float = DEFAULT_AGGRESSIVE_RAMP_PER_SEC
    deadline_sec: float = DEFAULT_RECOVERY_DEADLINE_AGGRESSIVE_SEC

    def compute_health(self, baseline: float, dt: float, is_crashed: bool) -> float:
        if is_crashed:
            return 0.0
        if dt <= 0:
            return baseline
        return max(0.0, baseline - self.ramp_per_sec * dt)

    def recovery_time_to_threshold(
        self, current_health: float, threshold: float, is_crashed: bool,
    ) -> float:
        if is_crashed:
            return float("inf")
        if current_health >= threshold:
            return 0.0
        return float("inf")  # no recovery without explicit reset

    def recovery_deadline_sec(self) -> float:
        return self.deadline_sec


@dataclass(frozen=True)
class ContrarianDecay:
    """Binary state, no time-evolution."""

    name: str = "contrarian"
    deadline_sec: float = DEFAULT_RECOVERY_DEADLINE_CONTRARIAN_SEC

    def compute_health(self, baseline: float, dt: float, is_crashed: bool) -> float:
        if is_crashed:
            return 0.0
        return baseline

    def recovery_time_to_threshold(
        self, current_health: float, threshold: float, is_crashed: bool,
    ) -> float:
        if is_crashed:
            return float("inf")
        return 0.0 if current_health >= threshold else float("inf")

    def recovery_deadline_sec(self) -> float:
        return self.deadline_sec


def profile_for_variant(variant: SlotVariant):
    """Resolve Trinity-Variant -> DecayProfile-Instance (Extension-Resolver)."""
    if variant is SlotVariant.CONSERVATIVE:
        return ConservativeDecay()
    if variant is SlotVariant.AGGRESSIVE:
        return AggressiveDecay()
    return ContrarianDecay()


# [CRUX-MK]
