# [CRUX-MK]
"""Snapshot Consistency Engine (Welle-15 Phase-10.2).

Bio-Aequivalent: Mitose-Metaphase (synchrone Chromosom-Anordnung vor Trennung).
Multi-Module-Snapshot fuer cross-cutting state-capture mit consistency-Checks.
"""
from .snapshot_consistency import (
    ModuleSnapshot,
    SnapshotConsistencyEngine,
    SnapshotResult,
    SnapshotStatus,
)

__all__ = [
    "ModuleSnapshot",
    "SnapshotConsistencyEngine",
    "SnapshotResult",
    "SnapshotStatus",
]

# CRUX-MK
