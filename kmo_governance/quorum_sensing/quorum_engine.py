"""KMO Quorum-Sensing Engine [CRUX-MK].

Welle-9β Phase-2 Modul 2.1: Tissue-Layer Quorum-Sensing.

Bio-Aequivalent: Bakterien-Quorum-Sensing (V. fischeri AHL-AI-2-System).
Auto-Inducer akkumuliert mit Population-Density. Bei Schwellen-Konzentration:
synchronisierte Genexpression aller Zellen. Hill-Funktion-Aktivierung mit
Cooperativity-Parameter n.

Anorg-Mapping (Welle-9.1b): A-21 Pheromone-Trails (Konzentrations-Threshold + Verstaerkung).

Mathematisch:
    activation(s, n, K_d) = s^n / (K_d^n + s^n)   # Hill-Funktion
    decay(s, lambda, dt) = s * exp(-lambda * dt)   # exponentieller Decay

K11 Cascade-Containment: Quorum pro tissue_id isoliert (kein Cross-Tissue-Spillover).
K13 Pre-Action-Verification: Cross-DF-Threshold (min N_unique DFs) verhindert Single-DF-Trigger.

Usage:
    engine = QuorumEngine(K_d=2.0, hill_n=2.7, decay_lambda=0.05)
    engine.emit_signal(tissue_id="pricing-eu", signal_type="demand_high", df_id="df-86", strength=1.0)
    engine.emit_signal(tissue_id="pricing-eu", signal_type="demand_high", df_id="df-87", strength=0.8)
    if engine.is_quorum_active(tissue_id="pricing-eu", signal_type="demand_high"):
        # Synchronisierte Cross-DF-Aktion
        ...
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional


# Constants with units.
DEFAULT_K_D: float = 1.0                  # half-saturation concentration
DEFAULT_HILL_N: float = 2.7                # Hill-coefficient (Hemoglobin-Default)
DEFAULT_DECAY_LAMBDA: float = 0.05         # 1/sec
DEFAULT_ACTIVATION_THRESHOLD: float = 0.5  # Hill-Y >= 0.5 -> active
DEFAULT_MIN_UNIQUE_DFS: int = 3            # min independent contributors


@dataclass(frozen=True)
class SignalContribution:
    """Single contribution to an auto-inducer pool. Immutable record."""

    tissue_id: str
    signal_type: str
    df_id: str
    strength: float
    timestamp: float


@dataclass
class AutoInducerPool:
    """Mutable pool per (tissue_id, signal_type). Tracks accumulated concentration."""

    tissue_id: str
    signal_type: str
    concentration: float = 0.0
    contributions: list[SignalContribution] = field(default_factory=list)
    last_updated: float = 0.0

    def unique_df_count(
        self,
        now: Optional[float] = None,
        ttl_window_sec: Optional[float] = None,
    ) -> int:
        """Count unique DF contributors. With TTL-window, only count recent ones.

        Welle-9β.5 Patch C1 (Copilot-Finding): historical-counting causes optimism-bias
        on long-running tissues. Pass ttl_window_sec to restrict to recent contributors.
        """
        if ttl_window_sec is None or now is None:
            return len({c.df_id for c in self.contributions})
        cutoff = now - ttl_window_sec
        return len({c.df_id for c in self.contributions if c.timestamp >= cutoff})


class QuorumEngine:
    """Hill-Funktion Threshold-Aggregator with multi-DF independence requirement.

    Pre-Conditions:
        - K_d > 0, hill_n > 0
        - decay_lambda >= 0
        - clock injectable for tests
    Post-Conditions:
        - emit_signal is atomic; concentration accumulates with decay
        - is_quorum_active requires (Hill-Y >= activation_threshold) AND (unique_df_count >= min_unique_dfs)
        - GDPR: purge_tissue cascade-deletes a whole tissue's data
    """

    def __init__(
        self,
        K_d: float = DEFAULT_K_D,
        hill_n: float = DEFAULT_HILL_N,
        decay_lambda: float = DEFAULT_DECAY_LAMBDA,
        activation_threshold: float = DEFAULT_ACTIVATION_THRESHOLD,
        min_unique_dfs: int = DEFAULT_MIN_UNIQUE_DFS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if K_d <= 0:
            raise ValueError("K_d must be > 0")
        if hill_n <= 0:
            raise ValueError("hill_n must be > 0")
        if decay_lambda < 0:
            raise ValueError("decay_lambda must be >= 0")
        if not (0 <= activation_threshold <= 1):
            raise ValueError("activation_threshold must be in [0,1]")
        if min_unique_dfs < 1:
            raise ValueError("min_unique_dfs must be >= 1")
        self.K_d = float(K_d)
        self.hill_n = float(hill_n)
        self.decay_lambda = float(decay_lambda)
        self.activation_threshold = float(activation_threshold)
        self.min_unique_dfs = int(min_unique_dfs)
        # Patch C1 (Copilot): TTL-window for unique_df_count. Default = 5 e-folding-times
        # (so DFs that contributed > ~5/lambda sec ago no longer count toward independence).
        self.unique_df_ttl_sec = (
            5.0 / decay_lambda if decay_lambda > 0 else float("inf")
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._pools: dict[tuple[str, str], AutoInducerPool] = {}

    # ---------------- Public API ----------------

    def emit_signal(
        self,
        tissue_id: str,
        signal_type: str,
        df_id: str,
        strength: float = 1.0,
    ) -> AutoInducerPool:
        """Add a signal-contribution from df_id to the pool. Returns updated pool."""
        if not tissue_id or not signal_type or not df_id:
            raise ValueError("tissue_id, signal_type, df_id required")
        if strength < 0:
            raise ValueError("strength must be >= 0")
        now = self._clock()
        with self._lock:
            key = (tissue_id, signal_type)
            pool = self._pools.get(key)
            if pool is None:
                pool = AutoInducerPool(
                    tissue_id=tissue_id,
                    signal_type=signal_type,
                    last_updated=now,
                )
                self._pools[key] = pool
            else:
                pool.concentration = self._decayed(pool, now)
                pool.last_updated = now
            pool.concentration += float(strength)
            pool.contributions.append(
                SignalContribution(
                    tissue_id=tissue_id,
                    signal_type=signal_type,
                    df_id=df_id,
                    strength=float(strength),
                    timestamp=now,
                )
            )
            return pool

    def hill_activation(self, tissue_id: str, signal_type: str) -> float:
        """Hill-Y = s^n / (K_d^n + s^n) ∈ [0, 1)."""
        with self._lock:
            pool = self._pools.get((tissue_id, signal_type))
            if pool is None:
                return 0.0
            now = self._clock()
            s = self._decayed(pool, now)
            if s <= 0:
                return 0.0
            sn = s ** self.hill_n
            return sn / (self.K_d ** self.hill_n + sn)

    def is_quorum_active(self, tissue_id: str, signal_type: str) -> bool:
        """Quorum requires BOTH Hill >= threshold AND unique_dfs >= min.

        Patch C1: unique_dfs counted within ttl_window (recent contributors only),
        not historically — addresses Copilot-Finding optimism-bias.
        """
        with self._lock:
            pool = self._pools.get((tissue_id, signal_type))
            if pool is None:
                return False
            now = self._clock()
            y = self.hill_activation(tissue_id, signal_type)
            n_unique_recent = pool.unique_df_count(
                now=now, ttl_window_sec=self.unique_df_ttl_sec
            )
            return y >= self.activation_threshold and n_unique_recent >= self.min_unique_dfs

    def current_concentration(self, tissue_id: str, signal_type: str) -> float:
        """Decayed-current concentration."""
        with self._lock:
            pool = self._pools.get((tissue_id, signal_type))
            if pool is None:
                return 0.0
            return self._decayed(pool, self._clock())

    def list_pools_for_tissue(self, tissue_id: str) -> list[AutoInducerPool]:
        with self._lock:
            return [p for k, p in self._pools.items() if k[0] == tissue_id]

    def purge_tissue(self, tissue_id: str) -> int:
        """Cascade-delete all pools for a tissue (GDPR-style, isolation)."""
        with self._lock:
            keys = [k for k in self._pools if k[0] == tissue_id]
            for k in keys:
                del self._pools[k]
            return len(keys)

    # ---------------- Internals ----------------

    def _decayed(self, pool: AutoInducerPool, now: float) -> float:
        """Apply exponential decay since last_updated, returns current concentration."""
        if self.decay_lambda == 0:
            return pool.concentration
        dt = max(0.0, now - pool.last_updated)
        if dt == 0:
            return pool.concentration
        decayed = pool.concentration * math.exp(-self.decay_lambda * dt)
        # Persist decay so subsequent reads are consistent
        pool.concentration = decayed
        pool.last_updated = now
        return decayed


def quorum_required(
    engine: QuorumEngine,
    tissue_id: str,
    signal_type: str,
) -> Callable:
    """Decorator factory: blocks func unless quorum active."""

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            if not engine.is_quorum_active(tissue_id, signal_type):
                raise PermissionError(
                    f"Quorum not active for tissue={tissue_id!r} signal={signal_type!r}"
                )
            return func(*args, **kwargs)

        wrapper.__name__ = getattr(func, "__name__", "quorum_wrapper")
        wrapper.__doc__ = getattr(func, "__doc__", None)
        return wrapper

    return decorator


# CRUX-MK
