"""KMO Distributed-Lock-Manager Module [CRUX-MK].

Welle-21 Phase-14 Modul: Cross-DF-Resource-Lock-Coordinator (TTL-Lease + Auto-Release).

Bio-Aequivalent: Synaptische-Verbindung.
    Pre-Synapse        -> Holder haelt Neurotransmitter-Reservoir (Lease)
    Post-Synapse       -> Rezipient mit Lease-Time (TTL-Window)
    Aktivitaets-Decay  -> Auto-Release wenn Synapse-Aktivitaet ablaeuft (Expiry)
    Kompetition        -> Multiple konkurrierende Synapsen kompetitieren um Resource

Komplement zu saga_step_orchestrator (DAG-basierte Multi-Step-Sequencing) und
df_bus_orchestrator (Cross-DF-Bus / Hormonsystem):
    distributed_lock_manager = exklusive Resource-Reservation mit
    TTL-Lease, Token-Validation und automatischer Sweep-Reaper-Mechanik.

CRUX-Bindung:
- K_0: token-validated release verhindert Lock-Hijacking durch andere Holder
- Q_0: Auto-Release expired Leases verhindert Deadlocks bei Holder-Crashes
- I_min: lease_token (uuid.uuid4) als kryptographischer Owner-Beleg
- W_0: Sweep-Reaper traegt amortisierten O(1)-Overhead (Cleanup-on-Acquire)

Public API:
    from kmo_governance.distributed_lock_manager import (
        DistributedLockManager, Lease, LockResult, LockState,
    )
"""

from .distributed_lock_manager import (
    DistributedLockManager,
    Lease,
    LockResult,
    LockState,
)

__all__ = [
    "DistributedLockManager",
    "Lease",
    "LockResult",
    "LockState",
]

# CRUX-MK
