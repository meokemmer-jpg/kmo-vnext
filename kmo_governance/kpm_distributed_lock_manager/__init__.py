# [CRUX-MK]
"""KPM-Distributed-Trade-Lock-Manager (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Aequivalent: Synaptische-Verbindung (Pre/Post-Synapse + TTL-Decay + Kompetition).
Pattern-Quelle: kmo_governance.distributed_lock_manager (Welle-21 Phase-14, Hotel-Domain).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System.
- Synaptic-Pattern angewendet auf Strategy-Lock fuer concurrent trades.
- Lock-Schluessel = (instrument_id, position_side); kurze TTL (Default 5s).
- Verhindert Doppel-Orders durch konkurrierende Strategien auf gleichem Setup.
- LONG und SHORT auf gleichem Instrument sind unabhaengige Locks (separate Sides).

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, andere Domaene
(Hotel-Resource-Lock -> Trading-Position-Lock).
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Public API:
    from kmo_governance.kpm_distributed_lock_manager import (
        KPMDistributedTradeLockManager,
        TradeLease,
        TradeLockResult,
        TradeLockState,
        PositionSide,
    )
"""

from .kpm_distributed_lock_manager import (
    KPMDistributedTradeLockManager,
    PositionSide,
    TradeLease,
    TradeLockResult,
    TradeLockState,
)

__all__ = [
    "KPMDistributedTradeLockManager",
    "PositionSide",
    "TradeLease",
    "TradeLockResult",
    "TradeLockState",
]

# CRUX-MK
