# [CRUX-MK]
"""KPM-Demo-Application — End-to-End-Pipeline der 9 KPM-Module (Welle-31 Phase-24).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System.
- Diese Demo orchestriert ALLE 9 Bio-Pattern-Lift-Module zusammen als
  produktionsnahe Trade-Admission-Pipeline. Beweist: Bio-Pattern-Lifts
  funktionieren ORCHESTRIERT wie ein Trading-Stack, nicht nur isoliert.

Pipeline-Stages (in dieser Reihenfolge):
  1. feature_flag_engine    -> Strategy enabled?            (Genexpression)
  2. deduplication_engine   -> Idempotent client_order_id?  (B-Cell-Memory)
  3. backpressure_engine    -> Order-Flow im Cap?           (Baroreflex)
  4. distributed_lock_mgr   -> Instrument/Side reserviert?  (Synapse)
  5. trading_failover       -> Active-Strategy via Routing? (Kollateral-Kreislauf)
  6. saga_orchestrator      -> Multi-Leg-Atomicity OK?      (Mitose)
  7. homeostasis_controller -> Allocation-Tracking          (Thermoregulation)
  8. audit_event_bus        -> Final-Audit publiziert?      (Lymphatic)
  9. distributed_lock_mgr   -> Cleanup (Lock-Release)
  + optional chaos_engineering.inject_random  (Innate-Immune)

Bio-Aequivalent: Komplette Immun-/Kreislauf-/Stoffwechsel-Kaskade einer
                 lebenden Zelle bei Antigen-Exposition.

Klassen:
  - TradeAdmissionResult (frozen): success, decision_path, reason,
    audit_event_id, saga_id, elapsed_ms, timestamp
  - KPMTradeAdmissionPipeline: End-to-End-Orchestrator
"""
from .kpm_demo_application import (
    KPMTradeAdmissionPipeline,
    TradeAdmissionResult,
)

__all__ = [
    "KPMTradeAdmissionPipeline",
    "TradeAdmissionResult",
]

# CRUX-MK
