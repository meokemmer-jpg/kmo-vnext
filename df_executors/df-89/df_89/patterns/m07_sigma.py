"""CRUX-MK M-07 Sigma-Faktor-Switch global mode pattern for DF-89."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import time

from pydantic import BaseModel, ConfigDict, Field


class Mode(str, Enum):
    """Runtime modes managed by the global Sigma-Faktor-Switch."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    RECOVERY = "recovery"
    PANIC = "panic"


class SigmaFactor(BaseModel):
    """Competing sigma factor for a target runtime mode."""

    model_config = ConfigDict(frozen=True)

    mode: Mode
    concentration: float = Field(ge=0.0)
    affinity_K: float = Field(gt=0.0)

    @property
    def weight(self) -> float:
        """Pre: affinity_K > 0. Post: returns sigma_i / K_i."""
        return self.concentration / self.affinity_K


@dataclass(frozen=True)
class ModeChange:
    """Audit-trail record for an accepted mode transition."""

    previous: Mode
    current: Mode
    owner: str
    at_s: float


@dataclass
class ModeSwitch:
    """Global mode switch with RNAP-style competition and hysteresis.

    Pre: theta_on > theta_off and min_dwell_time_s >= 0.
    Post: current_mode changes only through tick() and every change is audited.
    """

    theta_on: float = 0.60
    theta_off: float = 0.40
    min_dwell_time_s: float = 0.0
    current_mode: Mode = Mode.NORMAL
    default_owner: str = "system"
    _clock: Callable[[], float] = time.monotonic
    _sigmas: list[SigmaFactor] = field(default_factory=list, init=False)
    _observers: list[Callable[[Mode, Mode], None]] = field(default_factory=list, init=False)
    _handlers: dict[Mode, list[Callable[[Mode], None]]] = field(
        default_factory=lambda: {mode: [] for mode in Mode}, init=False
    )
    audit_trail: list[ModeChange] = field(default_factory=list, init=False)
    _last_change_at_s: float = field(init=False)

    def __post_init__(self) -> None:
        """Pre: dataclass fields are initialized. Post: invariants are enforced."""
        if self.theta_on <= self.theta_off:
            raise ValueError("theta_on must be greater than theta_off")
        if self.min_dwell_time_s < 0:
            raise ValueError("min_dwell_time_s must be non-negative")
        self._last_change_at_s = self._clock()

    def add_sigma(self, sigma: SigmaFactor) -> None:
        """Pre: sigma is validated. Post: sigma participates in dominance."""
        self._sigmas.append(sigma)

    def compute_dominance(self) -> dict[Mode, float]:
        """Pre: registered sigmas are valid. Post: probabilities sum to 1 or 0."""
        weights = {mode: 0.0 for mode in Mode}
        for sigma in self._sigmas:
            weights[sigma.mode] += sigma.weight
        total = sum(weights.values())
        if total == 0.0:
            return weights
        return {mode: weight / total for mode, weight in weights.items()}

    def register_observer(self, callback: Callable[[Mode, Mode], None]) -> None:
        """Pre: callback accepts old and new mode. Post: callback fires on changes."""
        self._observers.append(callback)

    def register_handler(self, mode: Mode, callback: Callable[[Mode], None]) -> None:
        """Pre: callback accepts the active mode. Post: callback fires for mode."""
        self._handlers[mode].append(callback)

    def tick(self, owner: str | None = None) -> Mode:
        """Pre: sigmas reflect current signals. Post: returns current active mode."""
        dominance = self.compute_dominance()
        target = max(dominance, key=dominance.get)
        if not self._should_switch(target, dominance):
            return self.current_mode

        previous = self.current_mode
        self.current_mode = target
        self._last_change_at_s = self._clock()
        change = ModeChange(
            previous=previous,
            current=target,
            owner=owner or self.default_owner,
            at_s=self._last_change_at_s,
        )
        self.audit_trail.append(change)
        for observer in self._observers:
            observer(previous, target)
        for handler in self._handlers[target]:
            handler(target)
        return self.current_mode

    def _should_switch(self, target: Mode, dominance: dict[Mode, float]) -> bool:
        """Pre: dominance contains every Mode. Post: true only past hysteresis."""
        if target == self.current_mode:
            return False
        now = self._clock()
        if now - self._last_change_at_s < self.min_dwell_time_s:
            return False
        target_on = dominance[target] > self.theta_on
        current_off = dominance[self.current_mode] < self.theta_off
        return target_on and current_off
