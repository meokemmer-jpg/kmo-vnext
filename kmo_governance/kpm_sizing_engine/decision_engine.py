# [CRUX-MK]
"""KPMVarianteDDecisionEngine: Master-Wrapper per ~/.claude/rules/kpm-sizing.md.

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/KPMVarianteDDecisionEngine.ts
    (Commit-Stand f4083f4)

Pipeline (Reihenfolge der Gates ist Teil der Paritaet):
  1. Kelly-Optimum  2. Variante-D-Context-Fraction  3. Drawdown-Multiplier (4-Stufen)
  4. HIVE-Gate  5. Regime-Gate  6. Trinity-Modifier  7. Pilot-Mode-Cap  -> EUR-Size

Trinity-Pattern (per rules/coding.md §2):
  conservative 0.7x | aggressive 1.0x | contrarian 0.85x

!!!! ALPHA-NOT-K0-READY !!!!
Phase-1 Pilot: Thomas-First. Shadow-Mode 3+ Monate Paper-Trading vor Real-Capital.
Diese Engine ist KEINE Investment-Empfehlung. Nur Edu + Pilot.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal

from .drawdown_governance import DrawdownGovernance, DrawdownLevel
from .hive_governance_gate import HIVEGovernanceGate, MarketSignal
from .kelly_criterion import KellyContext, KellyCriterion
from .numerics import clamp

__all__ = [
    "TradeOpportunity",
    "RegimeContext",
    "TrinityVariant",
    "DecisionGates",
    "TradeDecision",
    "DecisionEngineConfig",
    "DEFAULT_CONFIG",
    "KPMVarianteDDecisionEngine",
    "TRINITY_MODIFIERS",
    "PILOT_MODE_FRACTION_CAP",
]

RegimeContext = Literal["normal", "high-vola", "regime-break"]
TrinityVariant = Literal["conservative", "aggressive", "contrarian"]

# Trinity-Modifier auf die Context-Fraction (dimensionslos, per TS-Referenz)
TRINITY_MODIFIERS: Dict[str, float] = {
    "conservative": 0.7,   # Family-Office-Default
    "aggressive": 1.0,     # Variante-D-Maximum
    "contrarian": 0.85,    # Hybrid mit Stress-Test-Cap
}

# Thomas-First Pilot-Hard-Cap (Fraction, per rules/kpm-sizing.md Phase-1)
PILOT_MODE_FRACTION_CAP: float = 0.25


@dataclass(frozen=True)
class TradeOpportunity:
    asset: str
    win_probability: float  # (0, 1)
    win_amount: float       # > 0 (Multiplikator)
    loss_amount: float      # > 0 (Multiplikator)
    notional: float         # EUR verfuegbares Kapital


@dataclass(frozen=True)
class DecisionGates:
    drawdown_passed: bool
    hive_passed: bool
    regime_passed: bool


@dataclass(frozen=True)
class TradeDecision:
    size: float             # EUR finale Position-Size
    fraction: float         # [0, 1] von notional
    trinity_variant: TrinityVariant
    rationale: str
    gates: DecisionGates
    rejected: bool
    warnings: List[str]


@dataclass(frozen=True)
class DecisionEngineConfig:
    pilot_mode: bool = True            # Thomas-First: Cap bei 0.25
    withdrawal_phase: bool = False     # aktive Entnahme-Phase
    trinity_variant: TrinityVariant = "conservative"


DEFAULT_CONFIG = DecisionEngineConfig(
    pilot_mode=True, withdrawal_phase=False, trinity_variant="conservative"
)


@dataclass(frozen=True)
class DrawdownStatus:
    level: DrawdownLevel
    drawdown: float


class KPMVarianteDDecisionEngine:
    """Zentrale Trade-Decision-Engine (Variante-D)."""

    def __init__(
        self,
        drawdown_gov: DrawdownGovernance,
        hive_gate: HIVEGovernanceGate,
        config: DecisionEngineConfig = DEFAULT_CONFIG,
    ) -> None:
        self.drawdown_gov = drawdown_gov
        self.hive_gate = hive_gate
        self.config = config

    def _resolve_kelly_context(
        self, regime: RegimeContext, edge_confidence: Literal["high", "medium"]
    ) -> KellyContext:
        """Finaler Kelly-Context per Variante-D-Tabelle (Prioritaets-Reihenfolge TS-identisch)."""
        if regime == "regime-break":
            return "regime-break"
        if regime == "high-vola":
            return "high-vola"
        if self.config.withdrawal_phase:
            return "withdrawal-phase"
        if edge_confidence == "high":
            return "normal-high-confidence"
        return "normal-medium"

    @staticmethod
    def _trinity_modifier(variant: TrinityVariant) -> float:
        """Trinity-Pattern-Modifier (conservative 0.7 / aggressive 1.0 / contrarian 0.85)."""
        return TRINITY_MODIFIERS[variant]

    def _pilot_mode_cap(self, fraction: float) -> float:
        """Pilot-Mode Hard-Cap (Thomas-First): Fraction max 0.25 wenn pilot_mode."""
        if self.config.pilot_mode:
            return min(fraction, PILOT_MODE_FRACTION_CAP)
        return fraction

    def decide_trade_size(
        self,
        opportunity: TradeOpportunity,
        current_hive: float,
        regime: RegimeContext = "normal",
        market_signal: MarketSignal = "neutral",
        edge_confidence: Literal["high", "medium"] = "medium",
    ) -> TradeDecision:
        """Entscheide Trade-Size (7-Schritt-Pipeline, Reihenfolge TS-identisch).

        Pre: opportunity.win_probability in (0, 1), opportunity.notional > 0,
             current_hive in [0, 1].
        Post: rejected=True mit size=0 wenn ein Gate blockt; sonst
              size = fraction * notional, fraction in [0, 1].
        """
        warnings: List[str] = []

        # 1. Kelly Criterion
        kelly = KellyCriterion(
            opportunity.win_probability, opportunity.win_amount, opportunity.loss_amount
        )
        f_opt = kelly.optimal_fraction()
        if f_opt <= 0:
            return TradeDecision(
                size=0.0,
                fraction=0.0,
                trinity_variant=self.config.trinity_variant,
                rationale=f"Kelly-Edge negativ (f*={f_opt:.4f}) — KEIN Trade",
                gates=DecisionGates(
                    drawdown_passed=False, hive_passed=False, regime_passed=False
                ),
                rejected=True,
                warnings=["Negative Edge"],
            )

        # 2. Variante-D-Context
        ctx = self._resolve_kelly_context(regime, edge_confidence)
        ctx_fraction = kelly.context_adaptive_fraction(ctx)

        # 3. Drawdown-Multiplier
        dd_result = self.drawdown_gov.enforce_level()
        drawdown_passed = dd_result.position_multiplier > 0
        if not drawdown_passed:
            return TradeDecision(
                size=0.0,
                fraction=0.0,
                trinity_variant=self.config.trinity_variant,
                rationale=(
                    f"Drawdown-Gate failed: {dd_result.action} "
                    f"(level={dd_result.level}, "
                    f"dd={self.drawdown_gov.current_drawdown() * 100:.1f}%)"
                ),
                gates=DecisionGates(
                    drawdown_passed=False,
                    hive_passed=False,
                    regime_passed=regime == "normal",
                ),
                rejected=True,
                warnings=[f"Drawdown-Level: {dd_result.level}"],
            )
        if dd_result.level == "soft-brake":
            warnings.append(f"Drawdown soft-brake aktiv: {dd_result.action}")

        # 4. HIVE-Gate
        hive_res = self.hive_gate.leverage_gate(current_hive, market_signal)
        if hive_res.recommended_action == "deleverage":
            hive_passed = False
            hive_multiplier = 0.0
        elif hive_res.recommended_action == "maintain":
            # Trade auf Base-Level erlaubt (keine Leverage-Erhoehung)
            hive_passed = True
            hive_multiplier = 1.0
        else:  # increase
            hive_passed = True
            hive_multiplier = 1.0
        if not hive_passed:
            return TradeDecision(
                size=0.0,
                fraction=0.0,
                trinity_variant=self.config.trinity_variant,
                rationale=f"HIVE-Gate failed: {hive_res.reason}",
                gates=DecisionGates(
                    drawdown_passed=True,
                    hive_passed=False,
                    regime_passed=regime == "normal",
                ),
                rejected=True,
                warnings=["HIVE Auto-Deleverage"],
            )
        if hive_res.recommended_action == "maintain":
            warnings.append(hive_res.reason)

        # 5. Regime-Gate
        regime_passed = regime != "regime-break"
        if not regime_passed:
            return TradeDecision(
                size=0.0,
                fraction=0.0,
                trinity_variant=self.config.trinity_variant,
                rationale="Regime-Break detected -> kein Trade (per Variante-D)",
                gates=DecisionGates(
                    drawdown_passed=True, hive_passed=True, regime_passed=False
                ),
                rejected=True,
                warnings=["Regime-Break aktiv"],
            )

        # 6. Trinity-Modifier
        trinity_mod = self._trinity_modifier(self.config.trinity_variant)

        # Kombinieren
        final_fraction = (
            ctx_fraction * dd_result.position_multiplier * hive_multiplier * trinity_mod
        )

        # 7. Pilot-Mode-Cap
        before_pilot = final_fraction
        final_fraction = self._pilot_mode_cap(final_fraction)
        if final_fraction < before_pilot:
            warnings.append(
                f"Pilot-Mode-Cap aktiv: {before_pilot:.4f} -> {final_fraction:.4f}"
            )

        final_fraction = clamp(final_fraction, 0.0, 1.0)
        final_size = final_fraction * opportunity.notional

        return TradeDecision(
            size=final_size,
            fraction=final_fraction,
            trinity_variant=self.config.trinity_variant,
            rationale=(
                f"Kelly f*={f_opt:.4f} -> Variante-D-{ctx}={ctx_fraction:.4f} "
                f"-> Drawdown={dd_result.level}({dd_result.position_multiplier:.2f}x) "
                f"-> HIVE={current_hive:.2f}({hive_res.recommended_action}) "
                f"-> Trinity-{self.config.trinity_variant}={trinity_mod:.2f}x "
                f"-> final f={final_fraction:.4f} "
                f"({'PILOT-MODE' if self.config.pilot_mode else 'NORMAL-MODE'})"
            ),
            gates=DecisionGates(
                drawdown_passed=drawdown_passed,
                hive_passed=hive_passed,
                regime_passed=regime_passed,
            ),
            rejected=False,
            warnings=warnings,
        )

    def drawdown_status(self) -> DrawdownStatus:
        """Drawdown-Status (Delegate)."""
        dd = self.drawdown_gov.current_drawdown()
        return DrawdownStatus(level=self.drawdown_gov.enforce_level().level, drawdown=dd)

    def record_equity(self, value: float) -> None:
        """Post-Trade-Equity-Update (Delegate)."""
        self.drawdown_gov.record_equity(value)
