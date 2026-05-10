# [CRUX-MK]
"""Tests fuer SAE-v8 Chaos (Welle-55, DEMO-only)."""
from __future__ import annotations

import pytest

from kmo_governance.sae_v8_chaos_engineering_real import (
    FaultSeverity,
    SAEv8ChaosEngineering,
    SAEv8ChaosScenario,
    SAEv8FaultType,
)


def _scen(slot="slot-1", ft=SAEv8FaultType.TRINITY_VOTE_TIMEOUT, sev=FaultSeverity.MODERATE):
    return SAEv8ChaosScenario(
        scenario_id="s1", fault_type=ft, severity=sev, slot_id=slot, duration_s=0.1,
    )


def _ok_handler(s):
    return {"success": True, "trinity_consensus_recovered": True}


def test_init_validation():
    SAEv8ChaosEngineering()
    with pytest.raises(ValueError):
        SAEv8ChaosEngineering(max_concurrent_chaos=0)


def test_scenario_validation():
    with pytest.raises(ValueError):
        SAEv8ChaosScenario(scenario_id="", fault_type=SAEv8FaultType.SLOT_AGENT_CRASH, severity=FaultSeverity.MINOR, slot_id="s", duration_s=0.1)
    with pytest.raises(ValueError):
        SAEv8ChaosScenario(scenario_id="s", fault_type=SAEv8FaultType.SLOT_AGENT_CRASH, severity=FaultSeverity.MINOR, slot_id="s", duration_s=0)
    with pytest.raises(TypeError):
        SAEv8ChaosScenario(scenario_id="s", fault_type="not-enum", severity=FaultSeverity.MINOR, slot_id="s", duration_s=0.1)  # type: ignore


def test_register_and_inject_success():
    chaos = SAEv8ChaosEngineering()
    chaos.register_slot("slot-1", _ok_handler)
    o = chaos.inject(_scen())
    assert o.success is True
    assert o.trinity_consensus_recovered is True


def test_unregistered_slot_fails():
    chaos = SAEv8ChaosEngineering()
    o = chaos.inject(_scen(slot="no-such"))
    assert o.success is False
    assert o.error == "slot_not_registered"


def test_pause_blocks_inject():
    chaos = SAEv8ChaosEngineering()
    chaos.register_slot("s", _ok_handler)
    chaos.pause_chaos()
    o = chaos.inject(_scen(slot="s"))
    assert o.error == "chaos_paused"


def test_register_empty_slot_raises():
    chaos = SAEv8ChaosEngineering()
    with pytest.raises(ValueError):
        chaos.register_slot("", _ok_handler)


def test_handler_exception_returns_failed():
    def boom(s):
        raise RuntimeError("x")
    chaos = SAEv8ChaosEngineering()
    chaos.register_slot("s", boom)
    o = chaos.inject(_scen(slot="s"))
    assert o.success is False
    assert "RuntimeError" in (o.error or "")


def test_failed_outcome_in_history():
    chaos = SAEv8ChaosEngineering()
    chaos.inject(_scen(slot="never"))
    assert len(chaos.get_outcomes()) == 1


def test_outcomes_history_bounded():
    chaos = SAEv8ChaosEngineering(max_outcomes_history=2)
    chaos.register_slot("s", _ok_handler)
    for _ in range(5):
        chaos.inject(_scen(slot="s"))
    assert len(chaos.get_outcomes()) == 2


def test_outcome_immutable():
    chaos = SAEv8ChaosEngineering()
    chaos.register_slot("s", _ok_handler)
    o = chaos.inject(_scen(slot="s"))
    with pytest.raises(Exception):
        o.success = False  # type: ignore


def test_each_fault_type_works():
    chaos = SAEv8ChaosEngineering()
    chaos.register_slot("s", _ok_handler)
    for ft in SAEv8FaultType:
        o = chaos.inject(_scen(slot="s", ft=ft))
        assert o.fault_type == ft


def test_consensus_failed_propagates():
    def bad(s):
        return {"success": True, "trinity_consensus_recovered": False}
    chaos = SAEv8ChaosEngineering()
    chaos.register_slot("s", bad)
    o = chaos.inject(_scen(slot="s"))
    assert o.trinity_consensus_recovered is False


# CRUX-MK
