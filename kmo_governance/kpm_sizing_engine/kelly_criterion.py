# [CRUX-MK]
"""KellyCriterion: Optimal Bet-Sizing per Kelly (1956) und Thorp (1969-2008).

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/KellyCriterion.ts
    (Commit-Stand f4083f4, inkl. Welle-M-Patch-KPM-1 Asymmetric-Loss-Korrektur)

Foundation:
- Kelly (1956) Eq. 4: f* = (p*winAmount - q*lossAmount) / (winAmount*lossAmount)
- Thorp (1969/2006): Half-Kelly als Praxis-Heuristik
- KPM-Variante-D-Hybrid (Martin-approved 2026-04-19, ~/.claude/rules/kpm-sizing.md):
  kontext-adaptive Kelly-Fraction 0.25-0.40, NICHT fix Half-Kelly 0.5.

Status: CONDITIONAL. ALPHA-NOT-K0-READY. Pilot-Pflicht Thomas-First, Shadow-Mode 3+ Monate.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Literal

from .numerics import clamp

__all__ = [
    "KellyContext",
    "KellyCriterion",
    "GrowthRuinResult",
    "CONTEXT_FRACTIONS",
    "HALF_KELLY_FACTOR",
    "RUIN_RISK_COEFFICIENT",
]

# Kontext-Klassen fuer Variante-D-Adaptive-Fraction (per rules/kpm-sizing.md Tabelle)
KellyContext = Literal[
    "normal-high-confidence",  # Normalregime + hoher Edge-Confidence => 0.40
    "normal-medium",           # Default => 0.30
    "high-vola",               # Erhoehte Vola / Regime-Unsicherheit => 0.25
    "withdrawal-phase",        # Entnahme-Phase / Liquiditaetsbedarf hoch => 0.20
    "regime-break",            # Regimebruch detektiert => 0 (pausieren)
]

# Variante-D Kelly-Fraction-Tabelle (dimensionslose Faktoren auf f*)
CONTEXT_FRACTIONS: Dict[str, float] = {
    "normal-high-confidence": 0.40,
    "normal-medium": 0.30,
    "high-vola": 0.25,
    "withdrawal-phase": 0.20,
}

# Thorp-Empfehlung Half-Kelly (dimensionsloser Faktor)
HALF_KELLY_FACTOR: float = 0.5

# Heuristik: ruinRisk = 0.5 * (fraction/fOpt)^2, gecappt auf [0, 1] (per TS-Referenz)
RUIN_RISK_COEFFICIENT: float = 0.5


@dataclass(frozen=True)
class GrowthRuinResult:
    """Ergebnis von growth_at_risk_of_ruin (TS: {growth, ruinRisk})."""

    growth: float
    ruin_risk: float


class KellyCriterion:
    """KellyCriterion fuer Binary-Outcome-Bet (win/loss), asymmetric-loss-korrekt.

    Pre:
      - 0 < win_probability < 1
      - win_amount > 0 (absoluter Gewinn-Betrag bei Win)
      - loss_amount > 0 (absoluter Verlust-Betrag bei Loss)

    Invariants:
      - p + q = 1 (mutually exclusive)
      - Asymmetric-Kelly: f* = (p*w - q*l) / (w*l)
    """

    def __init__(self, win_probability: float, win_amount: float, loss_amount: float) -> None:
        if win_probability <= 0 or win_probability >= 1:
            raise ValueError("KellyCriterion: winProbability must be in (0, 1)")
        if win_amount <= 0:
            raise ValueError("KellyCriterion: winAmount must be > 0")
        if loss_amount <= 0:
            raise ValueError("KellyCriterion: lossAmount must be > 0")
        self.win_probability = win_probability
        self.win_amount = win_amount
        self.loss_amount = loss_amount

    def optimal_fraction(self) -> float:
        """Optimale Kelly-Fraction f* fuer asymmetrische Outcomes.

        Pre: Konstruktor-Invarianten gelten.
        Post: f* = (p*w - q*l) / (w*l); negativ wenn Edge negativ (KEIN BET, NICHT short).
        """
        p = self.win_probability
        q = 1 - p
        w = self.win_amount
        l = self.loss_amount
        # Welle-M-Patch-KPM-1 (2026-05-05): Asymmetric-Kelly f* = (p*w - q*l) / (w*l)
        return (p * w - q * l) / (w * l)

    def half_kelly(self) -> float:
        """Half-Kelly per Thorp-Empfehlung (NICHT Variante-D-Default).

        Post: returns HALF_KELLY_FACTOR * optimal_fraction()
        """
        return HALF_KELLY_FACTOR * self.optimal_fraction()

    def context_adaptive_fraction(self, context: KellyContext) -> float:
        """Variante-D kontext-adaptive Fraction per rules/kpm-sizing.md Tabelle.

        Pre: context ist gueltiger KellyContext.
        Post: returns clamp(fraction * f_opt, 0, 1); 0 bei negativem Edge oder regime-break.
        """
        f_opt = self.optimal_fraction()
        if f_opt <= 0:
            # Negative Edge => kein Bet
            return 0.0
        if context == "regime-break":
            return 0.0
        if context not in CONTEXT_FRACTIONS:
            raise ValueError(f"context_adaptive_fraction: unknown context '{context}'")
        fraction = CONTEXT_FRACTIONS[context]
        return clamp(fraction * f_opt, 0.0, 1.0)

    def expected_growth_rate(self, fraction: float) -> float:
        """Erwartete logarithmische Wachstumsrate bei Fraction f.

        E[log(1 + f*outcome)] = p*log(1 + f*w) + q*log(1 - f*l)

        Pre: 0 <= fraction < 1/loss_amount (sonst Bankrupt => -inf)
        Post: returns Growth-Rate; -inf bei fraction*loss_amount >= 1
        """
        if fraction < 0:
            raise ValueError("expectedGrowthRate: fraction must be >= 0")
        p = self.win_probability
        q = 1 - p
        loss_rel = fraction * self.loss_amount
        if loss_rel >= 1:
            return float("-inf")  # log(0 oder negativ) => Bankrupt
        win_rel = fraction * self.win_amount
        return p * math.log(1 + win_rel) + q * math.log(1 - loss_rel)

    def growth_at_risk_of_ruin(self, fraction: float) -> GrowthRuinResult:
        """Probability-of-Ruin-adjustierte Growth-Rate (Heuristik per TS-Referenz).

        Pre: 0 < fraction < 1/loss_amount
        Post: ruin_risk = clamp(0.5 * (fraction/f_opt)^2, 0, 1);
              bei f_opt <= 0: (growth=0, ruin_risk=1) — exakt wie TS-Referenz.
        """
        growth = self.expected_growth_rate(fraction)
        f_opt = self.optimal_fraction()
        if f_opt <= 0:
            return GrowthRuinResult(growth=0.0, ruin_risk=1.0)
        ratio = fraction / f_opt
        ruin_risk = clamp(RUIN_RISK_COEFFICIENT * ratio * ratio, 0.0, 1.0)
        return GrowthRuinResult(growth=growth, ruin_risk=ruin_risk)
