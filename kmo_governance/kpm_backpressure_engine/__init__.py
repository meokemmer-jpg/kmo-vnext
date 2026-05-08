# [CRUX-MK]
"""KPM-Backpressure-Engine (Welle-27 Phase-20 Bio-Pattern-Lift).

Bio-Aequivalent: Baroreflex-on-Order-Flow.
  Karotis-Sinus-Drucksensoren auf Order-Flow-Velocity. Bei zu hohem Flow -->
  "vagale Hemmung" = Drosselung der Order-Submission. Pre-Trade-Risk-Limits,
  dynamische Throttling.

Pattern-Quelle: kmo_governance.backpressure_engine (Welle-9, Hotel-Domain, ~801 LoC).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System.
- Baroreflex-Pattern angewendet auf Order-Flow-Throttling.
- 2-Achsen-State: per-Strategy + Global FlowState (LONG/SHORT-uebergreifend).
- Throttle-Aktionen: ALLOW (NORMAL/ELEVATED) -> DELAY (THROTTLED) -> REJECT (BLOCKED).
- Rolling-Window-Sampling (Default 60 samples) + threshold-basiertes Tier-Wechseln.
- Verhindert Strategy-Burst-Floods bei Markt-Volatilitaet (CRUX K_0-Schutz).

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, andere Domaene
(Hotel-Capacity-Throttling -> Trading-Order-Flow-Throttling).
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Public API:
    from kmo_governance.kpm_backpressure_engine import (
        KPMBackpressureEngine,
        FlowState,
        OrderFlowSample,
        ThrottleAction,
        BackpressureDecision,
    )
"""

from .kpm_backpressure_engine import (
    BackpressureDecision,
    FlowState,
    KPMBackpressureEngine,
    OrderFlowSample,
    ThrottleAction,
)

__all__ = [
    "BackpressureDecision",
    "FlowState",
    "KPMBackpressureEngine",
    "OrderFlowSample",
    "ThrottleAction",
]

# CRUX-MK
