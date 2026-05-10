from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from kmo_governance.df_health_monitor_chaos_engineering import (
    DFChaosFault,
    DFChaosOutcome,
    DFChaosScenario,
    DFHealthMonitorChaosEngineering,
    FaultSeverity,
)


def make_scenario(
    df_id: str = "df-main",
    fault: DFChaosFault = DFChaosFault.DF_PROCESS_CRASH,
    severity: FaultSeverity = FaultSeverity.SEVERE,
) -> DFChaosScenario:
    return DFChaosScenario(df_id=df_id, fault=fault, severity=severity)


def test_register_df_allows_successful_injection() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")

    outcome = engine.inject(make_scenario())

    assert outcome.success is True
    assert outcome.df_id == "df-main"
    assert outcome.message == "process crash injected"


def test_unregistered_df_returns_failed_outcome() -> None:
    engine = DFHealthMonitorChaosEngineering()

    outcome = engine.inject(make_scenario())

    assert outcome.success is False
    assert "not registered" in outcome.message
    assert outcome.metadata == {"reason": "unregistered_df"}


def test_failed_outcome_is_appended_to_history() -> None:
    engine = DFHealthMonitorChaosEngineering()

    outcome = engine.inject(make_scenario())

    assert engine.get_outcomes() == (outcome,)


def test_pause_chaos_blocks_injection() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")
    engine.pause_chaos()

    outcome = engine.inject(make_scenario())

    assert outcome.success is False
    assert outcome.message == "chaos injection is paused"
    assert outcome.metadata == {"reason": "paused"}


def test_pause_chaos_can_resume_injection() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")
    engine.pause_chaos()
    engine.pause_chaos(False)

    outcome = engine.inject(make_scenario())

    assert outcome.success is True


def test_get_outcomes_returns_immutable_tuple_snapshot() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")
    first = engine.inject(make_scenario())

    outcomes = engine.get_outcomes()
    engine.inject(make_scenario(fault=DFChaosFault.DF_AUTH_EXPIRED))

    assert isinstance(outcomes, tuple)
    assert outcomes == (first,)
    assert len(engine.get_outcomes()) == 2


def test_scenario_is_frozen() -> None:
    scenario = make_scenario()

    with pytest.raises(FrozenInstanceError):
        scenario.df_id = "changed"  # type: ignore[misc]


def test_outcome_is_frozen() -> None:
    outcome = DFChaosOutcome(
        scenario_id="scenario-1",
        df_id="df-main",
        fault=DFChaosFault.DF_PROCESS_CRASH,
        severity=FaultSeverity.SEVERE,
        success=True,
        message="ok",
    )

    with pytest.raises(FrozenInstanceError):
        outcome.success = False  # type: ignore[misc]


def test_rejects_empty_df_id_registration() -> None:
    engine = DFHealthMonitorChaosEngineering()

    with pytest.raises(ValueError, match="df_id"):
        engine.register_df("   ")


def test_all_faults_can_be_injected() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")

    outcomes = [
        engine.inject(make_scenario(fault=fault, severity=FaultSeverity.MODERATE))
        for fault in DFChaosFault
    ]

    assert [outcome.fault for outcome in outcomes] == list(DFChaosFault)
    assert all(outcome.success for outcome in outcomes)


def test_severity_is_preserved_in_outcome() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")
    scenario = make_scenario(severity=FaultSeverity.CRITICAL)

    outcome = engine.inject(scenario)

    assert outcome.severity is FaultSeverity.CRITICAL


def test_outcome_carries_scenario_metadata_and_timestamp() -> None:
    engine = DFHealthMonitorChaosEngineering()
    engine.register_df("df-main")
    scenario = DFChaosScenario(
        df_id="df-main",
        fault=DFChaosFault.DF_OUTPUT_CORRUPTED,
        severity=FaultSeverity.MINOR,
        metadata={"target": "artifact-stream"},
    )

    outcome = engine.inject(scenario)

    assert outcome.scenario_id == scenario.scenario_id
    assert outcome.metadata == {"target": "artifact-stream"}
    assert isinstance(outcome.timestamp, datetime)
