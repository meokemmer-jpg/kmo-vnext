# [CRUX-MK]
"""LexVance-Distributed-Document-Lock (Welle-41 Phase-34, 23. Multi-Domain-Lift).

Bio-Aequivalent: Synaptic-Coordination auf LexVance-Legal-Document-Editing.
Pattern-Quelle: distributed_lock_manager (Welle-21 Hotel) + graphity_distributed_lock (Welle-30 Verlag)
                + ninedots_distributed_lock (Welle-38 PMO).

Domain: LexVance Multi-Mandant-Document-Coordination. Lock-Scope: (mandant_id, document_id, edit_phase).
Cross-Lawyer-Edit-Coordination mit conflict-of-interest Schutz (kein Konkurrenz-Mandanten Zugriff).

TTL-Lease (default 3600s = 1h Lawyer-Editing-Block, lange Editor-Sessions ueblich in Legal-Reviews).

Public API:
    from kmo_governance.lexvance_distributed_lock import (
        DocumentLockState,
        DocumentLockResult,
        LexVanceDistributedLock,
    )

CRUX-MK
"""
from .lexvance_distributed_lock import (
    DocumentLockResult,
    DocumentLockState,
    LexVanceDistributedLock,
)

__all__ = [
    "DocumentLockResult",
    "DocumentLockState",
    "LexVanceDistributedLock",
]

# CRUX-MK
