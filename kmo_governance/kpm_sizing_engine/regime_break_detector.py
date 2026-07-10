# [CRUX-MK]
"""RegimeBreakDetector: Markt-Regime-Wechsel-Erkennung.

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/RegimeBreakDetector.ts
    (Commit-Stand f4083f4)

Foundation: Hamilton (1989) Markov-Switching, Chow-Test (1960), CUSUM (Page 1954).
Vereinfachte Pilot-Implementation: Rolling-Window-Variance-Ratio + Forecast-Dispersion
+ Edge-Decay-Alert (per Variante-D §Regimebruch-Stress-Test).

KPM-Variante-D-Trigger: Regimebruch -> Kelly-Fraction = 0 (pausieren).
Status: CONDITIONAL. ALPHA-NOT-K0-READY.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.

Paritaets-Hinweis: Die TS-Referenz iteriert das Rolling-Window mit
`start += Math.max(1, halfW / 4)` — der Schritt kann ein FLOAT sein und
Array.slice() trunkiert Float-Indizes. Dieses Verhalten wird hier exakt
nachgebildet (int()-Trunkierung, Float-Akkumulation des Starts).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence

from .numerics import mean, std_dev, variance

__all__ = [
    "RegimeBreakResult",
    "DispersionResult",
    "EdgeDecayResult",
    "RegimeComponents",
    "CombinedRegimeStatus",
    "RegimeBreakDetector",
    "MIN_RETURN_OBSERVATIONS",
    "VARIANCE_RATIO_BREAK_THRESHOLD",
    "EDGE_DECAY_CONSECUTIVE_MONTHS",
    "DEFAULT_DISPERSION_THRESHOLD",
]

MIN_RETURN_OBSERVATIONS: int = 30  # statistisches Minimum (Beobachtungen)
MIN_WINDOW: int = 10  # minimale Fenster-Groesse (Beobachtungen)
MIN_HALF_WINDOW_SAMPLES: int = 5  # minimale Samples pro Fenster-Haelfte
VARIANCE_RATIO_BREAK_THRESHOLD: float = 2.0  # Ratio > 2.0 = signifikanter Bruch
CONFIDENCE_RATIO_OFFSET: float = 1.5  # Confidence linear ab ratio=1.5
CONFIDENCE_RATIO_SCALE: float = 3.5  # ... bis ratio=5.0
DEFAULT_DISPERSION_THRESHOLD: float = 0.05  # Forecast-StdDev-Alarm-Schwelle (dezimal)
EDGE_DECAY_CONSECUTIVE_MONTHS: int = 3  # Strategy-Review nach 3 Monaten Decay
HIGH_VOLA_RATIO_THRESHOLD: float = 1.5  # ratio > 1.5 -> high-vola Regime


@dataclass(frozen=True)
class RegimeBreakResult:
    break_detected: bool
    confidence: float  # [0, 1]
    break_date: Optional[float] = None  # Index in returns (TS: number, ggf. float)
    ratio: Optional[float] = None  # variance-ratio (max deviation)


@dataclass(frozen=True)
class DispersionResult:
    dispersion: float  # StdDev ueber Forecasts
    alarm_triggered: bool


@dataclass(frozen=True)
class EdgeDecayResult:
    decay: bool
    consecutive_months: int
    mean_delta: float  # mean(realized - forecast), negativ bei Decay


@dataclass(frozen=True)
class RegimeComponents:
    break_detected: bool
    dispersion_alarm: bool


@dataclass(frozen=True)
class CombinedRegimeStatus:
    regime: Literal["normal", "high-vola", "regime-break"]
    confidence: float
    components: RegimeComponents


class RegimeBreakDetector:
    """Verarbeitet Return-Serie und detektiert Strukturbrueche.

    Pre: len(returns) >= MIN_RETURN_OBSERVATIONS (30)
    """

    def __init__(self, returns: Sequence[float]) -> None:
        if len(returns) < MIN_RETURN_OBSERVATIONS:
            raise ValueError("RegimeBreakDetector: need at least 30 return observations")
        self.returns: List[float] = list(returns)

    def detect_regime_break(self, window: int = 60) -> RegimeBreakResult:
        """Regimebruch via Variance-Ratio-Test ueber Rolling-Window.

        Pre: window >= 10 (wird auf len(returns) gekappt)
        Post: break_detected wenn max-deviation-ratio > 2.0;
              confidence = clamp((ratio - 1.5) / 3.5, 0, 1)
        """
        if window < MIN_WINDOW:
            raise ValueError("detectRegimeBreak: window must be >= 10")
        if window > len(self.returns):
            window = len(self.returns)

        max_ratio = 1.0
        break_idx: Optional[float] = None

        # Fenster ueberlappend durchschieben (Float-Schritt exakt wie TS-Referenz)
        half_w = math.floor(window / 2)
        step = max(1, half_w / 4)  # TS: Math.max(1, halfW / 4) — kann Float sein
        start = 0.0
        while start + window <= len(self.returns):
            # TS Array.slice trunkiert Float-Indizes (ToIntegerOrInfinity)
            pre = self.returns[int(start) : int(start + half_w)]
            post = self.returns[int(start + half_w) : int(start + window)]
            if len(pre) < MIN_HALF_WINDOW_SAMPLES or len(post) < MIN_HALF_WINDOW_SAMPLES:
                start += step
                continue
            v_pre = variance(pre)
            v_post = variance(post)
            if v_pre == 0:
                start += step
                continue
            ratio = v_post / v_pre
            # Max-Abweichung von 1.0 (beide Richtungen)
            dev = max(ratio, 1 / ratio)
            if dev > max_ratio:
                max_ratio = dev
                break_idx = start + half_w
            start += step

        break_detected = max_ratio > VARIANCE_RATIO_BREAK_THRESHOLD
        confidence = min(
            1.0, max(0.0, (max_ratio - CONFIDENCE_RATIO_OFFSET) / CONFIDENCE_RATIO_SCALE)
        )

        if break_detected:
            return RegimeBreakResult(
                break_detected=True,
                break_date=break_idx,
                confidence=confidence,
                ratio=max_ratio,
            )
        return RegimeBreakResult(break_detected=False, confidence=confidence, ratio=max_ratio)

    def forecast_dispersion_monitor(
        self,
        forecasts: Sequence[float],
        threshold: float = DEFAULT_DISPERSION_THRESHOLD,
    ) -> DispersionResult:
        """Forecast-Dispersion: hohe Streuung => Modell-Unsicherheit => Deleverage-Trigger.

        Pre: len(forecasts) >= 2
        """
        if len(forecasts) < 2:
            raise ValueError("forecastDispersionMonitor: need at least 2 forecasts")
        dispersion = std_dev(forecasts)
        return DispersionResult(dispersion=dispersion, alarm_triggered=dispersion > threshold)

    def edge_decay_alert(
        self, realized: Sequence[float], forecast: Sequence[float]
    ) -> EdgeDecayResult:
        """Edge-Decay per rules/kpm-sizing.md: realized < forecast 3 Monate in Folge.

        Pre: len(realized) == len(forecast), len(realized) >= 3
        """
        if len(realized) != len(forecast):
            raise ValueError("edgeDecayAlert: arrays must have equal length")
        if len(realized) < EDGE_DECAY_CONSECUTIVE_MONTHS:
            raise ValueError("edgeDecayAlert: need at least 3 observations")

        # Trailing consecutive Decay-Monate zaehlen
        consecutive = 0
        for i in range(len(realized) - 1, -1, -1):
            if realized[i] < forecast[i]:
                consecutive += 1
            else:
                break

        deltas = [realized[i] - forecast[i] for i in range(len(realized))]
        mean_delta = mean(deltas)

        return EdgeDecayResult(
            decay=consecutive >= EDGE_DECAY_CONSECUTIVE_MONTHS,
            consecutive_months=consecutive,
            mean_delta=mean_delta,
        )

    def combined_regime_status(
        self, forecasts: Optional[Sequence[float]] = None
    ) -> CombinedRegimeStatus:
        """Aggregiert Break + Dispersion zu Regime-Status (Input fuer DecisionEngine)."""
        break_res = self.detect_regime_break()
        dispersion_alarm = False
        if forecasts is not None and len(forecasts) >= 2:
            disp = self.forecast_dispersion_monitor(forecasts)
            dispersion_alarm = disp.alarm_triggered

        if break_res.break_detected:
            return CombinedRegimeStatus(
                regime="regime-break",
                confidence=break_res.confidence,
                components=RegimeComponents(break_detected=True, dispersion_alarm=dispersion_alarm),
            )
        if dispersion_alarm or (
            break_res.ratio is not None and break_res.ratio > HIGH_VOLA_RATIO_THRESHOLD
        ):
            return CombinedRegimeStatus(
                regime="high-vola",
                confidence=0.5 + 0.3 * break_res.confidence + (0.2 if dispersion_alarm else 0.0),
                components=RegimeComponents(
                    break_detected=False, dispersion_alarm=dispersion_alarm
                ),
            )
        return CombinedRegimeStatus(
            regime="normal",
            confidence=1 - break_res.confidence,
            components=RegimeComponents(break_detected=False, dispersion_alarm=dispersion_alarm),
        )
