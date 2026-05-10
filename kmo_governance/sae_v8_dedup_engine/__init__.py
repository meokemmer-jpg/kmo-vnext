# [CRUX-MK]
"""SAE-v8 Dedup-Engine for Slot-Submissions (Welle-42 Phase-35, 24. Multi-Domain-Lift).

Bio-Aequivalent: B-Cell-Memory-Match auf SAE-v8 Slot-Vote-Submission.
Pattern-Quelle: kpm_deduplication_engine (Welle-26 Trading) + deduplication_engine (Welle-9 Hotel).

DEMO-only Adapter (per L34 + Codex V16 REJECTED): Pattern-Demo, KEIN Real-Cross-Repo-Wiring.
Real-Wiring per branch-hub Plan Welle-50+ via SAE-v8-WIRING-PLAN.md.

Domain: SAE-v8 Slot-Voting-Submission. Dedup-Key: (slot_id, agent_class, vote_hash).
TTL: 5s (Trinity-Voting-Window kurz, schneller Throughput-Cycle).

Public API:
    from kmo_governance.sae_v8_dedup_engine import (
        SlotVoteDedupResult,
        SAEv8DedupEngine,
    )

CRUX-MK
"""
from .sae_v8_dedup_engine import (
    SAEv8DedupEngine,
    SlotVoteDedupResult,
)

__all__ = [
    "SAEv8DedupEngine",
    "SlotVoteDedupResult",
]

# CRUX-MK
