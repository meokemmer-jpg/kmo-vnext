# [CRUX-MK]
"""Tests fuer HeyLou-Chaos-Engineering (Welle-43 Phase-36)."""
from __future__ import annotations

import pytest

from kmo_governance.heylou_chaos_engineering import (
    FaultSeverity,
    HeyLouChaosEngineering,
    HeyLouChaosScenario,
    OTAFaultType,
)


def _scen(
    hotel_id: str = "hildesheim",
    fault_type: OTAFaultType = OTAFaultType.OTA_PROVIDER_TIMEOUT,
    severity: FaultSeverity = FaultSeverity.MODERATE,
) -> HeyLouChaosScenario:
    return HeyLouChaosScenario(
        scenario_id="sc-001",
        fault_type=fault_type,
        severity=severity,
        hotel_id=hotel_id,
        ota_channel="booking.com",
        duration_s=0.1,
    )


def _ok_handler(s):
    return {"success": True, "failover_to_alt_channel": True, "revenue_impact_eur": 50.0}


def test_init_validation() -> None:
    HeyLouChaosEngineering()
    with pytest.raises(ValueError):
        HeyLouChaosEngineering(max_concurrent_chaos=0)


def test_scenario_validation() -> None:
    with pytest.raises(ValueError):
        HeyLouChaosScenario(
            scenario_id="",
            fault_type=OTAFaultType.OTA_PROVIDER_TIMEOUT,
            severity=FaultSeverity.MINOR,
            hotel_id="h",
            ota_channel="b",
            duration_s=0.1,
        )
    with pytest.raises(TypeError):
        HeyLouChaosScenario(
            scenario_id="s",
            fault_type="not-enum",  # type: ignore[arg-type]
            severity=FaultSeverity.MINOR,
            hotel_id="h",
            ota_channel="b",
            duration_s=0.1,
        )


def test_register_and_inject_success() -> None:
    chaos = HeyLouChaosEngineering()
    chaos.register_hotel("hildesheim", _ok_handler)
    o = chaos.inject(_scen())
    assert o.success is True
    assert o.failover_to_alt_channel is True
    assert o.revenue_impact_eur == 50.0


def test_unregistered_hotel_fails_gracefully() -> None:
    chaos = HeyLouChaosEngineering()
    o = chaos.inject(_scen(hotel_id="never-registered"))
    assert o.success is False
    assert o.error == "hotel_not_registered"


def test_pause_blocks_inject() -> None:
    chaos = HeyLouChaosEngineering()
    chaos.register_hotel("h", _ok_handler)
    chaos.pause_chaos()
    o = chaos.inject(_scen(hotel_id="h"))
    assert o.error == "chaos_paused"


def test_get_total_revenue_impact() -> None:
    chaos = HeyLouChaosEngineering()
    chaos.register_hotel("h", _ok_handler)
    chaos.inject(_scen(hotel_id="h"))
    chaos.inject(_scen(hotel_id="h"))
    assert chaos.get_total_revenue_impact_eur() == 100.0


def test_outcome_frozen_immutability() -> None:
    chaos = HeyLouChaosEngineering()
    chaos.register_hotel("h", _ok_handler)
    o = chaos.inject(_scen(hotel_id="h"))
    with pytest.raises(Exception):
        o.success = False  # type: ignore[misc]


def test_failed_outcome_appended_to_history() -> None:
    """W39-P3-Pattern: failed-outcomes auch in history."""
    chaos = HeyLouChaosEngineering()
    chaos.inject(_scen(hotel_id="never-registered"))
    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 1


def test_handler_exception_returns_failed() -> None:
    def boom(s):
        raise RuntimeError("oh no")
    chaos = HeyLouChaosEngineering()
    chaos.register_hotel("h", boom)
    o = chaos.inject(_scen(hotel_id="h"))
    assert o.success is False
    assert "RuntimeError" in (o.error or "")


def test_register_empty_hotel_id_raises() -> None:
    chaos = HeyLouChaosEngineering()
    with pytest.raises(ValueError):
        chaos.register_hotel("", _ok_handler)


def test_outcomes_history_bounded() -> None:
    chaos = HeyLouChaosEngineering(max_outcomes_history=2)
    chaos.register_hotel("h", _ok_handler)
    for _ in range(5):
        chaos.inject(_scen(hotel_id="h"))
    assert len(chaos.get_outcomes()) == 2


# CRUX-MK
