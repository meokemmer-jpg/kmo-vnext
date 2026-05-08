# [CRUX-MK]
"""9dots-PMO-Audit-Bus (Welle-32 Phase-25 KMO-vNext Bio-Pattern-Lift 6/6).

Bio-Aequivalent: Lymphatic-System (peripher gesammelte PMO-Decision-Audit-Events
zentral aggregiert mit Compliance-Tag-Filterung + COSMOS/SAE-Governance/MYZ-Layer-Retention).

Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
2. Lift: kmo_governance.kpm_audit_event_bus (Welle-26 Phase-19, KPM-Trading).
3. Lift: kmo_governance.cape_familien_audit_bus (Welle-30 Phase-23, Cape-Familien).
4./5. Lifts: weitere KMO-Sublayer-Lifts.
6. Lift (HIER): 9dots-PMO-Compliance-Audit-Trail (agentic Software Platform SAE v8).

9dots-PMO-Domain-Note:
- 9dots GmbH = agentic Software Platform (SAE v8: 600 Agenten, 200 Slots x 3 Trinity-Varianten).
- PMO-Compliance dokumentiert Decisions ueber:
  Slot-Allocation (welcher Agent in welchem Slot),
  Agent-Class-Promotion (Trinity-Voting-Outcome),
  Trinity-Voting-Outcomes (Conservative/Aggressive/Contrarian),
  Governance-Tier-Aenderungen (q-Norm [-2, +2]),
  Hamilton-Optimization-Pivots (H = u + lambda*f),
  Budget-Allocation-Aenderungen (T_max, OPEX-Caps).
- Lymphatic-Pattern angewendet auf SAE-Governance-Audit-Trail.
- Idempotent + immutable (frozen Dataclass).
- SAE-Audit-Default-Retention: 6 Monate = 4380h
  (zwischen Hotel 1h Operational und Cape-Familien 8760h GDPR;
   ausreichend fuer Trinity-Backtrace + Hamilton-Pivot-Audit).

Demonstriert Bio-Pattern-Lift auf 6. Domain (interne 9dots-Compliance-Domain):
gleicher Architekturkern (Lymphatic-System), 6 unterschiedliche Vokabular-Schichten:
Hotel-Operationen, Trading-Strategien, Familien-Decisions, [4./5. Lift], 9dots-PMO-Compliance.
Belegt 3-Schicht-Architektur (Strukturkern + Bio-Tag + Domain-Vokabular) ist
domain-unabhaengig und universell.
Siehe BIO-PATTERN-LIFT-DEMO.md fuer 6-Domain-Isomorphie-Tabelle.

Klassen:
  - PMODecisionType (Enum): SLOT_ALLOCATION/AGENT_PROMOTION/AGENT_RELEGATION/
    TRINITY_VOTE/GOVERNANCE_TIER_CHANGE/HAMILTON_PIVOT/BUDGET_ADJUSTMENT
  - ComplianceTag (Enum): COSMOS/SAE_GOVERNANCE/MYZ_LAYER/CRUX_BINDING/
    K0_RELEVANT/Q0_RELEVANT/AUDIT_RTS25
  - PMOAuditEvent (Frozen): event_id, decision_type, agent_class, slot_id,
    governance_tier, context, compliance_tags, metadata, timestamp
  - NineDotsPMOAuditBus: publish, query, validate_event, cleanup_old, get_stats

Q_0-PFLICHT: KEINE Real-9dots-Production-Daten in Tests
             (alle Test-Daten dummy: "test_agent_x", "test_slot_y", "test_tier_z")
             -- Subagent-Datenschutz-Invariante.
"""
from .ninedots_pmo_audit_bus import (
    ComplianceTag,
    NineDotsPMOAuditBus,
    PMOAuditEvent,
    PMODecisionType,
)

__all__ = [
    "ComplianceTag",
    "NineDotsPMOAuditBus",
    "PMOAuditEvent",
    "PMODecisionType",
]

# CRUX-MK
