"""knowledge_decay package: Synaptic-Plasticity (LTP/LTD) + FSRS-Spaced-Repetition."""

from kmo_governance.knowledge_decay.knowledge_decay import (
    DEFAULT_INITIAL_CONFIDENCE,
    DEFAULT_INITIAL_STABILITY,
    DEFAULT_LTD_DECAY_RATE_PER_DAY,
    DEFAULT_LTP_BOOST_FACTOR,
    DEFAULT_PRUNING_CONFIDENCE,
    DEFAULT_PRUNING_MIN_AGE_DAYS,
    KnowledgeDecayEngine,
    KnowledgeEntry,
    SECONDS_PER_DAY,
    STABILITY_FLOOR,
)

__all__ = [
    "DEFAULT_INITIAL_CONFIDENCE",
    "DEFAULT_INITIAL_STABILITY",
    "DEFAULT_LTD_DECAY_RATE_PER_DAY",
    "DEFAULT_LTP_BOOST_FACTOR",
    "DEFAULT_PRUNING_CONFIDENCE",
    "DEFAULT_PRUNING_MIN_AGE_DAYS",
    "KnowledgeDecayEngine",
    "KnowledgeEntry",
    "SECONDS_PER_DAY",
    "STABILITY_FLOOR",
]
