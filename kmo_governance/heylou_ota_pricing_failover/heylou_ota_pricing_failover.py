# [CRUX-MK]
"""HeyLou-OTA-Pricing-Failover (Welle-35 Phase-28 Bio-Pattern-Lift).

Bio-Pattern-Lift von kmo_governance.failover_router (Welle-19, Hotel-Mock-Domain)
in HeyLou-OTA-Pricing-Domain. Active-Standby-Failover fuer OTA-Pricing-Sources:
Bei N fehlgeschlagenen Booking-Outcomes der primary OTA wird auf konservativere
standby-OTA umgeschaltet, bis manueller Recovery promote ausgeloest wird.

Pattern-Isomorphie:
- node_id            -> ota_source
- record_health      -> record_booking_outcome
- HEALTHY/DOWN       -> successful/failed Booking-Streak
- failover           -> Switch zu Backup-OTA-Source
- promote            -> Zurueck zu primary OTA-Source

Domain-spezifische Erweiterung:
- expected_pricing_freshness_s pro OTA (primary 30s, standby graduiert hoch)
- health_threshold default 5 (statt 3): OTAs sind volatiler als Hotel-Nodes
  (transient API-Errors, Rate-Limits, Booking-Caches), also tolerantere Schwelle.

Stdlib only (threading, time, dataclasses, enum). Pattern-Demo, no real bookings.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum


# Pricing-Freshness Constraint (vgl. HeyLou OTA-Cache-SLA)
# Wertebereich: > 0 (sekunden), realistisch [10, 1800] fuer OTA-Pricing
FRESHNESS_MIN_S: float = 0.0

# Default Pricing-Freshness pro Strategie-Tier (graduelle Erhoehung = Cache-Toleranz)
DEFAULT_FRESHNESS_PRIMARY_S: float = 30.0
DEFAULT_FRESHNESS_STANDBY_FIRST_S: float = 60.0
DEFAULT_FRESHNESS_STANDBY_SECOND_S: float = 300.0

# Default Failover-Threshold: OTAs volatiler als Hotel-Nodes -> 5 statt 3
DEFAULT_HEALTH_THRESHOLD: int = 5


class OTASourceStatus(str, Enum):
    """Health-Status einer OTA-Pricing-Source."""

    HEALTHY = "healthy"      # Booking-Outcomes successful, OTA liefert frische Preise
    DEGRADED = "degraded"    # 1-N-1 fehlgeschlagene Bookings, noch nicht abgeschaltet
    DOWN = "down"            # >= health_threshold fehlgeschlagene Bookings in Folge


class FailoverState(str, Enum):
    """Globaler Failover-State des OTA-Pricing-Routings."""

    PRIMARY = "primary"            # primary OTA-Source aktiv (frische Preise)
    FAILED_OVER = "failed_over"    # standby OTA-Source aktiv (groesseres Cache-Window)
    RECOVERING = "recovering"      # primary wieder healthy, manuelle Promotion benoetigt


@dataclass(frozen=True)
class OTAPricingDecision:
    """Routing-Entscheidung fuer aktive OTA-Pricing-Source.

    Frozen dataclass: Audit-Trail-Eintraege sind immutable.
    """

    target_ota_source: str
    state: FailoverState
    reason: str
    timestamp: float
    expected_pricing_freshness_s: float


class HeyLouOTAPricingFailover:
    """Active-Standby-Failover-Router fuer HeyLou-OTA-Pricing-Sources.

    Pre-Conditions:
    - primary_ota non-empty
    - standby_otas non-empty (mindestens 1)
    - health_threshold > 0
    - freshness_per_ota values >= FRESHNESS_MIN_S = 0

    Post-Conditions:
    - thread-safe (RLock)
    - Auto-Failover bei primary-DOWN auf erste healthy standby
    - Manual Recovery via promote_to_primary() (Q_0-Sicherheit: kein Auto-Recovery)
    - Audit-Trail aller Entscheidungen via get_decisions()
    """

    def __init__(
        self,
        primary_ota: str,
        standby_otas: list[str],
        health_threshold: int = DEFAULT_HEALTH_THRESHOLD,
        freshness_per_ota: dict[str, float] | None = None,
    ) -> None:
        if not primary_ota:
            raise ValueError("primary_ota required")
        if not standby_otas:
            raise ValueError("at least 1 standby_ota required")
        if health_threshold <= 0:
            raise ValueError("health_threshold must be > 0")

        self.primary_ota = primary_ota
        self.standby_otas = list(standby_otas)
        self.health_threshold = int(health_threshold)

        # Pricing-Freshness Setup (graduelle Erhoehung fuer standbys)
        self.freshness_per_ota = self._build_freshness_map(
            primary_ota, standby_otas, freshness_per_ota
        )
        self._validate_freshness_values()

        # Status-State pro OTA-Source
        self._ota_status: dict[str, OTASourceStatus] = {
            primary_ota: OTASourceStatus.HEALTHY
        }
        for s in standby_otas:
            self._ota_status[s] = OTASourceStatus.HEALTHY

        # Fail-Counter pro OTA-Source (consecutive failed bookings)
        self._fail_counts: dict[str, int] = {primary_ota: 0}
        for s in standby_otas:
            self._fail_counts[s] = 0

        # Globaler State
        self._state = FailoverState.PRIMARY
        self._active_ota = primary_ota
        self._decisions: list[OTAPricingDecision] = []
        self._lock = threading.RLock()

    @staticmethod
    def _build_freshness_map(
        primary_ota: str,
        standby_otas: list[str],
        override: dict[str, float] | None,
    ) -> dict[str, float]:
        """Build Pricing-Freshness-Map: defaults (graduiert) + optional overrides."""
        freshness_map: dict[str, float] = {primary_ota: DEFAULT_FRESHNESS_PRIMARY_S}
        for idx, s in enumerate(standby_otas):
            if idx == 0:
                freshness_map[s] = DEFAULT_FRESHNESS_STANDBY_FIRST_S
            elif idx == 1:
                freshness_map[s] = DEFAULT_FRESHNESS_STANDBY_SECOND_S
            else:
                # Weitere standbys: weiter erhoeht (groesseres Cache-Window)
                freshness_map[s] = (
                    DEFAULT_FRESHNESS_STANDBY_SECOND_S + 300.0 * (idx - 1)
                )

        if override is not None:
            for sid, freshness in override.items():
                freshness_map[sid] = freshness
        return freshness_map

    def _validate_freshness_values(self) -> None:
        """Pre-Condition: freshness values >= FRESHNESS_MIN_S = 0."""
        for sid, freshness in self.freshness_per_ota.items():
            if freshness < FRESHNESS_MIN_S:
                raise ValueError(
                    f"freshness for {sid} = {freshness}s out of range "
                    f"(must be >= {FRESHNESS_MIN_S}s)"
                )

    @property
    def state(self) -> FailoverState:
        with self._lock:
            return self._state

    @property
    def active_ota(self) -> str:
        with self._lock:
            return self._active_ota

    def record_booking_outcome(self, ota_source: str, successful: bool) -> None:
        """Record das Outcome eines Booking-Versuchs fuer eine OTA-Source.

        Pre: ota_source is known
        Post: status updated; fail_count incremented oder reset
        """
        with self._lock:
            if ota_source not in self._ota_status:
                raise ValueError(f"unknown ota_source: {ota_source}")
            if successful:
                # Successful booking -> Reset fail-counter, status -> HEALTHY
                self._fail_counts[ota_source] = 0
                if self._ota_status[ota_source] != OTASourceStatus.HEALTHY:
                    self._ota_status[ota_source] = OTASourceStatus.HEALTHY
            else:
                # Failed booking -> increment counter, escalate status
                self._fail_counts[ota_source] += 1
                if self._fail_counts[ota_source] >= self.health_threshold:
                    self._ota_status[ota_source] = OTASourceStatus.DOWN
                else:
                    self._ota_status[ota_source] = OTASourceStatus.DEGRADED

    def route(self) -> OTAPricingDecision:
        """Decide active OTA-Source based on health.

        Post: OTAPricingDecision in audit-trail; _state und _active_ota aktualisiert.
        """
        with self._lock:
            primary_status = self._ota_status[self.primary_ota]

            # Primary DOWN -> Failover zu erster healthy standby
            if primary_status == OTASourceStatus.DOWN:
                for standby in self.standby_otas:
                    if self._ota_status[standby] == OTASourceStatus.HEALTHY:
                        self._active_ota = standby
                        self._state = FailoverState.FAILED_OVER
                        decision = OTAPricingDecision(
                            target_ota_source=standby,
                            state=FailoverState.FAILED_OVER,
                            reason=(
                                f"primary {self.primary_ota} DOWN "
                                f"(failed-booking-streak >= {self.health_threshold}), "
                                f"failover to backup OTA {standby}"
                            ),
                            timestamp=time.time(),
                            expected_pricing_freshness_s=self.freshness_per_ota[standby],
                        )
                        self._decisions.append(decision)
                        return decision
                # Alle standbys auch down -> all-down fallback
                decision = OTAPricingDecision(
                    target_ota_source=self.primary_ota,
                    state=self._state,
                    reason=(
                        "all OTA-sources DOWN, route-to-primary as fallback "
                        "(stale pricing risk: rate-parity violations possible)"
                    ),
                    timestamp=time.time(),
                    expected_pricing_freshness_s=self.freshness_per_ota[self.primary_ota],
                )
                self._decisions.append(decision)
                return decision

            # Primary OK und vorher Failover -> RECOVERING (manuelle Promotion benoetigt)
            if (
                self._state == FailoverState.FAILED_OVER
                and primary_status == OTASourceStatus.HEALTHY
            ):
                self._state = FailoverState.RECOVERING
                decision = OTAPricingDecision(
                    target_ota_source=self._active_ota,
                    state=FailoverState.RECOVERING,
                    reason=(
                        f"primary OTA {self.primary_ota} recovered, "
                        f"in RECOVERING state (manual promote_to_primary needed "
                        f"for Q_0-pricing-stability)"
                    ),
                    timestamp=time.time(),
                    expected_pricing_freshness_s=self.freshness_per_ota[self._active_ota],
                )
                self._decisions.append(decision)
                return decision

            # Primary healthy, normal-state
            decision = OTAPricingDecision(
                target_ota_source=self.primary_ota,
                state=FailoverState.PRIMARY,
                reason=f"primary OTA {self.primary_ota} healthy, fresh pricing active",
                timestamp=time.time(),
                expected_pricing_freshness_s=self.freshness_per_ota[self.primary_ota],
            )
            self._decisions.append(decision)
            self._active_ota = self.primary_ota
            return decision

    def promote_to_primary(self) -> OTAPricingDecision:
        """Manuelle Promotion zurueck zur primary OTA-Source.

        Pre: primary_ota muss HEALTHY sein
        Post: state -> PRIMARY, active_ota -> primary

        Sicherheit: Kein Auto-Recovery (Q_0-pricing-stability-Schutz).
        Verhindert Auto-Switch-Loops bei volatilen Pricing-APIs.
        """
        with self._lock:
            if self._ota_status[self.primary_ota] != OTASourceStatus.HEALTHY:
                raise RuntimeError(
                    f"primary OTA {self.primary_ota} not HEALTHY "
                    f"(status={self._ota_status[self.primary_ota]}), "
                    f"cannot promote"
                )
            self._state = FailoverState.PRIMARY
            self._active_ota = self.primary_ota
            decision = OTAPricingDecision(
                target_ota_source=self.primary_ota,
                state=FailoverState.PRIMARY,
                reason=(
                    "manual promote-to-primary (Q_0 approved, fresh pricing resumed)"
                ),
                timestamp=time.time(),
                expected_pricing_freshness_s=self.freshness_per_ota[self.primary_ota],
            )
            self._decisions.append(decision)
            return decision

    def get_ota_statuses(self) -> dict[str, OTASourceStatus]:
        """Snapshot aller OTA-Source-Statuses."""
        with self._lock:
            return dict(self._ota_status)

    def get_decisions(self) -> tuple[OTAPricingDecision, ...]:
        """Audit-Trail aller bisherigen Routing-Entscheidungen (immutable tuple)."""
        with self._lock:
            return tuple(self._decisions)


# CRUX-MK
