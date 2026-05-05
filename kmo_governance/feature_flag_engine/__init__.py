"""feature_flag_engine package [CRUX-MK].

KMO-vNext Welle-10 Phase-6.5 SUBAGENT-G: Feature-Flag-Engine SKELETON.

Bio-Aequivalent: Genexpressions-Regulation (Promoter/Enhancer/Silencer).
Promotor-Bindungen entscheiden welche Gene transkribiert werden, abhaengig vom
zellulaeren Kontext (Konzentrationen, Modifikationen). Analog dazu schaltet die
Feature-Flag-Engine Software-Verhalten kontextabhaengig (User, Hotel, Environment).

Pattern-Inspiration:
  - kmo_governance/sigma_switch (Mode-State-Machine + Hysterese)
  - kmo_governance/multi_signal_policy (N-Input-Aggregation, Markov-State)
  - kmo_governance/pre_production_canary (Deterministic-Routing via md5)

K11 Cascade-Containment: Flags isolieren Risiko von Feature-Rollouts.
K13 Pre-Action-Verification: Pre-Conditions vor Flag-Updates explizit.

Komponenten:
  - FlagRule (frozen): unveraenderlicher Regel-Kontainer (boolean/percentage/contextual)
  - FlagContext (frozen): Auswertungs-Kontext (user_id/hotel_id/environment/custom)
  - FlagEvalRecord (frozen): Append-only Audit-Eintrag pro Evaluation
  - FeatureFlagEngine: Registry + Evaluation + Variant-Selection (thread-safe)
  - PercentageRollout: Deterministic md5(flag_id+user_id) bucket routing
  - ContextualRule: AND/OR-conditions ueber Context-Attributen
  - ABTestVariantSelector: Multi-Variant-Selection mit Weights (deterministic)
  - FlagAuditLog: Append-only Audit-Trail mit Distributions-Stats
"""

from kmo_governance.feature_flag_engine.feature_flag_engine import (
    ABTestVariantSelector,
    ContextualRule,
    FeatureFlagEngine,
    FlagAuditLog,
    FlagContext,
    FlagEvalRecord,
    FlagRule,
    FlagRuleType,
    PercentageRollout,
)

__all__ = [
    "ABTestVariantSelector",
    "ContextualRule",
    "FeatureFlagEngine",
    "FlagAuditLog",
    "FlagContext",
    "FlagEvalRecord",
    "FlagRule",
    "FlagRuleType",
    "PercentageRollout",
]

# CRUX-MK
