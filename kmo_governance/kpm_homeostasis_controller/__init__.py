# [CRUX-MK]
"""KPM-Homeostasis-Controller (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Aequivalent: Thermoregulation (Hypothalamus-basiert) auf Portfolio-
Drift-Setpoint statt auf System-Gesundheits-Metriken.
Pattern-Quelle: kmo_governance.homeostasis_controller (Welle-25 Phase-18,
Hotel/System-Domain, Setpoint + Schwellen + Rolling-Average-Smoothing).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Setpoint = ideale Asset-Allocation (z.B. 60% Equities)
- Deviation triggert Cooling (REDUCE_POSITION) bei zu hoher Allocation
  oder Heating (INCREASE_POSITION) bei zu niedriger Allocation
- Rolling-Average ueber history_window glaettet Spikes (kein Whipsaw-Trading)
- Risk-Budget bleibt zentral (Variante-D Drawdown-Caps gelten weiter)
- Critical-Threshold 15% (kleiner als Hotel/System 25%) wegen Trading-Volatilitaet
- HALT-Action bei CRITICAL-State (Schutz vor Cliff-Effect)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern (Setpoint-Feedback +
Threshold-State-Machine + Rolling-Average + Custom-Action-Hooks),
andere Domaene (Portfolio-Allocation-Drift statt System-Health-Metriken).

Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Pattern-Inspiration:
- homeostasis_controller (System-Domain): Setpoint + Cooling/Heating + PID-Smoothing
- Thermoregulation (Hypothalamus): Setpoint 37C + Sweat/Shiver-Response
- KPM Variante-D: Drawdown-Caps + Kelly-Fraction-Adaption als Komplement

NO external Dependencies (stdlib-only): threading, time, dataclasses,
enum, collections.deque, typing.

Public API:
    from kmo_governance.kpm_homeostasis_controller import (
        AllocationSample,
        HomeostasisState,
        KPMHomeostasisController,
        KPMHomeostasisDecision,
        RebalanceAction,
    )

Usage:
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
        history_window=20,
    )
    ctrl.record_allocation("equities", 62.0)
    ctrl.record_allocation("equities", 64.0)
    decision = ctrl.evaluate()
    if decision.action and decision.action.action_type == "REDUCE":
        # Trade-Engine-Hook: Position um magnitude_pct reduzieren
        ...
"""
from .kpm_homeostasis_controller import (
    AllocationSample,
    HomeostasisState,
    KPMHomeostasisController,
    KPMHomeostasisDecision,
    RebalanceAction,
)

__all__ = [
    "AllocationSample",
    "HomeostasisState",
    "KPMHomeostasisController",
    "KPMHomeostasisDecision",
    "RebalanceAction",
]

# CRUX-MK
