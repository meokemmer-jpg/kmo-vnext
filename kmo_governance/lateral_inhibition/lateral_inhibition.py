"""KMO Lateral Inhibition [CRUX-MK].

Welle-9β Phase-2 Modul 2.3: Notch-Delta-Signaling-Analog. Nachbar-DFs
unterdruecken gleiche Action-Wahl. Verhindert correlated failures + Cluster-Decisions.

Bio-Aequivalent: Notch-Delta-Signaling in Drosophila-Neurogenesis.
Anorg-Mapping (Welle-9.1b): Anti-Herding-Pattern.

Math:
    inhibition(neighbor_signal, n, K_i) = neighbor_signal^n / (K_i^n + neighbor_signal^n)
    P(action_i) = base_prob * (1 - inhibition_from_neighbors)
    Z-score for correlated failures: Z = (n_failed - mean) / sigma
"""

from __future__ import annotations

import functools
import math
import random
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Optional


DEFAULT_K_I: float = 1.0
DEFAULT_HILL_N: float = 2.5
DEFAULT_BASE_PROB: float = 1.0
DEFAULT_FAILURE_WINDOW_SEC: float = 60.0
DEFAULT_Z_THRESHOLD: float = 3.0


class LateralInhibitor:
    """Topology-aware decision-rate-limiter with anti-correlation defense.

    Pre-Conditions:
        - topology: dict[df_id, list[neighbor_df_id]]  (sets of neighbors per df)
        - K_i, hill_n > 0
        - clock injectable
    Post-Conditions:
        - signal_intent atomic
        - inhibition_strength reflects neighbors' recent intents
        - random pseudorandom delay introduces fairness when ties
    """

    def __init__(
        self,
        topology: dict[str, list[str]],
        K_i: float = DEFAULT_K_I,
        hill_n: float = DEFAULT_HILL_N,
        base_prob: float = DEFAULT_BASE_PROB,
        clock: Callable[[], float] = time.time,
        rng: Optional[random.Random] = None,
    ) -> None:
        if K_i <= 0 or hill_n <= 0:
            raise ValueError("K_i and hill_n must be > 0")
        if not (0 <= base_prob <= 1):
            raise ValueError("base_prob must be in [0,1]")
        self.topology = topology
        self.K_i = float(K_i)
        self.hill_n = float(hill_n)
        self.base_prob = float(base_prob)
        self._clock = clock
        self._rng = rng or random.Random(42)
        self._lock = threading.RLock()
        # action_intents: dict[(df_id, action_kind), last_intent_timestamp]
        self._intents: dict[tuple[str, str], float] = {}

    def signal_intent(self, df_id: str, action_kind: str) -> None:
        """Record df's intent to perform action_kind. Used by neighbors for inhibition."""
        if not df_id or not action_kind:
            raise ValueError("df_id and action_kind required")
        if df_id not in self.topology:
            raise KeyError(f"df_id {df_id!r} not in topology")
        with self._lock:
            self._intents[(df_id, action_kind)] = self._clock()

    def inhibition_strength(self, df_id: str, action_kind: str) -> float:
        """Hill-strength of neighbor inhibition for (df_id, action_kind)."""
        with self._lock:
            now = self._clock()
            neighbors = self.topology.get(df_id, [])
            # Count neighbors who signaled same action_kind within last 5s
            recent_signal_count = sum(
                1 for n in neighbors
                if (n, action_kind) in self._intents
                and now - self._intents[(n, action_kind)] < 5.0
            )
            if recent_signal_count == 0:
                return 0.0
            sn = recent_signal_count ** self.hill_n
            return sn / (self.K_i ** self.hill_n + sn)

    def admit_probability(self, df_id: str, action_kind: str) -> float:
        """P(action_i) = base_prob * (1 - inhibition_from_neighbors)."""
        return self.base_prob * (1.0 - self.inhibition_strength(df_id, action_kind))

    def admit(self, df_id: str, action_kind: str) -> bool:
        """Stochastic admission decision based on admit_probability + pseudorandom roll."""
        p = self.admit_probability(df_id, action_kind)
        return self._rng.random() < p

    def pseudorandom_delay_sec(self, df_id: str, action_kind: str, max_delay_sec: float = 0.5) -> float:
        """Notch-Delta-style random delay to break ties when both neighbors want same action.

        Uses df_id + action_kind as deterministic seed for reproducibility within a tick.
        """
        seed = hash((df_id, action_kind, int(self._clock()))) & 0xFFFFFFFF
        local_rng = random.Random(seed)
        return local_rng.uniform(0, max_delay_sec)

    def lateral_decorator(self, df_id: str, action_kind: str) -> Callable:
        """Decorator: only invoke wrapped function if admit() passes."""

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                if not self.admit(df_id, action_kind):
                    raise PermissionError(
                        f"Lateral inhibition blocks df={df_id!r} action={action_kind!r}"
                    )
                self.signal_intent(df_id, action_kind)
                return func(*args, **kwargs)
            return wrapper
        return decorator


