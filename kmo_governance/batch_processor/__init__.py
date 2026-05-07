"""KMO Batch-Processor Module [CRUX-MK].

Welle-21 Phase-14 Modul-2/2: Bulk-Operations mit Progress-Tracking + Failure-Isolation.

Bio-Aequivalent: Peristaltische-Wellen (Verdauungs-Trakt).
    Bolus-Bildung    -> submit() (Items werden zu Batch zusammengefasst)
    Peristaltik      -> Chunked-Execution (koordinierte Wellen Item-fuer-Item)
    Pause-Reflex     -> pause() / resume() (Wellen koennen unterbrochen werden)
    Skip-Reflex      -> skip_on_error (beschaedigte Items werden uebersprungen)
    Fortschritts-    -> Progress-Marker an jeder Station
       Marker

Komplement zu saga_step_orchestrator (Mitose-Phasen-Sequencing):
    saga_step_orchestrator = ordered DAG-Steps mit Compensation
    batch_processor        = bulk Items, jeder Item unabhaengig, Failure-Isolation

Public API:
    from kmo_governance.batch_processor import (
        BatchProcessor, BatchProgress, BatchResult, ItemResult,
        BatchStatus, ItemStatus,
    )
"""

from .batch_processor import (
    BatchProcessor,
    BatchProgress,
    BatchResult,
    BatchStatus,
    ItemResult,
    ItemStatus,
)

__all__ = [
    "BatchProcessor",
    "BatchProgress",
    "BatchResult",
    "BatchStatus",
    "ItemResult",
    "ItemStatus",
]

# CRUX-MK
