# [CRUX-MK]
"""LexVance-Compliance-Audit-Bus (Welle-40 Phase-33, 8. Domain Erweiterung, 22. Multi-Domain-Lift).

Bio-Aequivalent: Lymphatic-System auf Legal-Compliance-Audit-Trail.
Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain)
                + cape_familien_audit_bus (Welle-30, Familien-Domain)
                + ninedots_pmo_audit_bus (Welle-32, PMO-Domain).

Domain-Note (8. Domain — LexVance Legal-Compliance):
- LexVance = Kemmer Legal & Compliance Entity
- Legal-Audit-Trail mit GDPR + MiFID-II + AktG + StPO + DSGVO Konformitaet
- Lymphatic-Pattern: peripher gesammelte Legal-Decisions zentral aggregiert
  + Compliance-Tag-Filterung + Jurisdiction-aware Retention
- Hash-Chain Pflicht (per external-anchor-requirement-rule, RFC3161-compatible)

Pattern-Mapping (4-Domain-Vergleich):
- Hotel.event_type      -> KPM.event_type      -> Familien.decision_type   -> LexVance.legal_obligation_type
- Hotel.actor_id        -> KPM.strategy_id      -> Familien.member_role     -> LexVance.mandant_id
- Hotel.retention 168h  -> KPM 168h             -> Familien 8760h (1J)      -> LexVance 87600h (10J GDPR Pflicht)
- Hotel.compliance_tag  -> KPM.compliance       -> Familien.gdpr_tag        -> LexVance.jurisdiction (DE/US/UK/EU)

Public API:
    from kmo_governance.lexvance_compliance_audit_bus import (
        LegalObligationType,
        Jurisdiction,
        LegalAuditEvent,
        LexVanceComplianceAuditBus,
    )

CRUX-MK
"""
from .lexvance_compliance_audit_bus import (
    Jurisdiction,
    LegalAuditEvent,
    LegalObligationType,
    LexVanceComplianceAuditBus,
)

__all__ = [
    "Jurisdiction",
    "LegalAuditEvent",
    "LegalObligationType",
    "LexVanceComplianceAuditBus",
]

# CRUX-MK
