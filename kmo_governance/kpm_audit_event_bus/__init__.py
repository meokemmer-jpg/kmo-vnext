# [CRUX-MK]
"""KPM-Audit-Event-Bus (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Aequivalent: Lymphatic-System (peripher gesammelte Trade-Audit-Events
zentral aggregiert mit Compliance-Tag-Filterung + MiFID-RTS-25 Retention).
Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Lymphatic-Pattern angewendet auf Trade-Audit-Trail
- Strategy-Worker publishen TradeAuditEvents prio-priorisiert nach Compliance-Tags
  (KYC/AML/MIFID_BEST_EXEC/POSITION_LIMIT/RISK_BUDGET/LATE_TRADING)
- Idempotent + immutable (frozen Dataclass)
- MiFID-RTS-25 Retention >= 168h (7 Tage Default-Window)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, andere Domaene.
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Klassen:
  - TradeEventType (Enum): BUY/SELL/CANCEL/PARTIAL_FILL/REJECT/ADJUSTMENT
  - ComplianceTag (Enum): KYC/AML/MIFID_BEST_EXEC/POSITION_LIMIT/RISK_BUDGET/LATE_TRADING
  - TradeAuditEvent (Frozen): event_id, strategy_id, event_type, instrument_id,
    quantity, price, timestamp, compliance_tags, metadata
  - KPMAuditEventBus: publish, query, validate_event, cleanup_old, get_stats
"""
from .kpm_audit_event_bus import (
    ComplianceTag,
    KPMAuditEventBus,
    TradeAuditEvent,
    TradeEventType,
)

__all__ = [
    "ComplianceTag",
    "KPMAuditEventBus",
    "TradeAuditEvent",
    "TradeEventType",
]

# CRUX-MK
