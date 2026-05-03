"""KMO knowledge_decay Engine [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.4: Synaptic-Plasticity Analog (LTP/LTD) +
FSRS-Spaced-Repetition + Use-it-or-lose-it Auto-Pruning.

Bio-Aequivalent: Long-Term-Potentiation (LTP, use boostet Stability) und Long-Term-
Depression (LTD, non-use erodiert Stability). Synapsen die nicht aktiv sind, schwaechen
sich; aktive werden gestaerkt (Hebbian-Plasticity).

Anorg-Mapping: A-23 Forgetting-Curve / Spaced-Repetition (Ebbinghaus / SuperMemo).

Math (FSRS-Kern):
  R(t) = exp(-t / S)                      Retrievability (recall-probability)
  S' = S * (1 + factor)                   on USE: stability boost (LTP)
  S' = S * (1 - decay_rate)               on NON-USE: stability decay (LTD)
  pruning: Konfidenz < threshold UND Alter > min_age → REMOVE

Komponenten:
  - KnowledgeEntry: dataclass mit confidence + stability + last_use
  - KnowledgeDecayEngine: register/use/decay/prune Operationen
  - reconsolidation_engine: Use-Event boostet Confidence
  - forgetting_curve_optimizer: FSRS-tuned Spaced-Repetition Schedule
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------- Constants ----------

DEFAULT_INITIAL_STABILITY: float = 1.0       # days
DEFAULT_INITIAL_CONFIDENCE: float = 0.5      # neutral start
DEFAULT_LTP_BOOST_FACTOR: float = 0.3        # +30% on use
DEFAULT_LTD_DECAY_RATE_PER_DAY: float = 0.05  # -5%/day on non-use
DEFAULT_PRUNING_CONFIDENCE: float = 0.1
DEFAULT_PRUNING_MIN_AGE_DAYS: float = 7.0
SECONDS_PER_DAY: float = 86_400.0

# Patch F1 (Welle-9-delta-Cross-LLM 3/3-Finding "Stability-Floor"):
# Minimum stability to prevent division-by-zero in retrievability/optimal_next_review
# and excessive aggressive forgetting. S_floor = 0.001 days (~86s), guarantees
# math.exp(-t/S) stays computable and pruning still possible.
STABILITY_FLOOR: float = 0.001


# ---------- KnowledgeEntry ----------

@dataclass
class KnowledgeEntry:
    """One knowledge unit (methodik / fact / pattern).

    Pre: confidence in [0,1]; stability > 0; last_use <= now
    Post: mutable; updated by use() / decay() in KnowledgeDecayEngine
    """

    key: str                           # unique id (e.g. "method-pareto-cut")
    confidence: float                  # [0,1] subjective certainty
    stability: float                   # FSRS-S: days until forget
    last_use: float                    # unix timestamp of last reactivation
    created_at: float
    use_count: int = 0
    metadata: dict = field(default_factory=dict)

    def retrievability(self, now: float) -> float:
        """R(t) = exp(-Delta_t_days / S). Probability the entry is recallable."""
        delta_days = max(0.0, (now - self.last_use) / SECONDS_PER_DAY)
        if self.stability <= 0:
            return 0.0
        return math.exp(-delta_days / self.stability)


# ---------- KnowledgeDecayEngine ----------

class KnowledgeDecayEngine:
    """FSRS-tuned Spaced-Repetition + Synaptic-Plasticity model.

    Pre: pruning_confidence in [0,1]; pruning_min_age_days > 0
    Post:
      - register() adds entries (idempotent on re-register: returns existing)
      - use() applies LTP-boost
      - decay() applies time-based LTD-decay
      - prune() removes low-confidence + old entries
      - get_due_for_review() returns entries with low retrievability
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        ltp_boost_factor: float = DEFAULT_LTP_BOOST_FACTOR,
        ltd_decay_rate_per_day: float = DEFAULT_LTD_DECAY_RATE_PER_DAY,
        pruning_confidence: float = DEFAULT_PRUNING_CONFIDENCE,
        pruning_min_age_days: float = DEFAULT_PRUNING_MIN_AGE_DAYS,
    ) -> None:
        if not (0 < ltp_boost_factor):
            raise ValueError("ltp_boost_factor must be > 0")
        if not (0 < ltd_decay_rate_per_day < 1):
            raise ValueError("ltd_decay_rate_per_day must be in (0, 1)")
        if not (0 <= pruning_confidence <= 1):
            raise ValueError("pruning_confidence must be in [0,1]")
        if pruning_min_age_days <= 0:
            raise ValueError("pruning_min_age_days must be > 0")
        self._clock = clock
        self.ltp_boost_factor = float(ltp_boost_factor)
        self.ltd_decay_rate_per_day = float(ltd_decay_rate_per_day)
        self.pruning_confidence = float(pruning_confidence)
        self.pruning_min_age_days = float(pruning_min_age_days)
        self._entries: dict[str, KnowledgeEntry] = {}
        self._lock = threading.RLock()

    # ---------- Register / get ----------

    def register(
        self,
        key: str,
        initial_confidence: float = DEFAULT_INITIAL_CONFIDENCE,
        initial_stability: float = DEFAULT_INITIAL_STABILITY,
        metadata: Optional[dict] = None,
    ) -> KnowledgeEntry:
        """Register a new knowledge entry. Returns existing if key already known.

        Pre: 0 <= initial_confidence <= 1; initial_stability > 0
        """
        if not (0 <= initial_confidence <= 1):
            raise ValueError("initial_confidence must be in [0,1]")
        if initial_stability <= 0:
            raise ValueError("initial_stability must be > 0")
        # Patch F1: enforce floor on registration too
        initial_stability = max(STABILITY_FLOOR, float(initial_stability))
        with self._lock:
            if key in self._entries:
                return self._entries[key]
            now = self._clock()
            e = KnowledgeEntry(
                key=key,
                confidence=float(initial_confidence),
                stability=float(initial_stability),
                last_use=now,
                created_at=now,
                metadata=dict(metadata or {}),
            )
            self._entries[key] = e
            return e

    def get(self, key: str) -> Optional[KnowledgeEntry]:
        with self._lock:
            return self._entries.get(key)

    def all_entries(self) -> list[KnowledgeEntry]:
        with self._lock:
            return list(self._entries.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ---------- LTP / LTD ----------

    def use(self, key: str, performance: float = 1.0) -> Optional[KnowledgeEntry]:
        """Reconsolidation-Event: LTP-boost on use.

        Pre: performance in [0,1] (1.0 = perfect recall, 0.0 = forgot)
        Post:
          - Confidence increases proportional to performance + ltp_boost_factor
          - Stability multiplies by (1 + ltp_boost_factor * performance)
          - last_use updated to now
          - use_count incremented
        Returns None if key unknown.
        """
        if not (0 <= performance <= 1):
            raise ValueError("performance must be in [0,1]")
        with self._lock:
            e = self._entries.get(key)
            if e is None:
                return None
            now = self._clock()
            boost = self.ltp_boost_factor * performance
            # Confidence approaches 1 asymptotically
            e.confidence = min(1.0, e.confidence + (1.0 - e.confidence) * boost)
            # Stability multiplicative grow
            e.stability = e.stability * (1.0 + boost)
            e.last_use = now
            e.use_count += 1
            return e

    def decay(self) -> int:
        """LTD-decay: reduce stability for non-recently-used entries.

        Returns number of entries that received decay (i.e. > 0 days since last_use).
        """
        with self._lock:
            now = self._clock()
            decayed = 0
            for e in self._entries.values():
                delta_days = (now - e.last_use) / SECONDS_PER_DAY
                if delta_days <= 0:
                    continue
                # Daily decay applied over delta_days
                # Confidence decays slower than stability (pattern persistence)
                conf_decay = (self.ltd_decay_rate_per_day * 0.5) * delta_days
                stab_decay = self.ltd_decay_rate_per_day * delta_days
                e.confidence = max(0.0, e.confidence - conf_decay)
                # Patch F1: STABILITY_FLOOR prevents drop to zero
                e.stability = max(
                    STABILITY_FLOOR, e.stability * max(0.0, 1.0 - stab_decay)
                )
                decayed += 1
            return decayed

    # ---------- Pruning ----------

    def prune(self) -> list[str]:
        """Use-it-or-lose-it: remove entries with low confidence AND old age.

        Returns list of pruned keys. Auto-decay is NOT triggered first; call decay()
        beforehand for full forgetting-curve enforcement.
        """
        with self._lock:
            now = self._clock()
            to_remove: list[str] = []
            for key, e in self._entries.items():
                age_days = (now - e.created_at) / SECONDS_PER_DAY
                if (
                    e.confidence < self.pruning_confidence
                    and age_days > self.pruning_min_age_days
                ):
                    to_remove.append(key)
            for key in to_remove:
                del self._entries[key]
            return to_remove

    # ---------- Forgetting-Curve Optimizer (FSRS-style) ----------

    def get_due_for_review(self, retrievability_threshold: float = 0.7) -> list[KnowledgeEntry]:
        """Return entries whose R(t) has fallen below threshold (review-needed).

        Pre: 0 < threshold < 1
        Post: list ordered by lowest retrievability first (most-urgent)
        """
        if not (0 < retrievability_threshold < 1):
            raise ValueError("threshold must be in (0,1)")
        with self._lock:
            now = self._clock()
            due = [
                (e.retrievability(now), e)
                for e in self._entries.values()
                if e.retrievability(now) < retrievability_threshold
            ]
            due.sort(key=lambda pair: pair[0])
            return [e for _, e in due]

    def optimal_next_review(self, key: str) -> Optional[float]:
        """FSRS: timestamp of next-review = last_use + S * ln(1/R_target).

        For R_target=0.9 (recommended FSRS): t_review = last_use + S * 0.105 days.
        Returns unix-timestamp or None if key unknown.
        """
        with self._lock:
            e = self._entries.get(key)
            if e is None:
                return None
            R_target = 0.9
            review_offset_days = e.stability * math.log(1.0 / R_target)
            return e.last_use + review_offset_days * SECONDS_PER_DAY


# CRUX-MK
