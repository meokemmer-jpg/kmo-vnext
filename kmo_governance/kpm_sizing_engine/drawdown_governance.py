# [CRUX-MK]
"""DrawdownGovernance: 4-Stufen-Eskalation per ~/.claude/rules/kpm-sizing.md.

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/DrawdownGovernance.ts
    (Commit-Stand f4083f4, inkl. Welle-M-Patch-KPM-5 Dynamic-Vol + Cooldown + Override-Log)

KPM-Variante-D-Cap-Cascade:

| Drawdown   | Level          | Action                                  | Multiplier |
|------------|----------------|-----------------------------------------|------------|
| <15%       | normal         | Trade as designed                       | 1.0        |
| 15% - <20% | soft-brake     | Position-Reduktion 50%, Review-Pflicht  | 0.5        |
| 20% - <25% | hard-cap       | Trading-Pause, Martin-Phronesis-Gate    | 0.0        |
| >=25%      | absolute-no-go | Harter Stop, Familien-Notfall-Protokoll | 0.0        |

Cliff-Effect-Schutz: 4 Stufen statt binaer (per rules/graduelle-eskalation.md).
Status: CONDITIONAL. ALPHA-NOT-K0-READY.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

__all__ = [
    "DrawdownLevel",
    "DrawdownThresholds",
    "CapResult",
    "DynamicCapResult",
    "OverrideLogEntry",
    "CooldownStatus",
    "PeakRecoveryStatus",
    "DEFAULT_THRESHOLDS",
    "DrawdownGovernance",
    "MS_PER_DAY",
    "DEFAULT_COOLDOWN_MS",
    "VOL_ADJUSTMENT_FACTOR_MIN",
    "VOL_ADJUSTMENT_FACTOR_MAX",
    "SOFT_BRAKE_POSITION_MULTIPLIER",
]

DrawdownLevel = Literal["normal", "soft-brake", "hard-cap", "absolute-no-go", "cooldown"]

MS_PER_DAY: int = 86_400_000  # Millisekunden pro Tag
DEFAULT_COOLDOWN_MS: int = 5 * MS_PER_DAY  # 5 Tage Default-Cooldown (per TS-Referenz)
VOL_ADJUSTMENT_FACTOR_MIN: float = 0.7  # dimensionslos, per Roncalli (2013) Adaptive-Risk
VOL_ADJUSTMENT_FACTOR_MAX: float = 1.3  # dimensionslos
SOFT_BRAKE_POSITION_MULTIPLIER: float = 0.5  # Position-Reduktion 50%


@dataclass(frozen=True)
class DrawdownThresholds:
    """Schwellen dezimal (0.15 = 15%). Pre: 0 < soft_brake < hard_cap < absolute_no_go < 1."""

    soft_brake: float = 0.15
    hard_cap: float = 0.20
    absolute_no_go: float = 0.25


DEFAULT_THRESHOLDS = DrawdownThresholds(soft_brake=0.15, hard_cap=0.20, absolute_no_go=0.25)


@dataclass(frozen=True)
class CapResult:
    level: DrawdownLevel
    action: str
    position_multiplier: float


@dataclass(frozen=True)
class DynamicCapResult:
    """Welle-M-Patch-KPM-5: Dynamic-Cap-Result mit Adjusted-Thresholds + Cooldown."""

    level: DrawdownLevel
    position_multiplier: float
    action: str
    adjusted_thresholds: DrawdownThresholds
    cooldown_remaining_ms: Optional[float] = None
    override_logged: Optional[bool] = None
    volatility_factor: Optional[float] = None


@dataclass(frozen=True)
class OverrideLogEntry:
    user: str
    reason: str
    timestamp: float
    drawdown: float
    level: DrawdownLevel


@dataclass(frozen=True)
class CooldownStatus:
    in_cooldown: bool
    remaining_ms: float


@dataclass(frozen=True)
class PeakRecoveryStatus:
    recovered: bool
    periods_since_recovery: int


class DrawdownGovernance:
    """Verwaltet 4-Stufen-Eskalation auf Drawdown-Basis.

    Pre:
      - initial_equity > 0
      - thresholds: 0 < soft_brake < hard_cap < absolute_no_go < 1

    Invariants:
      - peak ist immer >= jeder bisherige Equity-Wert
      - current_drawdown() in [0, 1]
    """

    def __init__(
        self,
        initial_equity: float,
        thresholds: DrawdownThresholds = DEFAULT_THRESHOLDS,
    ) -> None:
        if initial_equity <= 0:
            raise ValueError("DrawdownGovernance: initialEquity must be > 0")
        if (
            thresholds.soft_brake <= 0
            or thresholds.hard_cap <= thresholds.soft_brake
            or thresholds.absolute_no_go <= thresholds.hard_cap
            or thresholds.absolute_no_go >= 1
        ):
            raise ValueError(
                "DrawdownGovernance: thresholds must satisfy "
                "0 < softBrake < hardCap < absoluteNoGo < 1"
            )
        self._peak = initial_equity
        self._current = initial_equity
        self.thresholds = thresholds
        self._history: List[float] = [initial_equity]
        self._peak_recovery_periods = 0
        # Welle-M-Patch-KPM-5: Cooldown-State
        self._cooldown_end_timestamp: Optional[float] = None
        self._override_log: List[OverrideLogEntry] = []

    @staticmethod
    def _now_ms() -> float:
        """Aktuelle Zeit in ms (TS: Date.now()). In Tests monkeypatchbar."""
        return time.time() * 1000.0

    def current_drawdown(self) -> float:
        """Aktueller Drawdown (Peak-to-Current). 0 wenn current >= peak."""
        if self._peak <= 0:
            return 0.0
        if self._current >= self._peak:
            return 0.0
        return (self._peak - self._current) / self._peak

    def record_equity(self, value: float) -> None:
        """Append neuen Equity-Wert; updated Peak und Recovery-Counter.

        Pre: value > 0
        """
        if value <= 0:
            raise ValueError("recordEquity: value must be > 0")
        self._current = value
        self._history.append(value)
        if value > self._peak:
            self._peak = value
            self._peak_recovery_periods = 0  # Peak recovered
        elif value < self._peak:
            self._peak_recovery_periods += 1  # Drawdown aktiv
        else:
            self._peak_recovery_periods = 0  # flat am Top

    def enforce_level(self) -> CapResult:
        """Bestimme aktuellen Eskalations-Level (statische Schwellen)."""
        dd = self.current_drawdown()
        t = self.thresholds

        if dd >= t.absolute_no_go:
            return CapResult(
                level="absolute-no-go",
                action=(
                    f"Drawdown {dd * 100:.1f}% >= {t.absolute_no_go * 100:.0f}% -> "
                    "Harter Stop, Familien-Notfall-Protokoll"
                ),
                position_multiplier=0.0,
            )
        if dd >= t.hard_cap:
            return CapResult(
                level="hard-cap",
                action=(
                    f"Drawdown {dd * 100:.1f}% >= {t.hard_cap * 100:.0f}% -> "
                    "Trading-Pause, Martin-Phronesis-Gate"
                ),
                position_multiplier=0.0,
            )
        if dd >= t.soft_brake:
            return CapResult(
                level="soft-brake",
                action=(
                    f"Drawdown {dd * 100:.1f}% >= {t.soft_brake * 100:.0f}% -> "
                    "Position-Reduktion 50%, Review-Pflicht"
                ),
                position_multiplier=SOFT_BRAKE_POSITION_MULTIPLIER,
            )
        return CapResult(level="normal", action="Trading as designed", position_multiplier=1.0)

    def enforce_level_dynamic(
        self,
        current_volatility: Optional[float] = None,
        baseline_volatility: Optional[float] = None,
        cooldown_periods_ms: Optional[float] = None,
        override_context: Optional[Dict[str, object]] = None,
    ) -> DynamicCapResult:
        """Welle-M-Patch-KPM-5: Dynamic-Volatility-Adjusted Eskalation.

        adjustment_factor = clamp(1/vol_ratio, 0.7, 1.3)
        adjusted_threshold = base_threshold * adjustment_factor

        Pre: current_volatility, baseline_volatility > 0 (wenn gegeben);
             cooldown_periods_ms >= 0 (default 5 Tage).
        """
        t = self.thresholds
        dd = self.current_drawdown()
        now = self._now_ms()

        # Volatility-Adjustment (TS: options.currentVolatility ?? 1)
        current_vol = current_volatility if current_volatility is not None else 1.0
        baseline_vol = baseline_volatility if baseline_volatility is not None else 1.0
        if current_vol <= 0 or baseline_vol <= 0:
            raise ValueError("enforceLevelDynamic: volatilities must be > 0")
        vol_ratio = current_vol / baseline_vol
        adjustment_factor = max(
            VOL_ADJUSTMENT_FACTOR_MIN, min(VOL_ADJUSTMENT_FACTOR_MAX, 1 / vol_ratio)
        )

        adjusted = DrawdownThresholds(
            soft_brake=t.soft_brake * adjustment_factor,
            hard_cap=t.hard_cap * adjustment_factor,
            absolute_no_go=t.absolute_no_go * adjustment_factor,
        )

        # Cooldown-Check (hoechste Prioritaet)
        if self._cooldown_end_timestamp is not None and now < self._cooldown_end_timestamp:
            return DynamicCapResult(
                level="cooldown",
                position_multiplier=0.0,
                action="Cooldown active, no new positions allowed",
                adjusted_thresholds=adjusted,
                cooldown_remaining_ms=self._cooldown_end_timestamp - now,
                volatility_factor=adjustment_factor,
            )

        # Cooldown expired: State loeschen
        if self._cooldown_end_timestamp is not None and now >= self._cooldown_end_timestamp:
            self._cooldown_end_timestamp = None

        # Override-Logging
        override_logged = False
        if override_context is not None:
            determined_level = self._determine_level(dd, adjusted)
            self._override_log.append(
                OverrideLogEntry(
                    user=str(override_context["user"]),
                    reason=str(override_context["reason"]),
                    timestamp=float(override_context["timestamp"]),  # type: ignore[arg-type]
                    drawdown=dd,
                    level=determined_level,
                )
            )
            override_logged = True

        # Level mit adjusted Thresholds
        if dd >= adjusted.absolute_no_go:
            return DynamicCapResult(
                level="absolute-no-go",
                position_multiplier=0.0,
                action=(
                    f"Drawdown {dd * 100:.1f}% >= {adjusted.absolute_no_go * 100:.1f}% (vol-adj) -> "
                    "Harter Stop, Familien-Notfall-Protokoll"
                ),
                adjusted_thresholds=adjusted,
                override_logged=override_logged,
                volatility_factor=adjustment_factor,
            )
        if dd >= adjusted.hard_cap:
            # Cooldown triggern
            cd_ms = cooldown_periods_ms if cooldown_periods_ms is not None else DEFAULT_COOLDOWN_MS
            self._cooldown_end_timestamp = now + cd_ms
            return DynamicCapResult(
                level="hard-cap",
                position_multiplier=0.0,
                action=(
                    f"Drawdown {dd * 100:.1f}% >= {adjusted.hard_cap * 100:.1f}% (vol-adj) -> "
                    f"Trading-Pause + Martin-Phronesis-Gate + "
                    f"{int(math.floor(cd_ms / MS_PER_DAY))}-day-cooldown"
                ),
                adjusted_thresholds=adjusted,
                cooldown_remaining_ms=cd_ms,
                override_logged=override_logged,
                volatility_factor=adjustment_factor,
            )
        if dd >= adjusted.soft_brake:
            return DynamicCapResult(
                level="soft-brake",
                position_multiplier=SOFT_BRAKE_POSITION_MULTIPLIER,
                action=(
                    f"Drawdown {dd * 100:.1f}% >= {adjusted.soft_brake * 100:.1f}% (vol-adj) -> "
                    "Position-Reduktion 50%, Review-Pflicht"
                ),
                adjusted_thresholds=adjusted,
                override_logged=override_logged,
                volatility_factor=adjustment_factor,
            )
        return DynamicCapResult(
            level="normal",
            position_multiplier=1.0,
            action="Normal trading (vol-adj OK)",
            adjusted_thresholds=adjusted,
            override_logged=override_logged,
            volatility_factor=adjustment_factor,
        )

    @staticmethod
    def _determine_level(dd: float, t: DrawdownThresholds) -> DrawdownLevel:
        """Welle-M-Patch-KPM-5: Level-Bestimmung bei gegebenen Thresholds."""
        if dd >= t.absolute_no_go:
            return "absolute-no-go"
        if dd >= t.hard_cap:
            return "hard-cap"
        if dd >= t.soft_brake:
            return "soft-brake"
        return "normal"

    def get_override_log(self) -> List[OverrideLogEntry]:
        """Override-Log abrufen (Kopie, read-only-Semantik)."""
        return list(self._override_log)

    def is_in_cooldown(self) -> CooldownStatus:
        """Cooldown-Status pruefen."""
        if self._cooldown_end_timestamp is None:
            return CooldownStatus(in_cooldown=False, remaining_ms=0.0)
        now = self._now_ms()
        if now >= self._cooldown_end_timestamp:
            return CooldownStatus(in_cooldown=False, remaining_ms=0.0)
        return CooldownStatus(in_cooldown=True, remaining_ms=self._cooldown_end_timestamp - now)

    def clear_cooldown(self, override_context: Dict[str, str]) -> None:
        """Manueller Cooldown-Clear (Martin-Phronesis-Override, Pflicht-Logging)."""
        if self._cooldown_end_timestamp is not None:
            self._override_log.append(
                OverrideLogEntry(
                    user=str(override_context["user"]),
                    reason=str(override_context["reason"]),
                    timestamp=self._now_ms(),
                    drawdown=self.current_drawdown(),
                    level="cooldown",
                )
            )
            self._cooldown_end_timestamp = None

    def peak_recovery(self) -> PeakRecoveryStatus:
        """Recovery-Status seit letztem Peak."""
        return PeakRecoveryStatus(
            recovered=self._current >= self._peak,
            periods_since_recovery=self._peak_recovery_periods,
        )

    def snapshot(self) -> Dict[str, object]:
        """Read-only-Snapshot fuer Logging/Dashboard."""
        cooldown_status = self.is_in_cooldown()
        return {
            "peak": self._peak,
            "current": self._current,
            "drawdown": self.current_drawdown(),
            "level": self.enforce_level().level,
            "history_len": len(self._history),
            "cooldown_active": cooldown_status.in_cooldown,
            "override_log_size": len(self._override_log),
        }
