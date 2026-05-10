# [CRUX-MK]
"""Graphity-Homeostasis-Pricing (Welle-44 Phase-37, 26. Multi-Domain-Lift).

Bio-Aequivalent: Thermoregulation auf Verlag-Royalty-Pricing-Drift.
Pattern-Quelle: kpm_homeostasis_controller (Welle-26 Trading) + cape_familien_homeostasis (Welle-38).

Domain: VG-Wort + Royalty-Tracking. Setpoint = ideale Royalty-Rate (% pro Verkaufseinheit).
Deviation triggert Royalty-Adjustment-Aktionen (Author-Renegotiation, ggf. neue Vertragsklausel).

Public API:
    from kmo_governance.graphity_homeostasis_pricing import (
        RoyaltyState,
        RoyaltySample,
        RoyaltyDecision,
        GraphityHomeostasisPricing,
    )

CRUX-MK
"""
from .graphity_homeostasis_pricing import (
    GraphityHomeostasisPricing,
    RoyaltyDecision,
    RoyaltySample,
    RoyaltyState,
)

__all__ = [
    "GraphityHomeostasisPricing",
    "RoyaltyDecision",
    "RoyaltySample",
    "RoyaltyState",
]

# CRUX-MK
