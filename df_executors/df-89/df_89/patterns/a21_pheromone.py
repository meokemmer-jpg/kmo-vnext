"""CRUX-MK A-21 Pheromone-Trails success-weighted routing pattern."""

from __future__ import annotations

import math
import random
import threading
from dataclasses import dataclass, field
from typing import TypeAlias

EdgeKey: TypeAlias = tuple[str, str]


@dataclass
class PheromoneTrail:
    """Shared stigmergic routing state for DF-89 tool or agent selection."""

    pheromones: dict[EdgeKey, float] = field(default_factory=dict)
    evaporation_rate: float = 0.1
    q: float = 1.0
    alpha: float = 1.0
    tau_max: float = 100.0
    ttl_threshold: float = 0.001
    failure_decay: float = 0.5
    rng: random.Random = field(default_factory=random.Random, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        """Pre: dataclass fields are assigned. Post: numeric invariants hold."""
        if not 0.0 <= self.evaporation_rate <= 1.0:
            raise ValueError("evaporation_rate must be in [0, 1]")
        if self.q <= 0.0:
            raise ValueError("q must be positive")
        if self.alpha <= 0.0:
            raise ValueError("alpha must be positive")
        if self.tau_max <= 0.0:
            raise ValueError("tau_max must be positive")
        if self.ttl_threshold < 0.0:
            raise ValueError("ttl_threshold must be non-negative")
        if not 0.0 <= self.failure_decay <= 1.0:
            raise ValueError("failure_decay must be in [0, 1]")

        with self._lock:
            self.pheromones = {
                edge: self._cap_tau(value)
                for edge, value in self.pheromones.items()
                if value >= self.ttl_threshold
            }

    def deposit(self, edge: EdgeKey, success: bool, latency_ms: float) -> None:
        """Pre: external outcome is explicit. Post: edge tau is rewarded or penalized."""
        self._validate_edge(edge)
        if not isinstance(success, bool):
            raise TypeError("success must be an explicit bool")
        if latency_ms <= 0.0:
            raise ValueError("latency_ms must be positive")

        with self._lock:
            current = self.pheromones.get(edge, 0.0)
            if success:
                updated = current + (self.q / latency_ms)
            else:
                updated = current * self.failure_decay
            self._set_or_purge(edge, updated)

    def evaporate(self) -> None:
        """Pre: trail state may contain edges. Post: tau is globally evaporated."""
        with self._lock:
            retention = 1.0 - self.evaporation_rate
            decayed = {
                edge: value * retention
                for edge, value in self.pheromones.items()
                if value * retention >= self.ttl_threshold
            }
            self.pheromones = decayed

    def route(self, source: str, candidates: list[str]) -> str:
        """Pre: candidates are available. Post: returns one target by tau-weighted routing."""
        if not source:
            raise ValueError("source must be non-empty")
        if not candidates:
            raise ValueError("candidates must not be empty")
        if any(not candidate for candidate in candidates):
            raise ValueError("candidates must be non-empty strings")

        with self._lock:
            values = [self.pheromones.get((source, target), 0.0) for target in candidates]
            if all(value < self.ttl_threshold for value in values):
                return self.rng.choice(candidates)

            weights = [self._route_weight(value) for value in values]
            total = sum(weights)
            if total <= 0.0 or not math.isfinite(total):
                return self.rng.choice(candidates)

            cursor = self.rng.random() * total
            cumulative = 0.0
            for target, weight in zip(candidates, weights, strict=True):
                cumulative += weight
                if cursor <= cumulative:
                    return target
            return candidates[-1]

    def tau(self, edge: EdgeKey) -> float:
        """Pre: edge has source and target. Post: returns current pheromone or zero."""
        self._validate_edge(edge)
        with self._lock:
            return self.pheromones.get(edge, 0.0)

    def snapshot(self) -> dict[EdgeKey, float]:
        """Pre: trail exists. Post: returns a stable copy of pheromone state."""
        with self._lock:
            return dict(self.pheromones)

    def exponential_decay(self, tau_0: float, ticks: float) -> float:
        """Pre: tau_0 and ticks are non-negative. Post: returns tau_0 * e^(-lambda*t)."""
        if tau_0 < 0.0:
            raise ValueError("tau_0 must be non-negative")
        if ticks < 0.0:
            raise ValueError("ticks must be non-negative")
        return tau_0 * math.exp(-self.evaporation_rate * ticks)

    def _route_weight(self, tau: float) -> float:
        if tau <= 0.0:
            return 0.0
        return math.pow(min(tau, self.tau_max), self.alpha)

    def _set_or_purge(self, edge: EdgeKey, value: float) -> None:
        capped = self._cap_tau(value)
        if capped < self.ttl_threshold:
            self.pheromones.pop(edge, None)
            return
        self.pheromones[edge] = capped

    def _cap_tau(self, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("pheromone values must be finite")
        return max(0.0, min(value, self.tau_max))

    @staticmethod
    def _validate_edge(edge: EdgeKey) -> None:
        if (
            not isinstance(edge, tuple)
            or len(edge) != 2
            or not isinstance(edge[0], str)
            or not isinstance(edge[1], str)
            or not edge[0]
            or not edge[1]
        ):
            raise ValueError("edge must be a non-empty (source, target) tuple")

