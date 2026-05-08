# [CRUX-MK]
"""KPM-Feature-Flag-Engine (Welle-29 Phase-22 Bio-Pattern-Lift).

Bio-Aequivalent: Genexpressions-Regulation (Promoter/Repressor + Expression-Gradient).
Pattern-Quelle: kmo_governance.feature_flag_engine (Welle-9, Hotel-Domain).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Genexpressions-Pattern angewendet auf Trading-Strategy-Activation
- Strategy-Worker schalten Trading-Strategies ueber Feature-Flags ein/aus
  (DISABLED / RAMP_UP / ENABLED / EMERGENCY_OFF) mit percentage_rollout-Gradient
- Audit-Trail-Pflicht fuer Compliance (jeder State-Wechsel ist FlagAuditEvent)
- Idempotent-deterministisch via hashlib.md5(flag_id+request_id) % 100

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern, andere Domaene.
Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Klassen:
  - FlagState (Enum): DISABLED, RAMP_UP, ENABLED, EMERGENCY_OFF
  - FlagDefinition (frozen): flag_id, strategy_id, default_state, description, owner, ts
  - FlagDecision (frozen): flag_id, strategy_id, state, percentage_rollout, enabled, reason, ts
  - FlagAuditEvent (frozen): flag_id, old_state, new_state, changed_by, reason, ts
  - KPMFeatureFlagEngine: register_flag, set_state, set_percentage_rollout, evaluate,
    emergency_off, clear_emergency, get_audit_log, list_flags
"""
from .kpm_feature_flag_engine import (
    FlagAuditEvent,
    FlagDecision,
    FlagDefinition,
    FlagState,
    KPMFeatureFlagEngine,
)

__all__ = [
    "FlagAuditEvent",
    "FlagDecision",
    "FlagDefinition",
    "FlagState",
    "KPMFeatureFlagEngine",
]

# CRUX-MK
