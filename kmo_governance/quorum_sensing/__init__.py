"""KMO Quorum-Sensing Module [CRUX-MK].

Welle-9β Phase-2 Modul 2.1: Tissue-Layer Hill-Funktion-Threshold-Aggregator.
"""

from .quorum_engine import (
    AutoInducerPool,
    QuorumEngine,
    SignalContribution,
    quorum_required,
)

__all__ = [
    "AutoInducerPool",
    "QuorumEngine",
    "SignalContribution",
    "quorum_required",
]

# CRUX-MK
