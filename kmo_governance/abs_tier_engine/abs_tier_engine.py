"""KMO ABS-Tier Engine [CRUX-MK].

Welle-9γ Phase-3 Modul 3.3: Hormonal-Feedback fuer Cross-Hotel-Pricing-Coordination.

Bio-Aequivalent: Endokrines System (Insulin/Glucagon-Regulation). Cross-Organ-Signal-
isierung via Hormone-Pool im Blutkreislauf. Negative Feedback verhindert Pricing-Spiral.

Anorg-Mapping: A-16 Eigen-Hypercycle (zyklische Katalyse).

Komponenten:
  - HormonePool: Append-Only Event-Stream pro Hormone-Typ
  - ABSTierRouter: Pricing-Tier-Decision via Hill-Aggregator
  - PricingHomeostasis: Anti-Hormone Negative-Feedback

Math:
  H(t+1) = H(t) * exp(-λ * Δt) + Σ new_emissions  (Decay + Source)
  Receptor-Response = H^n / (K_d^n + H^n)  (Hill mit n=2-4)
  Damping = Anti_Hormone^m / (K_a^m + Anti_Hormone^m)  (Negative Feedback)
"""

from __future__ import annotations

import enum
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Optional


# Hormone-Typen
class HormoneType(str, enum.Enum):
    PRICING_TIER = "pricing_tier"
    CAPACITY_PRESSURE = "capacity_pressure"
    DEMAND_SIGNAL = "demand_signal"
    ANTI_PRICING = "anti_pricing"  # negative-feedback hormone


# ABS-Tier Levels (Pricing-Strategy)
class ABSTier(str, enum.Enum):
    SMART = "smart"      # base-rate, low-risk
    HYBRID = "hybrid"    # mid-tier, balanced
    VOLL = "voll"        # aggressive ABS-pricing


# Constants with units
DEFAULT_HORMONE_HALFLIFE_SEC: float = 4 * 3600   # 4h half-life
DEFAULT_RECEPTOR_KD: float = 1.0
DEFAULT_RECEPTOR_HILL_N: float = 3.0
DEFAULT_PRICING_SPIRAL_THRESHOLD: float = 5.0


@dataclass(frozen=True)
class HormoneEmission:
    """Append-only emission record (immutable)."""

    hotel_id: str
    hormone_type: HormoneType
    amount: float
    timestamp: float


class HormonePool:
    """Append-only Hormone-Stream with exponential decay.

    Pre: halflife_sec > 0
    Post:
        - emit() is atomic; concentration aggregates with decay
        - concentration() reflects decay since last emission
    """

    def __init__(
        self,
        halflife_sec: float = DEFAULT_HORMONE_HALFLIFE_SEC,
        clock: Callable[[], float] = time.time,
        ttl_halflives: float = 10.0,
    ) -> None:
        """Patch E1 (Gemini-Finding O(N) Memory-Leak):

        ttl_halflives: emissions older than ttl_halflives*halflife_sec are pruned.
        After 10 half-lives, contribution is exp(-10*ln2) ≈ 0.001 — negligible.
        """
        if halflife_sec <= 0:
            raise ValueError("halflife_sec must be > 0")
        if ttl_halflives <= 0:
            raise ValueError("ttl_halflives must be > 0")
        self.halflife_sec = float(halflife_sec)
        self.ttl_sec = float(ttl_halflives) * self.halflife_sec
        # Decay-rate from half-life: exp(-λ*halflife) = 0.5 -> λ = ln(2)/halflife
        self.decay_lambda = math.log(2) / halflife_sec
        self._clock = clock
        self._lock = threading.RLock()
        # Stream pro (hotel_id, hormone_type)
        self._emissions: dict[tuple[str, HormoneType], list[HormoneEmission]] = defaultdict(list)
        self._emit_counter: int = 0  # gc trigger every N emits
        self._gc_every: int = 100

    def emit(
        self, hotel_id: str, hormone_type: HormoneType, amount: float
    ) -> HormoneEmission:
        if not hotel_id:
            raise ValueError("hotel_id required")
        if not isinstance(hormone_type, HormoneType):
            raise TypeError("hormone_type must be HormoneType")
        if amount < 0:
            raise ValueError("amount must be >= 0")
        e = HormoneEmission(
            hotel_id=hotel_id,
            hormone_type=hormone_type,
            amount=float(amount),
            timestamp=self._clock(),
        )
        with self._lock:
            self._emissions[(hotel_id, hormone_type)].append(e)
            # Patch E1: trigger periodic GC to prevent unbounded growth
            self._emit_counter += 1
            if self._emit_counter >= self._gc_every:
                self._emit_counter = 0
                self._prune_expired_locked()
        return e

    def concentration(self, hotel_id: str, hormone_type: HormoneType) -> float:
        """Σ amount_i * exp(-λ * (now - t_i))  -- decay-aware sum.

        Patch E1: prunes expired emissions on read for amortized O(1) lookups.
        """
        with self._lock:
            now = self._clock()
            cutoff = now - self.ttl_sec
            emissions = self._emissions.get((hotel_id, hormone_type), [])
            # In-place prune (since list is monotonic in timestamp under emit())
            if emissions and emissions[0].timestamp < cutoff:
                # Find first non-expired index (linear scan, but only on stale entries)
                idx = 0
                for i, e in enumerate(emissions):
                    if e.timestamp >= cutoff:
                        idx = i
                        break
                else:
                    idx = len(emissions)  # all expired
                if idx > 0:
                    del emissions[:idx]
            return sum(
                e.amount * math.exp(-self.decay_lambda * max(0.0, now - e.timestamp))
                for e in emissions
            )

    def _prune_expired_locked(self) -> int:
        """GC: remove emissions older than ttl_sec across all (hotel, type). Returns N pruned."""
        now = self._clock()
        cutoff = now - self.ttl_sec
        total_pruned = 0
        for key, emissions in list(self._emissions.items()):
            if not emissions:
                continue
            idx = 0
            for i, e in enumerate(emissions):
                if e.timestamp >= cutoff:
                    idx = i
                    break
            else:
                idx = len(emissions)
            if idx > 0:
                del emissions[:idx]
                total_pruned += idx
            # Empty lists: keep (defaultdict will not regrow on read)
        return total_pruned

    def gc_expired(self) -> int:
        """Manual GC trigger. Returns number of emissions pruned."""
        with self._lock:
            return self._prune_expired_locked()

    def cross_hotel_concentration(self, hormone_type: HormoneType) -> float:
        """Aggregate hormone-concentration across all hotels (organism-wide)."""
        total = 0.0
        with self._lock:
            now = self._clock()
            for (h, t), emissions in self._emissions.items():
                if t != hormone_type:
                    continue
                total += sum(
                    e.amount * math.exp(-self.decay_lambda * max(0.0, now - e.timestamp))
                    for e in emissions
                )
        return total

    def purge_hotel(self, hotel_id: str) -> int:
        """GDPR cascade-delete: all emissions for one hotel."""
        with self._lock:
            keys = [k for k in self._emissions if k[0] == hotel_id]
            count = sum(len(self._emissions[k]) for k in keys)
            for k in keys:
                del self._emissions[k]
            return count