class CorrelatedFailureDetector:
    """Z-score-based detector for tissue-wide failure clusters.

    Pre-Conditions:
        - window_sec > 0
        - z_threshold > 0
    Post-Conditions:
        - record_failure atomic
        - is_correlated_failure flags when Z > z_threshold (tissue-wide alarm)
    """

    def __init__(
        self,
        window_sec: float = DEFAULT_FAILURE_WINDOW_SEC,
        z_threshold: float = DEFAULT_Z_THRESHOLD,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if window_sec <= 0:
            raise ValueError("window_sec must be > 0")
        if z_threshold <= 0:
            raise ValueError("z_threshold must be > 0")
        self.window_sec = float(window_sec)
        self.z_threshold = float(z_threshold)
        self._clock = clock
        self._lock = threading.RLock()
        # tissue_id -> deque[(timestamp, df_id)]
        self._failures: defaultdict = defaultdict(deque)
        # tissue_id -> rolling history of per-window failure counts (for stats)
        self._history: defaultdict = defaultdict(list)

    def record_failure(self, tissue_id: str, df_id: str) -> None:
        if not tissue_id or not df_id:
            raise ValueError("tissue_id and df_id required")
        now = self._clock()
        with self._lock:
            self._failures[tissue_id].append((now, df_id))
            self._gc(tissue_id, now)

    def failure_count_in_window(self, tissue_id: str) -> int:
        with self._lock:
            now = self._clock()
            self._gc(tissue_id, now)
            return len(self._failures[tissue_id])

    def is_correlated_failure(self, tissue_id: str, mean: float, sigma: float) -> bool:
        """Detect Z = (n_failed - mean) / sigma > z_threshold.

        mean+sigma are baseline-statistics passed in; in production these come
        from rolling history (use add_baseline_sample).
        """
        if sigma <= 0:
            return False
        n = self.failure_count_in_window(tissue_id)
        z = (n - mean) / sigma
        return z > self.z_threshold

    def add_baseline_sample(self, tissue_id: str, count: int) -> None:
        """Register a baseline-window-count for rolling baseline stats."""
        with self._lock:
            self._history[tissue_id].append(int(count))
            # Keep last 200 samples
            if len(self._history[tissue_id]) > 200:
                self._history[tissue_id] = self._history[tissue_id][-200:]

    def baseline_stats(self, tissue_id: str) -> tuple[float, float]:
        """Return (mean, sigma) of rolling baseline. Returns (0,0) if insufficient."""
        with self._lock:
            samples = self._history[tissue_id]
            if len(samples) < 2:
                return 0.0, 0.0
            return statistics.mean(samples), statistics.stdev(samples)

    def _gc(self, tissue_id: str, now: float) -> None:
        cutoff = now - self.window_sec
        dq = self._failures[tissue_id]
        while dq and dq[0][0] < cutoff:
            dq.popleft()


# CRUX-MK
