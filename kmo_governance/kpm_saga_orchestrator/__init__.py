# [CRUX-MK]
"""KPM-Saga-Orchestrator (Welle-27 Phase-20 KMO-vNext, Bio-Pattern-Lift).

Multi-Leg-Order-Saga via 5-Phasen-Sequencing mit Compensation-on-Failure.

Bio-Aequivalent: Mitose-Phasen-Sequencing (Prophase/Metaphase/Anaphase/
Telophase/Cytokinesis) auf Multi-Leg-Trade-Atomicity. Wie eine Zelle 5 streng
geordnete Phasen durchlaeuft (jede mit Reversibilitaet bis zum Point-of-No-
Return), durchlaeuft eine Multi-Leg-Order 5 Saga-Phasen mit Compensation-Path
pro Phase: VALIDATE -> RESERVE -> EXECUTE -> CONFIRM -> SETTLE.

KPM-Domain-Note: Multi-Leg-Order-Atomicity ist im Trading kritisch (Pairs-
Trade, Spread-Order, Basket-Rebalance). Wenn Leg-2 fehlschlaegt nachdem
Leg-1 schon submitted ist, MUSS Leg-1 kompensiert werden (Reverse-Order
absetzen, Margin-Reserve freigeben). Saga-Pattern garantiert: entweder
alle Legs settlen, oder alle kompensieren — kein Partial-Commit der den
Portfolio-Risk verzerrt.

Pattern-Quelle: kmo_governance/saga_step_orchestrator (Welle-9, DAG-basiert).
Lift-Adjustment: Statt DAG-Topology hier 5-Phase-Linear-State-Machine pro
Saga (jede Saga = 1 Multi-Leg-Order mit N Steps, jeder Step durchlaeuft alle
5 Phasen). Phasen sind sequentiell (kein DAG noetig); Parallelitaet kommt
ueber concurrent Sagas (Multi-Order-Workload).

Public API:
    from kmo_governance.kpm_saga_orchestrator import (
        KPMSagaOrchestrator,
        SagaStep,
        SagaPhase,
        SagaState,
        SagaOutcome,
    )

CRUX-MK
"""
from .kpm_saga_orchestrator import (
    KPMSagaOrchestrator,
    SagaOutcome,
    SagaPhase,
    SagaState,
    SagaStep,
)

__all__ = [
    "KPMSagaOrchestrator",
    "SagaOutcome",
    "SagaPhase",
    "SagaState",
    "SagaStep",
]

# CRUX-MK
