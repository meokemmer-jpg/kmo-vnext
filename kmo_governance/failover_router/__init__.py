# [CRUX-MK]
"""Failover-Router (Welle-19 Phase-13.1).

Bio-Aequivalent: Kollateral-Kreislauf (Active-Standby Failover bei Hauptarterien-Block).
Active-Standby-Routing mit Health-basierter Promotion.
"""
from .failover_router import (
    FailoverRouter,
    FailoverState,
    NodeStatus,
    RouteDecision,
)

__all__ = ["FailoverRouter", "FailoverState", "NodeStatus", "RouteDecision"]

# CRUX-MK
