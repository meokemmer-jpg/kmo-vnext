# [CRUX-MK]
"""KPM-Trading-Failover (Welle-23 Phase-16 Bio-Pattern-Lift).

Bio-Aequivalent: Kollateral-Kreislauf (Active-Standby Failover bei Hauptarterien-Block).
Pattern-Quelle: kmo_governance.failover_router (Welle-19 Phase-13.1, Hotel-Domain).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Active-Standby-Pattern angewendet auf Trading-Strategien (z.B. Kelly-Variante-Failover)
- primary_strategy = aggressivste Variante (z.B. Kelly 0.4)
- standby_strategy = konservativere Fallbacks (z.B. Kelly 0.3, Kelly 0.2)
- Failover-Trigger: 3 unprofitable Trades in Folge (entspricht NodeStatus.DOWN)
- Recovery: Promote zurueck zu primary nach 3 OK-Trades (manual via promote_to_primary)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, andere Domaene.
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.
"""
from .kpm_trading_failover import (
    FailoverState,
    KPMTradingFailover,
    StrategyStatus,
    TradingDecision,
)

__all__ = [
    "FailoverState",
    "KPMTradingFailover",
    "StrategyStatus",
    "TradingDecision",
]

# CRUX-MK
