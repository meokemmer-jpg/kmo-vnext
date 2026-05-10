# [CRUX-MK]
"""9dots-Distributed-Project-Lock (Welle-38 Phase-31 W38-T3, 21. Multi-Domain-Lift).

Bio-Aequivalent: Synaptic-Coordination auf 9dots-Multi-Project-Editing.
Pattern-Quelle: distributed_lock_manager (Welle-21 Hotel) + graphity_distributed_lock (Welle-30 Verlag).

Domain: 9dots-PMO Multi-Project-Coordination. Lock-Scope: (project_id, phase, owner_role).
TTL-Lease (default 1800s = 30 min Editor-Inactivity bei PMO-Workshops).

Pattern-Mapping:
- Hotel.lock_id           -> 9dots.(project_id, phase, owner_role)
- Hotel.holder_id         -> 9dots.holder_session_id (PMO-Session)
- Hotel.ttl_s 30.0        -> 9dots.ttl_s 1800.0 (PMO-Workshop-Length)
- Hotel.sweep_interval 5.0 -> 9dots.sweep_interval 60.0

Public API:
    from kmo_governance.ninedots_distributed_lock import (
        ProjectLockState,
        ProjectLockResult,
        NineDotsDistributedLock,
    )

CRUX-MK
"""
from .ninedots_distributed_lock import (
    NineDotsDistributedLock,
    ProjectLockResult,
    ProjectLockState,
)

__all__ = [
    "NineDotsDistributedLock",
    "ProjectLockResult",
    "ProjectLockState",
]

# CRUX-MK
