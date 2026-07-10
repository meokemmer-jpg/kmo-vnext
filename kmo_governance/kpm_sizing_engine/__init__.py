# [CRUX-MK]
"""kpm_sizing_engine: KPM (Kemmer-Portfolio-Management) Variante-D Sizing-Engine.

Python-Port (Paritaets-Ziel) der TS-Referenz:
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/ (Commit-Stand f4083f4)

Variante-D-Hybrid per ~/.claude/rules/kpm-sizing.md (Martin-approved 2026-04-19).

!!!! ALPHA-NOT-K0-READY !!!!
Status: CONDITIONAL. Pilot-Pflicht Thomas-First, Shadow-Mode 3+ Monate vor Real-Capital.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.
Echtgeld-Einsatz ausschliesslich via Martin-Phronesis (K_0-Sperr-Liste).
"""

from .numerics import (
    CALMAR_NO_DRAWDOWN_CAP,
    calmar_ratio,
    clamp,
    conditional_var,
    correlation,
    geometric_mean,
    max_drawdown,
    mean,
    quantile,
    sharpe_ratio,
    std_dev,
    sum_values,
    value_at_risk,
    variance,
)
from .kelly_criterion import (
    CONTEXT_FRACTIONS,
    GrowthRuinResult,
    HALF_KELLY_FACTOR,
    KellyContext,
    KellyCriterion,
)
from .drawdown_governance import (
    DEFAULT_THRESHOLDS,
    CapResult,
    CooldownStatus,
    DrawdownGovernance,
    DrawdownLevel,
    DrawdownThresholds,
    DynamicCapResult,
    OverrideLogEntry,
    PeakRecoveryStatus,
)
from .hive_governance_gate import (
    HIVECalibrationResult,
    HIVECalibrationScenario,
    HIVEGovernanceGate,
    LeverageGateResult,
    MarketSignal,
    shannon_from_counts,
)
from .regime_break_detector import (
    CombinedRegimeStatus,
    DispersionResult,
    EdgeDecayResult,
    RegimeBreakDetector,
    RegimeBreakResult,
    RegimeComponents,
)
from .portfolio_optimizer import (
    Asset,
    ConstrainedOptimizationResult,
    CVaRLPResult,
    FrontierPoint,
    LedoitWolfResult,
    OptimizationResult,
    PortfolioOptimizer,
    covariance_from_samples,
)
from .decision_engine import (
    DEFAULT_CONFIG,
    DecisionEngineConfig,
    DecisionGates,
    KPMVarianteDDecisionEngine,
    RegimeContext,
    TradeDecision,
    TradeOpportunity,
    TrinityVariant,
)

__all__ = [
    # numerics
    "mean", "variance", "std_dev", "correlation", "quantile", "geometric_mean",
    "max_drawdown", "sharpe_ratio", "calmar_ratio", "value_at_risk", "conditional_var",
    "sum_values", "clamp", "CALMAR_NO_DRAWDOWN_CAP",
    # kelly
    "KellyCriterion", "KellyContext", "GrowthRuinResult", "CONTEXT_FRACTIONS",
    "HALF_KELLY_FACTOR",
    # drawdown
    "DrawdownGovernance", "DrawdownThresholds", "DrawdownLevel", "DEFAULT_THRESHOLDS",
    "CapResult", "DynamicCapResult", "OverrideLogEntry", "CooldownStatus",
    "PeakRecoveryStatus",
    # hive
    "HIVEGovernanceGate", "MarketSignal", "LeverageGateResult", "HIVECalibrationResult",
    "HIVECalibrationScenario", "shannon_from_counts",
    # regime
    "RegimeBreakDetector", "RegimeBreakResult", "DispersionResult", "EdgeDecayResult",
    "CombinedRegimeStatus", "RegimeComponents",
    # portfolio
    "PortfolioOptimizer", "Asset", "OptimizationResult", "FrontierPoint", "CVaRLPResult",
    "LedoitWolfResult", "ConstrainedOptimizationResult", "covariance_from_samples",
    # decision engine
    "KPMVarianteDDecisionEngine", "TradeOpportunity", "TradeDecision", "DecisionGates",
    "DecisionEngineConfig", "DEFAULT_CONFIG", "RegimeContext", "TrinityVariant",
]
