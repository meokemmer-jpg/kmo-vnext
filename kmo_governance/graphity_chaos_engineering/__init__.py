# [CRUX-MK]
"""Graphity-Chaos-Engineering (Welle-38 Phase-31 Bio-Pattern-Lift, 19. Lift).

Bio-Aequivalent: Innate-Immunity-Stress-Test auf Verlag-Edit-Pipeline.
Pattern-Quelle: kmo_governance.chaos_engineering (Welle-9, Hotel-Domain)
                + sae_chaos_engineering_for_aiops (Welle-30, SAE-Domain).

Verlag-Domain-Fault-Klassen (Graphity):
- AUTHOR_BURNOUT: Autor kann nicht liefern (Manuscript-Stall)
- EDITOR_REVIEW_BLOCK: Editor blockiert Review (Workflow-Stall)
- TYPESETTING_ERROR: Setzer-Fault (Layout-Korrumpierung)
- DEADLINE_MISS: Termin-Verfehlung (Schedule-Drift)
- VG_WORT_QUOTA_EXCEEDED: Compliance-Verletzung

Pattern-Isomorphie:
- Hotel-Service       -> Verlag-Edit-Stage (manuscript_id + editor_role)
- ChaosScenario       -> GraphityChaosScenario
- agent_class         -> editor_role (author/editor/reviewer/typesetter/corrector)
- slots_impacted      -> manuscripts_blocked
- trinity_voting      -> editorial_consensus (3-Stimmen Editor+Reviewer+Author)

19. Multi-Domain-Bio-Pattern-Lift: 8. Verlag-Lift in 7. Domain (Verlag-Graphity).

Public API:
    from kmo_governance.graphity_chaos_engineering import (
        VerlagFaultType,
        FaultSeverity,
        GraphityChaosScenario,
        GraphityChaosOutcome,
        GraphityChaosEngineering,
    )

CRUX-MK
"""
from .graphity_chaos_engineering import (
    FaultSeverity,
    GraphityChaosEngineering,
    GraphityChaosOutcome,
    GraphityChaosScenario,
    VerlagFaultType,
)

__all__ = [
    "FaultSeverity",
    "GraphityChaosEngineering",
    "GraphityChaosOutcome",
    "GraphityChaosScenario",
    "VerlagFaultType",
]

# CRUX-MK
