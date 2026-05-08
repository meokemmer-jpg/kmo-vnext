# [CRUX-MK]
"""KPM-Deduplication-Engine (Welle-26 Phase-19 Round-2 KMO-vNext, Lift 5/5).

Trade-Order-Idempotency via client_order_id + payload-Hash + TTL-LRU.

Bio-Aequivalent: B-Cell-Memory (Antigen-Hash-Memory mit Halbwertszeit) auf
Trade-Idempotency. Body erinnert sich an bereits-gesehenen Trade-Order und
verhindert Doppel-Submission (Network-Retry, Strategy-Resend).

KPM-Domain-Note: client_order_id ist primary-key (broker-stable identifier
fuer Order-Idempotency). order_payload-Hash dient als secondary check fuer
Audit-Trail (MiFID-RTS-25 retention) — wenn dieselbe client_order_id mit
abweichendem payload erscheint, ist das ein Signal fuer Strategy-Bug oder
Order-Manipulation, NICHT fuer Re-Submission. True LRU eviction nach
last_access_at (post-W20-P2 baseline) schuetzt Hot-Orders (recent retries)
vor Eviction durch idle-Background-Orders.

Default-TTL 300s (5min) reflektiert Trading-Latenz: Network-Retry-Window +
Strategy-Resend-Cycle + Broker-Ack-Timeout. Hotel-Domain hatte 3600s (1h),
Trading braucht engeren TTL um Stale-Order-Re-Submission zu vermeiden.

CRUX-MK
"""
from .kpm_deduplication_engine import (
    KPMDeduplicationEngine,
    OrderRecord,
    TradeDedupResult,
)

__all__ = [
    "KPMDeduplicationEngine",
    "OrderRecord",
    "TradeDedupResult",
]

# CRUX-MK
