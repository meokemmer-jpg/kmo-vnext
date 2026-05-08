# [CRUX-MK]
"""HeyLou-OTA-Pricing-Failover (Welle-35 Phase-28 Bio-Pattern-Lift).

Bio-Aequivalent: Kollateral-Kreislauf (Active-Standby Failover bei Hauptarterien-Block).
Pattern-Quelle: kmo_governance.failover_router (Welle-19 Phase-13.1, Hotel-Domain).

HeyLou-OTA-Domain-Note:
- HeyLou-Hotel-Operations nutzen multiple OTA-Pricing-Sources fuer Verfuegbarkeit + Rate-Parity
- primary_ota = primaere Pricing-Source (z.B. Booking.com Direct-Connect)
- standby_otas = Fallback-Sources (z.B. Expedia, Direct-Booking-Engine, GDS-Amadeus)
- Failover-Trigger: 5 fehlgeschlagene Booking-Outcomes in Folge (OTA-Volatilitaet > Hotel-Domain)
- Pricing-Freshness graduiert: primary 30s, standby[0] 60s, standby[1] 300s
- Recovery: manual promote (Q_0-Sicherheit gegen Auto-Switch-Loops bei Pricing-Drift)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, andere Domaene.
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.
"""
from .heylou_ota_pricing_failover import (
    FailoverState,
    HeyLouOTAPricingFailover,
    OTAPricingDecision,
    OTASourceStatus,
)

__all__ = [
    "FailoverState",
    "HeyLouOTAPricingFailover",
    "OTAPricingDecision",
    "OTASourceStatus",
]

# CRUX-MK
