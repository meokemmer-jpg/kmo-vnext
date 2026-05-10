# [CRUX-MK]
"""HeyLou-Chaos-Engineering (Welle-43 Phase-36, 25. Multi-Domain-Lift).

Bio-Aequivalent: Innate-Immunity-Stress-Test auf HeyLou-OTA-Pricing-Pipeline.
Pattern-Quelle: chaos_engineering (Welle-9 Hotel) + sae_chaos_engineering_for_aiops (Welle-30)
                + graphity_chaos_engineering (Welle-38 Verlag).

Domain: HeyLou OTA-Pricing-Failover. Fault-Klassen:
- OTA_PROVIDER_TIMEOUT (Booking.com / Expedia API timeout)
- PRICE_CALCULATION_OVERFLOW (Numeric-Overflow in dynamic pricing)
- INVENTORY_DESYNC (Cross-OTA Inventory drift)
- COMPETITOR_PRICE_FETCH_FAIL (Marktdaten-API down)
- CURRENCY_RATE_STALE (FX-Rate older than 1h)

Public API:
    from kmo_governance.heylou_chaos_engineering import (
        OTAFaultType,
        FaultSeverity,
        HeyLouChaosScenario,
        HeyLouChaosOutcome,
        HeyLouChaosEngineering,
    )

CRUX-MK
"""
from .heylou_chaos_engineering import (
    FaultSeverity,
    HeyLouChaosEngineering,
    HeyLouChaosOutcome,
    HeyLouChaosScenario,
    OTAFaultType,
)

__all__ = [
    "FaultSeverity",
    "HeyLouChaosEngineering",
    "HeyLouChaosOutcome",
    "HeyLouChaosScenario",
    "OTAFaultType",
]

# CRUX-MK
