# [CRUX-MK]
"""Cape-Familien-Dedup (Welle-46 Phase-39, 28. Multi-Domain-Lift).

Bio-Aequivalent: B-Cell-Memory-Match auf Familien-Decision-Repetition-Avoidance.
Pattern-Quelle: kpm_deduplication_engine (Welle-26) + deduplication_engine (Welle-9).

Domain: Familien-Decision-Stream. Verhindert dass identische Decision-Anfragen
in kurzer Zeit doppelt verarbeitet werden (Familien-Effizienz, Mental-Load-Schutz).

Public API:
    from kmo_governance.cape_familien_dedup import (
        FamilienDecisionDedupResult,
        CapeFamilienDedup,
    )

CRUX-MK
"""
from .cape_familien_dedup import (
    CapeFamilienDedup,
    FamilienDecisionDedupResult,
)

__all__ = [
    "CapeFamilienDedup",
    "FamilienDecisionDedupResult",
]

# CRUX-MK
