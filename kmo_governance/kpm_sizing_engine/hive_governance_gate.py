# [CRUX-MK]
"""HIVEGovernanceGate: Shannon-Entropy-basiertes Team-Score-Gate.

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/HIVEGovernanceGate.ts
    (Commit-Stand f4083f4, inkl. Welle-M-Patch-KPM-4 konfigurierbare Schwellen)

Foundation: Shannon (1948) H(X) = -SUM p_i * log_2(p_i).
Per ~/.claude/rules/kpm-sizing.md (Variante-D): HIVE ist Governance-Gate fuer
Leverage-Erhoehung, NICHT direkter Markt-Signal-Trigger.

  - HIVE >= 0.7: Leverage-Erhoehung erlaubt innerhalb Kelly-Limits
  - HIVE 0.5-0.7: Leverage stay flat
  - HIVE < 0.5: Auto-Deleverage

Status: CONDITIONAL. ALPHA-NOT-K0-READY.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Literal, Sequence, Tuple

from .numerics import clamp, sum_values

__all__ = [
    "MarketSignal",
    "LeverageGateResult",
    "HIVECalibrationResult",
    "HIVECalibrationScenario",
    "HIVEGovernanceGate",
    "shannon_from_counts",
    "DEFAULT_LEVERAGE_THRESHOLD",
    "DEFAULT_DELEVERAGE_THRESHOLD",
    "N_SIGNAL_CATEGORIES",
]

MarketSignal = Literal["positive", "negative", "neutral"]

DEFAULT_LEVERAGE_THRESHOLD: float = 0.7  # HIVE-Score, dimensionslos [0,1]
DEFAULT_DELEVERAGE_THRESHOLD: float = 0.5  # HIVE-Score, dimensionslos [0,1]
N_SIGNAL_CATEGORIES: int = 3  # pos / neg / neutral (Diskretisierung auf Vorzeichen)

# Calibration-Konstanten (per TS-Referenz calibrateThresholds)
CALIBRATION_MIN_SAMPLES: int = 20
CALIBRATION_THRESHOLD_START: float = 0.05
CALIBRATION_THRESHOLD_END: float = 0.95
CALIBRATION_THRESHOLD_STEP: float = 0.05
CALIBRATION_DELEVERAGE_RATIO: float = 0.7  # deleverage ~ 0.7 * leverage (Heuristik)
CALIBRATION_CI_SPREAD: float = 0.1


@dataclass(frozen=True)
class LeverageGateResult:
    allow_leverage: bool
    reason: str
    recommended_action: Literal["increase", "maintain", "deleverage"]


@dataclass(frozen=True)
class HIVECalibrationResult:
    """Welle-M-Patch-KPM-4: Calibration-Result."""

    leverage_threshold: float
    deleverage_threshold: float
    confidence_interval: Tuple[float, float]
    method: Literal["roc-optimal", "youden-index", "fallback-default"]
    fallback_used: bool
    sample_size: int


@dataclass(frozen=True)
class HIVECalibrationScenario:
    """Welle-M-Patch-KPM-4: Historical-Scenario fuer Calibration."""

    period: str  # '2008' | '2020' | '2022' | frei
    team_signals: Sequence[Sequence[float]]
    actual_outcome: Literal["good", "neutral", "bad"]


class HIVEGovernanceGate:
    """Berechnet Shannon-Team-Entropy auf Vector-Signals.

    team_signals: 2D-Sequenz; jede Zeile ein Team-Mitglied, jede Spalte ein
    Signal (>0 positiv, <0 negativ, ==0 neutral). Wird zu Verteilung diskretisiert.

    Pre: len(team_signals) >= 1, alle Zeilen gleich lang, alle Werte endlich.
    """

    def __init__(self, team_signals: Sequence[Sequence[float]]) -> None:
        if len(team_signals) < 1:
            raise ValueError("HIVEGovernanceGate: need at least 1 team signal row")
        cols = len(team_signals[0])
        if cols < 1:
            raise ValueError("HIVEGovernanceGate: signal-vector must have >= 1 column")
        for row in team_signals:
            if len(row) != cols:
                raise ValueError("HIVEGovernanceGate: all rows must have equal length")
            for v in row:
                if not math.isfinite(v):
                    raise ValueError("HIVEGovernanceGate: all values must be finite")
        self.team_signals: List[List[float]] = [list(r) for r in team_signals]
        # Default-Schwellen 0.5/0.7 (Welle-M-Patch-KPM-4: konfigurierbar)
        self._leverage_threshold = DEFAULT_LEVERAGE_THRESHOLD
        self._deleverage_threshold = DEFAULT_DELEVERAGE_THRESHOLD

    def set_thresholds(self, leverage: float, deleverage: float) -> None:
        """Konfigurierbare Schwellen. Pre: 0 < deleverage < leverage < 1."""
        if deleverage <= 0 or deleverage >= 1:
            raise ValueError("setThresholds: deleverage must be in (0, 1)")
        if leverage <= 0 or leverage >= 1:
            raise ValueError("setThresholds: leverage must be in (0, 1)")
        if deleverage >= leverage:
            raise ValueError("setThresholds: deleverage must be < leverage")
        self._leverage_threshold = leverage
        self._deleverage_threshold = deleverage

    def get_thresholds(self) -> Dict[str, float]:
        return {
            "leverage": self._leverage_threshold,
            "deleverage": self._deleverage_threshold,
        }

    def shannon_entropy(self) -> float:
        """Shannon-Entropy auf flachen Team-Signals (diskretisiert auf Vorzeichen).

        Post: H = -SUM p_i * log_2(p_i); 0 bei Konzentration auf 1 Kategorie.
        """
        pos = 0
        neg = 0
        neu = 0
        for row in self.team_signals:
            for v in row:
                if v > 0:
                    pos += 1
                elif v < 0:
                    neg += 1
                else:
                    neu += 1
        total = pos + neg + neu
        if total == 0:
            return 0.0
        counts = [c for c in (pos, neg, neu) if c > 0]
        h = 0.0
        for c in counts:
            p = c / total
            h -= p * math.log2(p)
        return h

    def normalized_hive(self) -> float:
        """Normalisierter HIVE-Score in [0, 1]: H / log_2(3)."""
        h = self.shannon_entropy()
        h_max = math.log2(N_SIGNAL_CATEGORIES)
        if h_max == 0:
            return 0.0
        return clamp(h / h_max, 0.0, 1.0)

    def leverage_gate(self, current_hive: float, market_signal: MarketSignal) -> LeverageGateResult:
        """Leverage-Gate per rules/kpm-sizing.md Variante-D.

        Pre: 0 <= current_hive <= 1
        Post: recommended_action in {'increase','maintain','deleverage'};
              Markt-Signal 'negative' blockt increase auch bei HIVE >= leverage.
        """
        if current_hive < 0 or current_hive > 1:
            raise ValueError("leverageGate: currentHIVE must be in [0, 1]")
        if current_hive < self._deleverage_threshold:
            return LeverageGateResult(
                allow_leverage=False,
                reason=(
                    f"HIVE {current_hive:.2f} < {self._deleverage_threshold:.2f} "
                    "-> auto-Deleverage-Trigger"
                ),
                recommended_action="deleverage",
            )
        if current_hive < self._leverage_threshold:
            return LeverageGateResult(
                allow_leverage=False,
                reason=(
                    f"HIVE {current_hive:.2f} in [{self._deleverage_threshold:.2f}, "
                    f"{self._leverage_threshold:.2f}) -> keine Leverage-Erhoehung, "
                    "Status-quo halten"
                ),
                recommended_action="maintain",
            )
        # HIVE >= leverage_threshold
        if market_signal == "negative":
            return LeverageGateResult(
                allow_leverage=False,
                reason=(
                    f"HIVE {current_hive:.2f} >= {self._leverage_threshold:.2f} "
                    "ABER marketSignal=negative -> Erhoehung gegen Markt nicht ratsam"
                ),
                recommended_action="maintain",
            )
        return LeverageGateResult(
            allow_leverage=True,
            reason=(
                f"HIVE {current_hive:.2f} >= {self._leverage_threshold:.2f} "
                f"+ marketSignal={market_signal} -> "
                "Leverage-Erhoehung innerhalb Kelly-Limits erlaubt"
            ),
            recommended_action="increase",
        )

    @staticmethod
    def calibrate_thresholds(
        scenarios: Sequence[HIVECalibrationScenario],
    ) -> HIVECalibrationResult:
        """Welle-M-Patch-KPM-4: empirische Schwellen-Kalibrierung via ROC + Youden-Index.

        Pre: len(scenarios) >= 1
        Post: fallback_used=True (Default 0.7/0.5) wenn n < CALIBRATION_MIN_SAMPLES.
        """
        n = len(scenarios)

        if n < CALIBRATION_MIN_SAMPLES:
            return HIVECalibrationResult(
                leverage_threshold=DEFAULT_LEVERAGE_THRESHOLD,
                deleverage_threshold=DEFAULT_DELEVERAGE_THRESHOLD,
                confidence_interval=(0.5, 0.9),
                method="fallback-default",
                fallback_used=True,
                sample_size=n,
            )

        # HIVE-Score pro Szenario
        data_points: List[Tuple[float, str]] = []
        for scen in scenarios:
            gate = HIVEGovernanceGate(scen.team_signals)
            data_points.append((gate.normalized_hive(), scen.actual_outcome))

        # ROC: Thresholds 0.05..0.95, optimaler Youden-Index
        # (Float-Akkumulation exakt wie TS-Referenz `for (let t=0.05; t<=0.95; t+=0.05)`)
        best_leverage_t = DEFAULT_LEVERAGE_THRESHOLD
        best_youden = float("-inf")
        thresholds: List[float] = []
        t = CALIBRATION_THRESHOLD_START
        while t <= CALIBRATION_THRESHOLD_END:
            thresholds.append(t)
            t += CALIBRATION_THRESHOLD_STEP

        for t in thresholds:
            # positive prediction = HIVE >= t; actual positive = outcome 'good'
            tp = 0
            fp = 0
            fn = 0
            tn = 0
            for hive, outcome in data_points:
                predicted = hive >= t
                actual = outcome == "good"
                if predicted and actual:
                    tp += 1
                elif predicted and not actual:
                    fp += 1
                elif not predicted and actual:
                    fn += 1
                else:
                    tn += 1
            sensitivity = tp / (tp + fn) if tp + fn > 0 else 0.0
            specificity = tn / (tn + fp) if tn + fp > 0 else 0.0
            youden = sensitivity + specificity - 1
            if youden > best_youden:
                best_youden = youden
                best_leverage_t = t

        # Deleverage-Threshold: ~0.7 * leverage (Heuristik per TS-Referenz)
        best_deleverage_t = best_leverage_t * CALIBRATION_DELEVERAGE_RATIO
        best_deleverage_t = clamp(best_deleverage_t, 0.05, best_leverage_t - 0.05)

        ci_low = clamp(best_leverage_t - CALIBRATION_CI_SPREAD, 0.05, 0.95)
        ci_high = clamp(best_leverage_t + CALIBRATION_CI_SPREAD, 0.05, 0.95)

        return HIVECalibrationResult(
            leverage_threshold=best_leverage_t,
            deleverage_threshold=best_deleverage_t,
            confidence_interval=(ci_low, ci_high),
            method="youden-index",
            fallback_used=False,
            sample_size=n,
        )

    def snapshot(self) -> Dict[str, object]:
        """Statistik-Snapshot fuer Dashboard."""
        return {
            "team_size": len(self.team_signals),
            "signal_dimensions": len(self.team_signals[0]),
            "raw_shannon": self.shannon_entropy(),
            "normalized_hive": self.normalized_hive(),
            "leverage_threshold": self._leverage_threshold,
            "deleverage_threshold": self._deleverage_threshold,
        }


def shannon_from_counts(counts: Sequence[float]) -> float:
    """Shannon-Entropy direkt aus einer flachen Verteilung.

    Pre: len(counts) >= 1, alle counts >= 0, sum > 0
    """
    total = sum_values(counts)
    if total <= 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h
