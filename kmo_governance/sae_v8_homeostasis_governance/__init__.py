# [CRUX-MK]
"""SAE-v8-Homeostasis-Governance (Welle-34 Phase-27 Bio-Pattern-Lift).

Bio-Aequivalent: Thermoregulation (Hypothalamus-basiert) auf SAE-Governance-
Tier-Setpoint statt auf System-Gesundheits-Metriken oder Portfolio-Allocation.
Pattern-Quelle: kmo_governance.homeostasis_controller (Welle-25 Phase-18,
Hotel/System-Domain, Setpoint + Schwellen + Rolling-Average-Smoothing).

SAE-v8-Domain-Note:
- SAE-v8 hat governance-tier q_norm in [-2, +2] pro Slot (q-Normalisierung)
- Setpoint = ideale q-Norm-Distribution (0.0 = balanciert)
- Deviation triggert Slot-Promotion (zu niedrig -> PROMOTING_SLOT,
  Challenger-Variante hochstufen) oder Slot-Relegation (zu hoch ->
  RELEGATING_SLOT, Variante mit hohem q_norm relegated)
- Rolling-Average ueber history_window glaettet q_norm-Spikes
  (kein Whipsaw-Promotion/Relegation bei kurzen q-Sprungspitzen)
- Critical-Threshold 30% Default (groesser als Hotel/System 25% und KPM 15%)
  weil Governance-Tier-Volatilitaet hoeher (q_norm reagiert auf Reward-Stream)
- F_CUM_DECAY = 0.98 ist Komplement (Slot-Fitness-Verfall, NICHT q_norm-Drift)
- Real-SAE-v8-Production-Code wird NICHT veraendert (nur Pattern-Lift-Demo)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern (Setpoint-Feedback +
Threshold-State-Machine + Rolling-Average + Custom-Action-Hooks),
andere Domaene (SAE-v8-Governance-Tier-Drift statt System-Health-Metriken
oder Portfolio-Allocation-Drift).

Siehe BIO-PATTERN-LIFT-DEMO.md fuer 3-Domain-Vergleichs-Tabelle (Hotel/KPM/SAE).

Pattern-Inspiration:
- homeostasis_controller (System-Domain): Setpoint + Cooling/Heating + PID-Smoothing
- kpm_homeostasis_controller (Trading-Domain): Setpoint + REDUCE/INCREASE + HALT
- Thermoregulation (Hypothalamus): Setpoint 37C + Sweat/Shiver-Response
- SAE-v8 coding.md §10: F_CUM_DECAY=0.98 (Slot-Fitness-Verfall, separate Mechanik)
- SAE-v8 §4 Invariante 1: q_norm in [-2, +2] (q-Scale-Normalisierung)

NO external Dependencies (stdlib-only): threading, time, dataclasses,
enum, collections.deque, typing.

Public API:
    from kmo_governance.sae_v8_homeostasis_governance import (
        GovernanceSample,
        GovernanceState,
        SAEv8HomeostasisGovernance,
        SAEGovernanceDecision,
        SlotAdjustmentAction,
    )

Usage:
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
        history_window=50,
    )
    gov.record_governance("slot-042", q_norm=0.3)
    gov.record_governance("slot-042", q_norm=0.5)
    decision = gov.evaluate(slot_id="slot-042")
    if decision.action and decision.action.action_type == "RELEGATE":
        # SAE-Trinity-Hook: Slot-Variante relegated, Challenger holen
        ...
"""
from .sae_v8_homeostasis_governance import (
    GovernanceSample,
    GovernanceState,
    SAEGovernanceDecision,
    SAEv8HomeostasisGovernance,
    SlotAdjustmentAction,
)

__all__ = [
    "GovernanceSample",
    "GovernanceState",
    "SAEGovernanceDecision",
    "SAEv8HomeostasisGovernance",
    "SlotAdjustmentAction",
]

# CRUX-MK
