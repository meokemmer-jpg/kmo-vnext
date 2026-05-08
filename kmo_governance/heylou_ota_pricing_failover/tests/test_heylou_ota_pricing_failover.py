# [CRUX-MK]
"""HeyLou-OTA-Pricing-Failover Tests (Welle-35 Phase-28 Bio-Pattern-Lift).

Iso-morphe Test-Suite zum Hotel-Domain-Pattern (failover_router/tests),
HeyLou-OTA-Domain-spezifisch fuer Pricing-Source-Failover.
"""
from __future__ import annotations

import threading

import pytest

from kmo_governance.heylou_ota_pricing_failover import (
    FailoverState,
    HeyLouOTAPricingFailover,
    OTAPricingDecision,
    OTASourceStatus,
)


def test_init_validation():
    """Init-Validation: Pflicht-Felder + Threshold-Check + Freshness-Range."""
    # Empty primary
    with pytest.raises(ValueError):
        HeyLouOTAPricingFailover(
            primary_ota="",
            standby_otas=["test_expedia"],
        )
    # Empty standby list
    with pytest.raises(ValueError):
        HeyLouOTAPricingFailover(
            primary_ota="test_booking_com",
            standby_otas=[],
        )
    # health_threshold == 0
    with pytest.raises(ValueError):
        HeyLouOTAPricingFailover(
            primary_ota="test_booking_com",
            standby_otas=["test_expedia"],
            health_threshold=0,
        )
    # health_threshold negative
    with pytest.raises(ValueError):
        HeyLouOTAPricingFailover(
            primary_ota="test_booking_com",
            standby_otas=["test_expedia"],
            health_threshold=-1,
        )
    # freshness override < 0
    with pytest.raises(ValueError):
        HeyLouOTAPricingFailover(
            primary_ota="test_booking_com",
            standby_otas=["test_expedia"],
            freshness_per_ota={"test_expedia": -10.0},
        )


def test_initial_state_primary():
    """Initial-State: PRIMARY mit primary OTA active und fresh pricing."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia", "test_direct_booking"],
    )
    assert r.state == FailoverState.PRIMARY
    assert r.active_ota == "test_booking_com"
    statuses = r.get_ota_statuses()
    assert statuses["test_booking_com"] == OTASourceStatus.HEALTHY
    assert statuses["test_expedia"] == OTASourceStatus.HEALTHY
    assert statuses["test_direct_booking"] == OTASourceStatus.HEALTHY
    # Defaults: primary 30s, standby[0] 60s, standby[1] 300s
    assert r.freshness_per_ota["test_booking_com"] == 30.0
    assert r.freshness_per_ota["test_expedia"] == 60.0
    assert r.freshness_per_ota["test_direct_booking"] == 300.0


def test_route_to_primary_when_healthy():
    """route() liefert primary wenn alle Booking-Outcomes successful."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    for _ in range(3):
        r.record_booking_outcome("test_booking_com", successful=True)
    decision = r.route()
    assert decision.target_ota_source == "test_booking_com"
    assert decision.state == FailoverState.PRIMARY
    assert decision.expected_pricing_freshness_s == 30.0
    assert "healthy" in decision.reason.lower()


def test_failover_when_primary_5_fails():
    """5 fehlgeschlagene Booking-Outcomes -> Failover (default health_threshold=5)."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    # 4 fails -> noch DEGRADED, kein Failover
    for _ in range(4):
        r.record_booking_outcome("test_booking_com", successful=False)
    decision = r.route()
    assert decision.target_ota_source == "test_booking_com"
    assert decision.state == FailoverState.PRIMARY
    statuses = r.get_ota_statuses()
    assert statuses["test_booking_com"] == OTASourceStatus.DEGRADED

    # 5. fail -> DOWN, route() -> Failover
    r.record_booking_outcome("test_booking_com", successful=False)
    decision = r.route()
    assert decision.target_ota_source == "test_expedia"
    assert decision.state == FailoverState.FAILED_OVER
    assert decision.expected_pricing_freshness_s == 60.0  # standby[0] default
    assert "DOWN" in decision.reason
    assert "failover" in decision.reason.lower()


def test_failover_skips_unhealthy_standby():
    """Failover ueberspringt unhealthy standby OTA."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia", "test_direct_booking"],
    )
    # Mache erste standby DOWN
    for _ in range(5):
        r.record_booking_outcome("test_expedia", successful=False)
    # Mache primary DOWN
    for _ in range(5):
        r.record_booking_outcome("test_booking_com", successful=False)
    decision = r.route()
    # Sollte zu zweiter standby skippen
    assert decision.target_ota_source == "test_direct_booking"
    assert decision.state == FailoverState.FAILED_OVER
    assert decision.expected_pricing_freshness_s == 300.0  # standby[1] default


def test_recovery_state_after_primary_returns_successful():
    """Nach Failover: primary returns successful -> RECOVERING (no auto-promote)."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    # Trigger Failover
    for _ in range(5):
        r.record_booking_outcome("test_booking_com", successful=False)
    r.route()
    assert r.state == FailoverState.FAILED_OVER
    # Primary recovers
    for _ in range(3):
        r.record_booking_outcome("test_booking_com", successful=True)
    decision = r.route()
    # Sollte RECOVERING sein, NICHT direkt PRIMARY (Q_0-Sicherheit)
    assert decision.state == FailoverState.RECOVERING
    assert decision.target_ota_source == "test_expedia"  # immer noch standby aktiv
    assert "manual promote" in decision.reason.lower()


def test_promote_to_primary():
    """Manuelle Promotion: zurueck zu primary OTA wenn HEALTHY."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    # Trigger Failover -> dann Recovery
    for _ in range(5):
        r.record_booking_outcome("test_booking_com", successful=False)
    r.route()
    for _ in range(3):
        r.record_booking_outcome("test_booking_com", successful=True)
    r.route()  # transition zu RECOVERING
    decision = r.promote_to_primary()
    assert decision.state == FailoverState.PRIMARY
    assert decision.target_ota_source == "test_booking_com"
    assert decision.expected_pricing_freshness_s == 30.0  # primary fresh pricing
    assert "promote-to-primary" in decision.reason.lower()
    assert r.state == FailoverState.PRIMARY
    assert r.active_ota == "test_booking_com"


