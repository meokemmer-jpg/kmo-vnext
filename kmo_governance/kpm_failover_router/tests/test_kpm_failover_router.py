from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.kpm_failover_router import (
    BrokerHealth,
    BrokerStatus,
    KPMFailoverRouter,
    RoutingDecision,
)


def test_register_broker_routes_primary_when_healthy() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision == RoutingDecision(
        chosen_broker_id="primary",
        fallback_chain=("secondary",),
    )


def test_primary_failure_routes_to_secondary() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)
    router.record_health("primary", latency_ms=50, error_rate=0.75)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision.chosen_broker_id == "secondary"
    assert decision.fallback_chain == ()


def test_primary_and_secondary_failure_routes_to_tertiary() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)
    router.register_broker("tertiary", 3)
    router.record_health("primary", latency_ms=2_000, error_rate=0.01)
    router.record_health("secondary", latency_ms=50, error_rate=0.50)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision.chosen_broker_id == "tertiary"
    assert decision.fallback_chain == ()


def test_degraded_primary_is_used_when_no_healthy_broker_exists() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)
    router.record_health("primary", latency_ms=400, error_rate=0.10)
    router.record_health("secondary", latency_ms=900, error_rate=0.20)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision.chosen_broker_id == "primary"
    assert decision.fallback_chain == ("secondary",)


def test_healthy_secondary_beats_degraded_primary() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)
    router.record_health("primary", latency_ms=400, error_rate=0.10)
    router.record_health("secondary", latency_ms=40, error_rate=0.01)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision.chosen_broker_id == "secondary"
    assert decision.fallback_chain == ("primary",)


def test_fallback_chain_excludes_failed_brokers_and_keeps_priority_order() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)
    router.register_broker("tertiary", 3)
    router.register_broker("quaternary", 4)
    router.record_health("primary", latency_ms=2_000, error_rate=0.01)
    router.record_health("secondary", latency_ms=20, error_rate=0.01)
    router.record_health("tertiary", latency_ms=700, error_rate=0.10)
    router.record_health("quaternary", latency_ms=30, error_rate=0.01)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision.chosen_broker_id == "secondary"
    assert decision.fallback_chain == ("tertiary", "quaternary")


def test_record_health_returns_frozen_health_snapshot() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)

    health = router.record_health("primary", latency_ms=25, error_rate=0.01)

    assert health == BrokerHealth(
        broker_id="primary",
        latency_ms=25.0,
        error_rate=0.01,
        status=BrokerStatus.HEALTHY,
    )
    with pytest.raises(FrozenInstanceError):
        health.status = BrokerStatus.FAILED


def test_routing_decision_is_frozen() -> None:
    decision = RoutingDecision(chosen_broker_id="primary", fallback_chain=("secondary",))

    with pytest.raises(FrozenInstanceError):
        decision.chosen_broker_id = "secondary"


def test_record_health_rejects_unknown_broker() -> None:
    router = KPMFailoverRouter()

    with pytest.raises(KeyError, match="unknown broker"):
        router.record_health("missing", latency_ms=10, error_rate=0.01)


def test_route_order_raises_when_all_brokers_failed() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 1)
    router.register_broker("secondary", 2)
    router.record_health("primary", latency_ms=1_500, error_rate=0.10)
    router.record_health("secondary", latency_ms=20, error_rate=0.75)

    with pytest.raises(RuntimeError, match="no available broker"):
        router.route_order({"symbol": "KPM", "qty": 10})


def test_registering_existing_broker_updates_priority() -> None:
    router = KPMFailoverRouter()
    router.register_broker("primary", 10)
    router.register_broker("secondary", 2)
    router.register_broker("primary", 1)

    decision = router.route_order({"symbol": "KPM", "qty": 10})

    assert decision.chosen_broker_id == "primary"
    assert decision.fallback_chain == ("secondary",)


def test_invalid_inputs_are_rejected() -> None:
    router = KPMFailoverRouter()

    with pytest.raises(ValueError, match="broker_id"):
        router.register_broker(" ", 1)
    with pytest.raises(ValueError, match="priority"):
        router.register_broker("primary", -1)

    router.register_broker("primary", 1)

    with pytest.raises(ValueError, match="latency_ms"):
        router.record_health("primary", latency_ms=-1, error_rate=0.01)
    with pytest.raises(ValueError, match="error_rate"):
        router.record_health("primary", latency_ms=10, error_rate=1.01)
    with pytest.raises(TypeError, match="order_payload"):
        router.route_order(["not", "a", "mapping"])
