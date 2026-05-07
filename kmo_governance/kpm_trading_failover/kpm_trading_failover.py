# [CRUX-MK]
"""KPM-Trading-Failover (Welle-23 Phase-16 Bio-Pattern-Lift).

Bio-Pattern-Lift von kmo_governance.failover_router (Welle-19, Hotel-Domain)
in KPM-Trading-Domain. Active-Standby-Failover fuer Trading-Strategien:
Bei N unprofitablen Trades der primary-Strategie wird auf konservativere
standby-Strategie umgeschaltet, bis manueller Recovery promote ausgeloest wird.

Pattern-Isomorphie:
- node_id        -> strategy_id
- record_health  -> record_trade_outcome
- HEALTHY/DOWN   -> profitabel/unprofitabel-Streak
- failover       -> Switch zu konservativerer Kelly-Variante
- promote        -> Zurueck zu aggressiver Kelly-Variante

Stdlib only (threading, time, dataclasses, enum). Pattern-Demo, no real money.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum


# Kelly-Fraction Constraint (vgl. rules/kpm-sizing.md Variante-D)
# Wertebereich: [0, 0.5] da Half-Kelly als Praxis-Obergrenze gilt
KELLY_MIN: float = 0.0
KELLY_MAX: float = 0.5

# Default Kelly-Fractions fuer Strategie-Tier (graduelle Reduktion)
DEFAULT_KELLY_PRIMARY: float = 0.4
DEFAULT_KELLY_STANDBY_FIRST: float = 0.3
DEFAULT_KELLY_STANDBY_SECOND: float = 0.2


class StrategyStatus(str, Enum):
    """Health-Status einer Trading-Strategie."""

    HEALTHY = "healthy"      # Strategie liefert Profit oder reset state
    DEGRADED = "degraded"    # 1-2 unprofitable Trades, noch nicht ausgemustert
    DOWN = "down"            # >= health_threshold unprofitable Trades in Folge


class FailoverState(str, Enum):
    """Globaler Failover-State des Trading-Systems."""

    PRIMARY = "primary"            # Aggressive Strategie aktiv
    FAILED_OVER = "failed_over"    # Konservative standby-Strategie aktiv
    RECOVERING = "recovering"      # Primary wieder healthy, manuelle Promotion benoetigt


@dataclass(frozen=True)
class TradingDecision:
    """Routing-Entscheidung fuer aktive Trading-Strategie.

    Frozen dataclass: Audit-Trail-Eintraege sind immutable.
    """

    active_strategy_id: str
    state: FailoverState
    reason: str
    timestamp: float
    expected_kelly_fraction: float


class KPMTradingFailover:
    """Active-Standby-Failover-Router fuer KPM-Trading-Strategien.

    Pre-Conditions:
    - primary_strategy_id non-empty
    - standby_strategy_ids non-empty (mindestens 1)
    - health_threshold > 0
    - kelly_per_strategy values in [KELLY_MIN, KELLY_MAX] = [0, 0.5]

    Post-Conditions:
    - thread-safe (RLock)
    - Auto-Failover bei primary-DOWN auf erste healthy standby
    - Manual Recovery via promote_to_primary() (Sicherheit: kein Auto-Recovery)
    - Audit-Trail aller Entscheidungen via get_decisions()
    """

    def __init__(
        self,
        primary_strategy_id: str,
        standby_strategy_ids: list[str],
        health_threshold: int = 3,
        kelly_per_strategy: dict[str, float] | None = None,
    ) -> None:
        if not primary_strategy_id:
            raise ValueError("primary_strategy_id required")
        if not standby_strategy_ids:
            raise ValueError("at least 1 standby_strategy required")
        if health_threshold <= 0:
            raise ValueError("health_threshold must be > 0")

        self.primary_strategy_id = primary_strategy_id
        self.standby_strategy_ids = list(standby_strategy_ids)
        self.health_threshold = int(health_threshold)

        # Kelly-Fraction Setup (graduelle Reduktion fuer standbys)
        self.kelly_per_strategy = self._build_kelly_map(
            primary_strategy_id, standby_strategy_ids, kelly_per_strategy
        )
        self._validate_kelly_fractions()

        # Status-State pro Strategie
        self._strategy_status: dict[str, StrategyStatus] = {
            primary_strategy_id: StrategyStatus.HEALTHY
        }
        for s in standby_strategy_ids:
            self._strategy_status[s] = StrategyStatus.HEALTHY

        # Loss-Counter pro Strategie (consecutive unprofitable trades)
        self._loss_counts: dict[str, int] = {primary_strategy_id: 0}
        for s in standby_strategy_ids:
            self._loss_counts[s] = 0

        # Globaler State
        self._state = FailoverState.PRIMARY
        self._active_strategy = primary_strategy_id
        self._decisions: list[TradingDecision] = []
        self._lock = threading.RLock()

    @staticmethod
    def _build_kelly_map(
        primary_id: str,
        standby_ids: list[str],
        override: dict[str, float] | None,
    ) -> dict[str, float]:
        """Build Kelly-Fraction-Map: defaults + optional overrides."""
        kelly_map: dict[str, float] = {primary_id: DEFAULT_KELLY_PRIMARY}
        for idx, s in enumerate(standby_ids):
            if idx == 0:
                kelly_map[s] = DEFAULT_KELLY_STANDBY_FIRST
            elif idx == 1:
                kelly_map[s] = DEFAULT_KELLY_STANDBY_SECOND
            else:
                # Weitere standbys: weiter reduziert
                kelly_map[s] = max(KELLY_MIN, DEFAULT_KELLY_STANDBY_SECOND - 0.05 * (idx - 1))

        if override is not None:
            for sid, frac in override.items():
                kelly_map[sid] = frac
        return kelly_map

    def _validate_kelly_fractions(self) -> None:
        """Pre-Condition: kelly fractions in [KELLY_MIN, KELLY_MAX]."""
        for sid, frac in self.kelly_per_strategy.items():
            if not (KELLY_MIN <= frac <= KELLY_MAX):
                raise ValueError(
                    f"kelly_fraction for {sid} = {frac} out of range [{KELLY_MIN}, {KELLY_MAX}]"
                )

    @property
    def state(self) -> FailoverState:
        with self._lock:
            return self._state

    @property
    def active_strategy(self) -> str:
        with self._lock:
            return self._active_strategy

    def record_trade_outcome(self, strategy_id: str, profitable: bool) -> None:
        """Record das Outcome eines Trades fuer eine Strategie.

        Pre: strategy_id is known
        Post: status updated; loss_count incremented oder reset
        """
        with self._lock:
            if strategy_id not in self._strategy_status:
                raise ValueError(f"unknown strategy_id: {strategy_id}")
            if profitable:
                # Profit -> Reset loss-counter, status -> HEALTHY
                self._loss_counts[strategy_id] = 0
                if self._strategy_status[strategy_id] != StrategyStatus.HEALTHY:
                    self._strategy_status[strategy_id] = StrategyStatus.HEALTHY
            else:
                # Loss -> increment counter, escalate status
                self._loss_counts[strategy_id] += 1
                if self._loss_counts[strategy_id] >= self.health_threshold:
                    self._strategy_status[strategy_id] = StrategyStatus.DOWN
                else:
                    self._strategy_status[strategy_id] = StrategyStatus.DEGRADED

    def route(self) -> TradingDecision:
        """Decide active strategy based on health.

        Post: TradingDecision in audit-trail; _state und _active_strategy aktualisiert.
        """
        with self._lock:
            primary_status = self._strategy_status[self.primary_strategy_id]

            # Primary DOWN -> Failover zu erster healthy standby
            if primary_status == StrategyStatus.DOWN:
                for standby in self.standby_strategy_ids:
                    if self._strategy_status[standby] == StrategyStatus.HEALTHY:
                        self._active_strategy = standby
                        self._state = FailoverState.FAILED_OVER
                        decision = TradingDecision(
                            active_strategy_id=standby,
                            state=FailoverState.FAILED_OVER,
                            reason=(
                                f"primary {self.primary_strategy_id} DOWN "
                                f"(loss-streak >= {self.health_threshold}), "
                                f"failover to conservative {standby}"
                            ),
                            timestamp=time.time(),
                            expected_kelly_fraction=self.kelly_per_strategy[standby],
                        )
                        self._decisions.append(decision)
                        return decision
                # Alle standbys auch down -> all-down fallback
                decision = TradingDecision(
                    active_strategy_id=self.primary_strategy_id,
                    state=self._state,
                    reason="all strategies DOWN, route-to-primary as fallback (high risk)",
                    timestamp=time.time(),
                    expected_kelly_fraction=self.kelly_per_strategy[self.primary_strategy_id],
                )
                self._decisions.append(decision)
                return decision

            # Primary OK und vorher Failover -> RECOVERING (manuelle Promotion benoetigt)
            if (
                self._state == FailoverState.FAILED_OVER
                and primary_status == StrategyStatus.HEALTHY
            ):
                self._state = FailoverState.RECOVERING
                decision = TradingDecision(
                    active_strategy_id=self._active_strategy,
                    state=FailoverState.RECOVERING,
                    reason=(
                        f"primary {self.primary_strategy_id} recovered, "
                        f"in RECOVERING state (manual promote_to_primary needed for K_0-safety)"
                    ),
                    timestamp=time.time(),
                    expected_kelly_fraction=self.kelly_per_strategy[self._active_strategy],
                )
                self._decisions.append(decision)
                return decision

            # Primary healthy, normal-state
            decision = TradingDecision(
                active_strategy_id=self.primary_strategy_id,
                state=FailoverState.PRIMARY,
                reason=f"primary {self.primary_strategy_id} healthy, aggressive Kelly active",
                timestamp=time.time(),
                expected_kelly_fraction=self.kelly_per_strategy[self.primary_strategy_id],
            )
            self._decisions.append(decision)
            self._active_strategy = self.primary_strategy_id
            return decision

    def promote_to_primary(self) -> TradingDecision:
        """Manuelle Promotion zurueck zur primary Strategie.

        Pre: primary_strategy_id muss HEALTHY sein
        Post: state -> PRIMARY, active_strategy -> primary

        Sicherheit: Kein Auto-Recovery (K_0-Schutz). Phronesis-Pflicht.
        """
        with self._lock:
            if self._strategy_status[self.primary_strategy_id] != StrategyStatus.HEALTHY:
                raise RuntimeError(
                    f"primary {self.primary_strategy_id} not HEALTHY "
                    f"(status={self._strategy_status[self.primary_strategy_id]}), "
                    f"cannot promote"
                )
            self._state = FailoverState.PRIMARY
            self._active_strategy = self.primary_strategy_id
            decision = TradingDecision(
                active_strategy_id=self.primary_strategy_id,
                state=FailoverState.PRIMARY,
                reason="manual promote-to-primary (Phronesis approved, aggressive Kelly resumed)",
                timestamp=time.time(),
                expected_kelly_fraction=self.kelly_per_strategy[self.primary_strategy_id],
            )
            self._decisions.append(decision)
            return decision

    def get_strategy_statuses(self) -> dict[str, StrategyStatus]:
        """Snapshot aller Strategy-Statuses."""
        with self._lock:
            return dict(self._strategy_status)

    def get_decisions(self) -> list[TradingDecision]:
        """Audit-Trail aller bisherigen Routing-Entscheidungen."""
        with self._lock:
            return list(self._decisions)


# CRUX-MK