def test_promote_unhealthy_raises():
    """promote_to_primary raises RuntimeError wenn primary nicht HEALTHY."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    # Mache primary DOWN
    for _ in range(5):
        r.record_booking_outcome("test_booking_com", successful=False)
    with pytest.raises(RuntimeError, match="not HEALTHY"):
        r.promote_to_primary()


def test_health_recovery_resets_fail_count():
    """Successful booking nach 4 fails -> Reset counter, status zurueck zu HEALTHY."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    # 4 fails -> DEGRADED
    for _ in range(4):
        r.record_booking_outcome("test_booking_com", successful=False)
    statuses = r.get_ota_statuses()
    assert statuses["test_booking_com"] == OTASourceStatus.DEGRADED

    # 1 successful booking -> reset to HEALTHY
    r.record_booking_outcome("test_booking_com", successful=True)
    statuses = r.get_ota_statuses()
    assert statuses["test_booking_com"] == OTASourceStatus.HEALTHY

    # Erneute 4 fails -> wieder DEGRADED, NICHT DOWN (counter resettet)
    for _ in range(4):
        r.record_booking_outcome("test_booking_com", successful=False)
    statuses = r.get_ota_statuses()
    assert statuses["test_booking_com"] == OTASourceStatus.DEGRADED


def test_freshness_per_ota_default_graduated():
    """Default-Freshness ist graduiert: 30s / 60s / 300s / 600s+ ..."""
    r = HeyLouOTAPricingFailover(
        primary_ota="primary",
        standby_otas=["s1", "s2", "s3"],
    )
    assert r.freshness_per_ota["primary"] == 30.0
    assert r.freshness_per_ota["s1"] == 60.0
    assert r.freshness_per_ota["s2"] == 300.0
    # Weitere standbys: erhoeht (DEFAULT_FRESHNESS_STANDBY_SECOND_S + 300 * (idx-1))
    assert r.freshness_per_ota["s3"] == 600.0  # 300 + 300*1


def test_concurrent_record_outcomes_50_threads():
    """50 Threads recorden parallel -> keine Race-Conditions, keine Exceptions."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia", "test_direct_booking"],
    )
    errors: list[Exception] = []

    def worker(ota: str, successful: bool, n: int) -> None:
        try:
            for _ in range(n):
                r.record_booking_outcome(ota, successful=successful)
        except Exception as e:
            errors.append(e)

    threads: list[threading.Thread] = []
    # 50 Threads, mixed outcomes auf alle 3 OTAs
    for i in range(50):
        ota = ["test_booking_com", "test_expedia", "test_direct_booking"][i % 3]
        successful = (i % 2 == 0)
        t = threading.Thread(target=worker, args=(ota, successful, 10))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # State soll konsistent sein (keine partiellen Updates)
    statuses = r.get_ota_statuses()
    for ota in ["test_booking_com", "test_expedia", "test_direct_booking"]:
        assert statuses[ota] in (
            OTASourceStatus.HEALTHY,
            OTASourceStatus.DEGRADED,
            OTASourceStatus.DOWN,
        )


def test_decision_frozen_immutability():
    """OTAPricingDecision ist frozen -> Audit-Trail-Integritaet."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    decision = r.route()
    with pytest.raises(Exception):  # FrozenInstanceError
        decision.target_ota_source = "hacker_ota"  # type: ignore[misc]
    with pytest.raises(Exception):
        decision.state = FailoverState.FAILED_OVER  # type: ignore[misc]


def test_unknown_ota_raises():
    """record_booking_outcome auf unknown OTA -> ValueError."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    with pytest.raises(ValueError, match="unknown ota_source"):
        r.record_booking_outcome("test_unknown_gds", successful=True)


def test_get_decisions_returns_immutable_tuple():
    """get_decisions() liefert tuple (immutable Audit-Trail)."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    r.route()
    r.route()
    decisions = r.get_decisions()
    assert isinstance(decisions, tuple)
    assert len(decisions) == 2
    # Spec-Pflicht: get_decisions() -> tuple[OTAPricingDecision, ...]
    # tuple ist immutable, kein .append
    assert not hasattr(decisions, "append")


def test_all_down_returns_primary_fallback():
    """Alle OTAs DOWN -> route-to-primary mit warning-reason."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia"],
    )
    for _ in range(5):
        r.record_booking_outcome("test_booking_com", successful=False)
        r.record_booking_outcome("test_expedia", successful=False)
    decision = r.route()
    assert decision.target_ota_source == "test_booking_com"
    assert "all OTA-sources DOWN" in decision.reason
    assert "stale pricing" in decision.reason.lower()


def test_freshness_per_ota_override():
    """Override fuer freshness_per_ota wirkt."""
    r = HeyLouOTAPricingFailover(
        primary_ota="test_booking_com",
        standby_otas=["test_expedia", "test_direct_booking"],
        freshness_per_ota={
            "test_booking_com": 15.0,
            "test_expedia": 45.0,
        },
    )
    assert r.freshness_per_ota["test_booking_com"] == 15.0
    assert r.freshness_per_ota["test_expedia"] == 45.0
    # Nicht-overridete bleiben default
    assert r.freshness_per_ota["test_direct_booking"] == 300.0


# CRUX-MK