class ABSTierRouter:
    """Pricing-Tier-Decision via Hill-aggregation of hormone-receptors.

    Pre: pool is HormonePool; thresholds in [0, 1]
    Post: route(hotel_id, request) returns ABSTier based on aggregated Hill-Y
    """

    def __init__(
        self,
        pool: HormonePool,
        K_d: float = DEFAULT_RECEPTOR_KD,
        hill_n: float = DEFAULT_RECEPTOR_HILL_N,
        smart_max_y: float = 0.3,
        hybrid_max_y: float = 0.7,
    ) -> None:
        if K_d <= 0 or hill_n <= 0:
            raise ValueError("K_d and hill_n must be > 0")
        if not (0 <= smart_max_y < hybrid_max_y <= 1):
            raise ValueError("0 <= smart_max_y < hybrid_max_y <= 1")
        self.pool = pool
        self.K_d = float(K_d)
        self.hill_n = float(hill_n)
        self.smart_max_y = float(smart_max_y)
        self.hybrid_max_y = float(hybrid_max_y)

    def receptor_response(self, hotel_id: str) -> float:
        """Hill-Y from aggregated DEMAND_SIGNAL + CAPACITY_PRESSURE.

        Patch D1 (Gemini-Finding "Blind Receptors"): ANTI_PRICING dampens the
        receptor by reducing effective signal-strength. Closes the negative
        feedback loop so PricingHomeostasis actually influences routing.
        """
        h = (
            self.pool.concentration(hotel_id, HormoneType.DEMAND_SIGNAL)
            + self.pool.concentration(hotel_id, HormoneType.CAPACITY_PRESSURE)
        )
        anti = self.pool.concentration(hotel_id, HormoneType.ANTI_PRICING)
        # Anti-pricing dampens via 1/(1+anti/K_d) factor (smooth, monotone)
        if anti > 0 and self.K_d > 0:
            h = h / (1.0 + anti / self.K_d)
        if h <= 0:
            return 0.0
        sn = h ** self.hill_n
        return sn / (self.K_d ** self.hill_n + sn)

    def route(self, hotel_id: str) -> ABSTier:
        y = self.receptor_response(hotel_id)
        if y < self.smart_max_y:
            return ABSTier.SMART
        if y < self.hybrid_max_y:
            return ABSTier.HYBRID
        return ABSTier.VOLL


class PricingHomeostasis:
    """Negative-Feedback against Pricing-Spiral.

    Pre: pool is HormonePool; spiral_threshold > 0
    Post: check_and_dampen() emits ANTI_PRICING when spiral-condition triggered
    """

    def __init__(
        self,
        pool: HormonePool,
        spiral_threshold: float = DEFAULT_PRICING_SPIRAL_THRESHOLD,
        anti_K_a: float = 1.0,
        anti_hill_m: float = 3.0,
    ) -> None:
        if spiral_threshold <= 0:
            raise ValueError("spiral_threshold must be > 0")
        if anti_K_a <= 0 or anti_hill_m <= 0:
            raise ValueError("anti_K_a and anti_hill_m must be > 0")
        self.pool = pool
        self.spiral_threshold = float(spiral_threshold)
        self.anti_K_a = float(anti_K_a)
        self.anti_hill_m = float(anti_hill_m)

    def damping_factor(self, hotel_id: str) -> float:
        """Anti-Hormone^m / (K_a^m + Anti-Hormone^m) -- damping in [0,1]."""
        anti = self.pool.concentration(hotel_id, HormoneType.ANTI_PRICING)
        if anti <= 0:
            return 0.0
        am = anti ** self.anti_hill_m
        return am / (self.anti_K_a ** self.anti_hill_m + am)

    def check_and_dampen(self, hotel_id: str) -> bool:
        """If pricing-tier concentration > threshold: emit ANTI_PRICING.

        Returns True if dampening was applied.
        """
        pricing_conc = self.pool.concentration(hotel_id, HormoneType.PRICING_TIER)
        if pricing_conc > self.spiral_threshold:
            # Emit anti-pricing proportional to overshoot
            overshoot = pricing_conc - self.spiral_threshold
            self.pool.emit(hotel_id, HormoneType.ANTI_PRICING, overshoot * 0.5)
            return True
        return False


# CRUX-MK
