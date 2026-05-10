# [CRUX-MK]
"""Cape-Familien-Homeostasis (Welle-38 Phase-31 W38-T2, 9. Familien-Lift, 20. Multi-Domain-Lift).

Bio-Aequivalent: Hypothalamus-Setpoint-Regulation auf Familien-Mental-Load.
Pattern-Quelle: kpm_homeostasis_controller (Welle-26, KPM-Trading)
                + homeostasis_controller (Welle-25, Hotel-Domain).

Domain: Familien-Cape-Coral-Relocation. Setpoint = ideale Familien-Mental-Load
(z.B. Stress-Level, Sleep-Hours-Aggregat). Deviation triggert Cape-Coral-Pacing-
Adjustments (mehr Pause, weniger Decisions, externe-Hilfe-Aktivierung).

Pattern-Isomorphie:
- Asset-Class       -> Familien-Member (Martin, Gerdi, Sebastian, etc.)
- AllocationPct     -> MentalLoadScore [0.0-1.0] (1.0 = burnout-Risiko)
- Setpoint          -> ideale Mental-Load (default 0.5)
- REDUCING_POSITION -> ENGAGE_RELIEF (externe-Hilfe / Pause)
- INCREASING_POSITION -> ENABLE_PROGRESS (mehr Familien-Decisions)
- CRITICAL          -> CRITICAL (sofort Phronesis-L13 + ggf. Therapie)

Public API:
    from kmo_governance.cape_familien_homeostasis import (
        FamilienState,
        MentalLoadSample,
        FamilienRebalanceAction,
        FamilienHomeostasisDecision,
        CapeFamilienHomeostasis,
    )

CRUX-MK
"""
from .cape_familien_homeostasis import (
    CapeFamilienHomeostasis,
    FamilienHomeostasisDecision,
    FamilienRebalanceAction,
    FamilienState,
    MentalLoadSample,
)

__all__ = [
    "CapeFamilienHomeostasis",
    "FamilienHomeostasisDecision",
    "FamilienRebalanceAction",
    "FamilienState",
    "MentalLoadSample",
]

# CRUX-MK
