# [CRUX-MK]
"""SAE-v8 Backpressure-Slot-Admission (Welle-34 Phase-27 Bio-Pattern-Lift Lift 16).

Bio-Aequivalent: Baroreflex-on-Slot-Admission.
  Karotis-Sinus-Drucksensoren auf Slot-Admission-Velocity. Bei zu hohem Pool-Fuellstand
  oder zu vielen Admissions pro Minute --> "vagale Hemmung" = Drosselung der
  Slot-Admission. Per-AgentClass + per-Trinity-Variant + Global FlowState.
  Verhindert Trinity-Variant-Imbalance und Slot-Pool-Saturation.

Pattern-Quelle: kmo_governance.backpressure_engine (Welle-9, Hotel-Domain, ~801 LoC).

SAE-v8-Domain-Note:
- SAE-v8 hat 200 Slots x 3 Trinity-Varianten (Conservative/Aggressive/Contrarian) = 600 Agenten.
- Baroreflex-Pattern angewendet auf Slot-Admission-Throttling.
- 3-Achsen-State: per-AgentClass + per-Trinity-Variant + Global FlowState.
- Throttle-Aktionen: ALLOW (NORMAL/ELEVATED) -> DELAY (THROTTLED) -> REJECT (BLOCKED).
- Rolling-Window-Sampling (Default 60 samples) + threshold-basiertes Tier-Wechseln.
- Verhindert Slot-Admission-Bursts und Trinity-Variant-Pool-Imbalance (CRUX K_0+Q_0-Schutz).

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, dritte SAE-v8-Domain-Anwendung
(Hotel-Capacity-Throttling -> Trading-Order-Flow-Throttling -> SAE-v8-Slot-Admission-Throttling).
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Public API:
    from kmo_governance.sae_v8_backpressure_slot_admission import (
        SAEv8BackpressureSlotAdmission,
        SlotFlowState,
        SlotAdmissionSample,
        AdmissionThrottleAction,
        SAESlotBackpressureDecision,
    )
"""

from .sae_v8_backpressure_slot_admission import (
    AdmissionThrottleAction,
    SAESlotBackpressureDecision,
    SAEv8BackpressureSlotAdmission,
    SlotAdmissionSample,
    SlotFlowState,
)

__all__ = [
    "AdmissionThrottleAction",
    "SAESlotBackpressureDecision",
    "SAEv8BackpressureSlotAdmission",
    "SlotAdmissionSample",
    "SlotFlowState",
]

# CRUX-MK
