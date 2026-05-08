# [CRUX-MK]
"""Cape-Familien-Audit-Bus (Welle-30 Phase-23 KMO-vNext Wild-Code-Blindtest 1/3).

Bio-Aequivalent: Lymphatic-System (peripher gesammelte Familien-Decision-Audit-Events
zentral aggregiert mit Compliance-Tag-Filterung + GDPR/US-Relocation Retention).
Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
2. Lift: kmo_governance.kpm_audit_event_bus (Welle-26 Phase-19, KPM-Trading-Domain).

Cape-Coral-Domain-Note (EXTERNE Domain Wild-Code-Blindtest):
- Cape-Coral-Vault = Familien-Verwaltungs-System (Wegzug, Visa, Steuer, Schul-Wahl,
  Brueder-Vereinbarungen, Medical-Decisions, etc.)
- Lymphatic-Pattern angewendet auf Familien-Decision-Audit-Trail
- Familien-Member-Roles publishen FamilienAuditEvents prio-priorisiert nach Compliance-Tags
  (PERSONAL_DATA / FAMILIAL / LEGAL / FINANCIAL_K0 / MEDICAL_PRIVACY / GDPR / US_RELOCATION)
- Idempotent + immutable (frozen Dataclass)
- GDPR-Default-Retention: 1 Jahr = 8760h (signifikant laenger als Hotel/KPM 168h)

Demonstriert Bio-Pattern-Lift auf 3. Domain (externe, Wild-Code-Blindtest):
gleicher Architekturkern (Lymphatic-System), 3 unterschiedliche Vokabular-Schichten:
Hotel-Operationen, Trading-Strategien, Familien-Decisions.
Belegt 3-Schicht-Architektur (Strukturkern + Bio-Tag + Domain-Vokabular) ist
domain-unabhaengig.
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Klassen:
  - FamilienDecisionType (Enum): DECISION_FAMILIAL/DECISION_VISA/DECISION_TAX/
    DECISION_MEDICAL/DECISION_FINANCIAL/DECISION_PROCEDURAL
  - ComplianceTag (Enum): PERSONAL_DATA/FAMILIAL/LEGAL/FINANCIAL_K0/MEDICAL_PRIVACY/
    GDPR/US_RELOCATION
  - FamilienAuditEvent (Frozen): event_id, decision_type, family_member_role, context,
    compliance_tags, metadata, timestamp
  - CapeFamilienAuditBus: publish, query, validate_event, cleanup_old, get_stats

Q_0-PFLICHT: KEINE Real-Familien-Daten in Tests (alle Test-Daten dummy: "test_member_x",
"test_decision_y") -- Subagent-Datenschutz-Invariante.
"""
from .cape_familien_audit_bus import (
    CapeFamilienAuditBus,
    ComplianceTag,
    FamilienAuditEvent,
    FamilienDecisionType,
)

__all__ = [
    "CapeFamilienAuditBus",
    "ComplianceTag",
    "FamilienAuditEvent",
    "FamilienDecisionType",
]

# CRUX-MK
