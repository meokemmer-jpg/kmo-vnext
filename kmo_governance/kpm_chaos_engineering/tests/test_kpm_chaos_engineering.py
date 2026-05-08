# [CRUX-MK]
"""Tests fuer KPM-Chaos-Engineering (Welle-26 Phase-19 Bio-Pattern-Lift).

14 Pflicht-Tests + Concurrent-Stress-Test:

1.  test_init_validation
2.  test_register_strategy
3.  test_inject_calls_handler
4.  test_inject_unknown_strategy_raises
5.  test_inject_random_picks_fault
6.  test_get_outcomes_filtered
7.  test_resilience_score_all_success
8.  test_resilience_score_no_outcomes_default
9.  test_pause_blocks_inject
10. test_resume_allows_inject
11. test_max_concurrent_chaos_enforced
12. test_concurrent_inject_50_threads
13. test_scenario_frozen
14. test_outcome_frozen
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.kpm_chaos_engineering import (
    ChaosOutcome,
    ChaosScenario,
    FaultSeverity,
    FaultType,
    KPMChaosEngineering,
)


# -------------- Helpers --------------


def _success_handler(scenario: ChaosScenario) -> ChaosOutcome:
    """Handler that always returns a success outcome."""
    return ChaosOutcome(
        scenario_id=scenario.scenario_id,
        success=True,
        actual_recovery_s=0.5,
        pnl_impact=0.0,
        observations=(f"handled {scenario.fault_type.value}",),
        timestamp=time.time(),
    )


def _failure_handler(scenario: ChaosScenario) -> ChaosOutcome:
    """Handler that always returns a failure outcome."""
    return ChaosOutcome(
        scenario_id=scenario.scenario_id,
        success=False,
        actual_recovery_s=10.0,
        pnl_impact=-1500.0,
        observations=("strategy crashed",),
        timestamp=time.time(),
    )


def _build_scenario(
    target: str = "kelly_0.4",
    sid: str = "test-1",
    ftype: FaultType = FaultType.LATENCY_SPIKE,
    sev: FaultSeverity = FaultSeverity.MINOR,
) -> ChaosScenario:
    return ChaosScenario(
        scenario_id=sid,
        fault_type=ftype,
        severity=sev,
        target_strategy_id=target,
        duration_s=1.0,
        params=(("min_ms", 10.0), ("max_ms", 50.0)),
        expected_recovery_s=1.0,
    )


# -------------- 1. Init-Validation --------------


def test_init_validation() -> None:
    """KPMChaosEngineering rejects invalid constructor args."""
    # Default construction works
    chaos = KPMChaosEngineering()
    assert chaos.default_severity == FaultSeverity.MINOR
    assert chaos.max_concurrent_chaos == 1

    # Custom severity + concurrent
    chaos2 = KPMChaosEngineering(
        default_severity=FaultSeverity.SEVERE, max_concurrent_chaos=5
    )
    assert chaos2.default_severity == FaultSeverity.SEVERE
    assert chaos2.max_concurrent_chaos == 5

    # max_concurrent_chaos must be >= 1
    with pytest.raises(ValueError):
        KPMChaosEngineering(max_concurrent_chaos=0)
    with pytest.raises(ValueError):
        KPMChaosEngineering(max_concurrent_chaos=-3)

    # default_severity must be FaultSeverity
    with pytest.raises(TypeError):
        KPMChaosEngineering(default_severity="moderate")  # type: ignore[arg-type]


# -------------- 2. Register-Strategy --------------


def test_register_strategy() -> None:
    """register_strategy validates inputs and stores handler."""
    chaos = KPMChaosEngineering()
    chaos.register_strategy("kelly_0.4", _success_handler)
    assert "kelly_0.4" in chaos.registered_strategies

    # Empty strategy_id raises
    with pytest.raises(ValueError):
        chaos.register_strategy("", _success_handler)

    # Non-callable handler raises
    with pytest.raises(TypeError):
        chaos.register_strategy("kelly_0.3", "not-callable")  # type: ignore[arg-type]

    # Re-register overwrites
    chaos.register_strategy("kelly_0.4", _failure_handler)
    outcome = chaos.inject(_build_scenario(target="kelly_0.4"))
    assert outcome.success is False  # failure_handler now bound


# -------------- 3. Inject-Calls-Handler --------------


def test_inject_calls_handler() -> None:
    """inject() calls registered handler and records outcome."""
    chaos = KPMChaosEngineering()

    invocations: list[ChaosScenario] = []

    def tracking_handler(scenario: ChaosScenario) -> ChaosOutcome:
        invocations.append(scenario)
        return _success_handler(scenario)

    chaos.register_strategy("kelly_0.4", tracking_handler)
    scenario = _build_scenario(sid="track-1")
    outcome = chaos.inject(scenario)

    assert len(invocations) == 1
    assert invocations[0].scenario_id == "track-1"
    assert outcome.success is True
    assert outcome.scenario_id == "track-1"

    # Outcome appended to audit trail
    all_outcomes = chaos.get_outcomes()
    assert len(all_outcomes) == 1
    assert all_outcomes[0] is outcome


# -------------- 4. Inject-Unknown-Strategy --------------


def test_inject_unknown_strategy_raises() -> None:
    """inject() raises KeyError when target_strategy_id not registered."""
    chaos = KPMChaosEngineering()
    scenario = _build_scenario(target="ghost_strategy")
    with pytest.raises(KeyError):
        chaos.inject(scenario)

    # Type validation: scenario must be ChaosScenario
    with pytest.raises(TypeError):
        chaos.inject("not-a-scenario")  # type: ignore[arg-type]


# -------------- 5. Inject-Random-Picks-Fault --------------


def test_inject_random_picks_fault() -> None:
    """inject_random() generates randomized scenario when fault_type omitted."""
    chaos = KPMChaosEngineering(default_severity=FaultSeverity.MODERATE)
    chaos.register_strategy("kelly_0.4", _success_handler)

    # Without explicit fault_type
    outcome = chaos.inject_random("kelly_0.4")
    assert outcome.success is True
    assert outcome.scenario_id.startswith("random-")

    # With explicit fault_type AND severity
    outcome2 = chaos.inject_random(
        "kelly_0.4",
        fault_type=FaultType.ORDER_REJECT,
        severity=FaultSeverity.CRITICAL,
    )
    assert outcome2.success is True

    # Unknown strategy_id raises
    with pytest.raises(KeyError):
        chaos.inject_random("ghost")

    # 5 randomized injections all succeed
    for _ in range(5):
        chaos.inject_random("kelly_0.4")
    outcomes = chaos.get_outcomes("kelly_0.4")
    assert len(outcomes) == 7  # 1 + 1 + 5


# -------------- 6. Get-Outcomes-Filtered --------------


def test_get_outcomes_filtered() -> None:
    """get_outcomes(strategy_id) returns only outcomes for that strategy."""
    chaos = KPMChaosEngineering(max_concurrent_chaos=2)
    chaos.register_strategy("kelly_0.4", _success_handler)
    chaos.register_strategy("kelly_0.2", _failure_handler)

    chaos.inject(_build_scenario(target="kelly_0.4", sid="s1"))
    chaos.inject(_build_scenario(target="kelly_0.2", sid="s2"))
    chaos.inject(_build_scenario(target="kelly_0.4", sid="s3"))

    all_outcomes = chaos.get_outcomes()
    assert len(all_outcomes) == 3
    assert isinstance(all_outcomes, tuple)  # immutable

    k04 = chaos.get_outcomes("kelly_0.4")
    assert len(k04) == 2
    assert {o.scenario_id for o in k04} == {"s1", "s3"}

    k02 = chaos.get_outcomes("kelly_0.2")
    assert len(k02) == 1
    assert k02[0].scenario_id == "s2"
    assert k02[0].success is False  # failure_handler

    # Empty filter for unknown id (no error, just empty)
    assert chaos.get_outcomes("ghost") == ()


# -------------- 7. Resilience-Score-All-Success --------------


def test_resilience_score_all_success() -> None:
    """get_resilience_score returns 1.0 when all outcomes succeed."""
    chaos = KPMChaosEngineering()
    chaos.register_strategy("kelly_0.4", _success_handler)

    for i in range(4):
        chaos.inject(_build_scenario(target="kelly_0.4", sid=f"ok-{i}"))

    assert chaos.get_resilience_score("kelly_0.4") == 1.0

    # Mixed success/failure -> proportion
    chaos.register_strategy("kelly_0.2", _failure_handler)
    for i in range(2):
        chaos.inject(_build_scenario(target="kelly_0.2", sid=f"fail-{i}"))
    chaos.register_strategy("kelly_0.2", _success_handler)
    chaos.inject(_build_scenario(target="kelly_0.2", sid="ok-final"))

    # 2 fails + 1 success = 1/3
    score = chaos.get_resilience_score("kelly_0.2")
    assert abs(score - 1.0 / 3.0) < 1e-9


# -------------- 8. Resilience-Score-No-Outcomes-Default --------------


def test_resilience_score_no_outcomes_default() -> None:
    """get_resilience_score returns 1.0 when no outcomes recorded yet."""
    chaos = KPMChaosEngineering()
    chaos.register_strategy("kelly_0.4", _success_handler)

    # No injects -> default 1.0 (vacuously resilient)
    assert chaos.get_resilience_score("kelly_0.4") == 1.0

    # Unknown strategy raises
    with pytest.raises(KeyError):
        chaos.get_resilience_score("ghost")

    # Empty strategy_id raises
    with pytest.raises(ValueError):
        chaos.get_resilience_score("")


# -------------- 9. Pause-Blocks-Inject --------------


def test_pause_blocks_inject() -> None:
    """pause_chaos() blocks further inject()-calls."""
    chaos = KPMChaosEngineering()
    chaos.register_strategy("kelly_0.4", _success_handler)

    assert chaos.is_paused is False
    chaos.pause_chaos()
    assert chaos.is_paused is True

    with pytest.raises(RuntimeError):
        chaos.inject(_build_scenario())

    # inject_random also blocked
    with pytest.raises(RuntimeError):
        chaos.inject_random("kelly_0.4")


# -------------- 10. Resume-Allows-Inject --------------


def test_resume_allows_inject() -> None:
    """resume_chaos() re-enables inject()-calls."""
    chaos = KPMChaosEngineering()
    chaos.register_strategy("kelly_0.4", _success_handler)

    chaos.pause_chaos()
    chaos.resume_chaos()
    assert chaos.is_paused is False

    outcome = chaos.inject(_build_scenario(sid="resumed"))
    assert outcome.success is True
    assert outcome.scenario_id == "resumed"


# -------------- 11. Max-Concurrent-Chaos-Enforced --------------


def test_max_concurrent_chaos_enforced() -> None:
    """max_concurrent_chaos blocks parallel injections beyond cap."""
    chaos = KPMChaosEngineering(max_concurrent_chaos=2)
    chaos.register_strategy("kelly_0.4", _success_handler)

    # Sequential injects always work (cap is on simultaneity)
    for i in range(5):
        outcome = chaos.inject(_build_scenario(sid=f"s-{i}"))
        assert outcome.success is True
    assert len(chaos.get_outcomes()) == 5

    # Simulate concurrency: a slow handler that holds the slot
    barrier = threading.Barrier(2)
    release_event = threading.Event()

    def slow_handler(scenario: ChaosScenario) -> ChaosOutcome:
        barrier.wait(timeout=2.0)
        release_event.wait(timeout=2.0)
        return _success_handler(scenario)

    chaos2 = KPMChaosEngineering(max_concurrent_chaos=1)
    chaos2.register_strategy("slow", slow_handler)

    # Start one in a thread (it will block in handler)
    holder_outcome: list[ChaosOutcome] = []
    err_box: list[BaseException] = []

    def hold() -> None:
        try:
            holder_outcome.append(
                chaos2.inject(_build_scenario(target="slow", sid="hold"))
            )
        except BaseException as exc:  # noqa: BLE001
            err_box.append(exc)

    holder_thread = threading.Thread(target=hold)
    holder_thread.start()
    barrier.wait(timeout=2.0)
    # Now slot is held; any second inject should fail with RuntimeError
    with pytest.raises(RuntimeError):
        chaos2.inject(_build_scenario(target="slow", sid="overflow"))
    release_event.set()
    holder_thread.join(timeout=3.0)
    assert not err_box, f"unexpected error in holder thread: {err_box}"
    assert len(holder_outcome) == 1


# -------------- 12. Concurrent-Inject-50-Threads --------------


def test_concurrent_inject_50_threads() -> None:
    """Stress-Test: 50 Threads concurrent inject + verify no data races."""
    chaos = KPMChaosEngineering(max_concurrent_chaos=50)
    chaos.register_strategy("kelly_0.4", _success_handler)

    barrier = threading.Barrier(50)
    errors: list[BaseException] = []
    error_lock = threading.Lock()

    def worker(index: int) -> None:
        barrier.wait(timeout=5.0)
        try:
            scenario = _build_scenario(sid=f"thr-{index}")
            chaos.inject(scenario)
        except BaseException as exc:  # noqa: BLE001
            with error_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not errors, f"unexpected errors in concurrent injects: {errors}"
    outcomes = chaos.get_outcomes("kelly_0.4")
    assert len(outcomes) == 50
    assert chaos.get_resilience_score("kelly_0.4") == 1.0
    # All scenario_ids unique
    ids = {o.scenario_id for o in outcomes}
    assert len(ids) == 50
    # active_chaos_count returned to zero
    assert chaos.active_chaos_count == 0


# -------------- 13. Scenario-Frozen --------------


def test_scenario_frozen() -> None:
    """ChaosScenario is frozen + validates fields."""
    scenario = _build_scenario(sid="frozen-1")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        scenario.scenario_id = "mutated"  # type: ignore[misc]

    # Validation: duration_s > 0
    with pytest.raises(ValueError):
        ChaosScenario(
            scenario_id="bad-1",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="x",
            duration_s=0.0,
        )
    with pytest.raises(ValueError):
        ChaosScenario(
            scenario_id="bad-2",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="x",
            duration_s=-1.0,
        )

    # Empty scenario_id raises
    with pytest.raises(ValueError):
        ChaosScenario(
            scenario_id="",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="x",
            duration_s=1.0,
        )

    # Empty target_strategy_id raises
    with pytest.raises(ValueError):
        ChaosScenario(
            scenario_id="x",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="",
            duration_s=1.0,
        )

    # Negative expected_recovery_s raises
    with pytest.raises(ValueError):
        ChaosScenario(
            scenario_id="x",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="y",
            duration_s=1.0,
            expected_recovery_s=-1.0,
        )

    # Wrong fault_type raises
    with pytest.raises(TypeError):
        ChaosScenario(
            scenario_id="x",
            fault_type="latency_spike",  # type: ignore[arg-type]
            severity=FaultSeverity.MINOR,
            target_strategy_id="y",
            duration_s=1.0,
        )

    # Wrong severity raises
    with pytest.raises(TypeError):
        ChaosScenario(
            scenario_id="x",
            fault_type=FaultType.LATENCY_SPIKE,
            severity="minor",  # type: ignore[arg-type]
            target_strategy_id="y",
            duration_s=1.0,
        )

    # params not a tuple raises
    with pytest.raises(TypeError):
        ChaosScenario(
            scenario_id="x",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="y",
            duration_s=1.0,
            params=[("a", 1)],  # type: ignore[arg-type]
        )

    # params entry not a 2-tuple raises
    with pytest.raises(TypeError):
        ChaosScenario(
            scenario_id="x",
            fault_type=FaultType.LATENCY_SPIKE,
            severity=FaultSeverity.MINOR,
            target_strategy_id="y",
            duration_s=1.0,
            params=(("a", 1, 2),),  # type: ignore[arg-type]
        )

    # Hashable (frozen + tuple-params)
    {scenario}  # noqa: B018
    assert hash(scenario) == hash(scenario)


# -------------- 14. Outcome-Frozen --------------


def test_outcome_frozen() -> None:
    """ChaosOutcome is frozen + validates fields."""
    outcome = ChaosOutcome(
        scenario_id="x",
        success=True,
        actual_recovery_s=0.0,
        pnl_impact=0.0,
        observations=("ok",),
        timestamp=time.time(),
    )
    with pytest.raises(Exception):
        outcome.success = False  # type: ignore[misc]

    # Empty scenario_id raises
    with pytest.raises(ValueError):
        ChaosOutcome(
            scenario_id="",
            success=True,
            actual_recovery_s=0.0,
            pnl_impact=0.0,
        )

    # Negative actual_recovery_s raises
    with pytest.raises(ValueError):
        ChaosOutcome(
            scenario_id="x",
            success=True,
            actual_recovery_s=-0.1,
            pnl_impact=0.0,
        )

    # observations not tuple raises
    with pytest.raises(TypeError):
        ChaosOutcome(
            scenario_id="x",
            success=True,
            actual_recovery_s=0.0,
            pnl_impact=0.0,
            observations=["a"],  # type: ignore[arg-type]
        )

    # observation element not string raises
    with pytest.raises(TypeError):
        ChaosOutcome(
            scenario_id="x",
            success=True,
            actual_recovery_s=0.0,
            pnl_impact=0.0,
            observations=(1,),  # type: ignore[arg-type]
        )


# -------------- Bonus: Handler-Exception-Becomes-Failure-Outcome --------------


def test_handler_exception_becomes_failure_outcome() -> None:
    """If handler raises, inject() captures it as a failed ChaosOutcome."""
    chaos = KPMChaosEngineering()

    def crashing_handler(scenario: ChaosScenario) -> ChaosOutcome:
        raise RuntimeError("simulated strategy crash")

    chaos.register_strategy("kelly_0.4", crashing_handler)
    outcome = chaos.inject(_build_scenario(sid="crashed"))
    assert outcome.success is False
    assert outcome.scenario_id == "crashed"
    assert any("RuntimeError" in obs for obs in outcome.observations)
    # active_chaos_count returns to zero even after exception
    assert chaos.active_chaos_count == 0


# -------------- Bonus: Handler-Wrong-Return-Type --------------


def test_handler_returning_non_outcome_becomes_failure() -> None:
    """Handler protocol violation -> synthetic failure outcome."""
    chaos = KPMChaosEngineering()

    def bad_handler(scenario: ChaosScenario) -> ChaosOutcome:
        return "not-an-outcome"  # type: ignore[return-value]

    chaos.register_strategy("kelly_0.4", bad_handler)
    outcome = chaos.inject(_build_scenario(sid="proto-1"))
    assert outcome.success is False
    assert any("non-ChaosOutcome" in obs for obs in outcome.observations)


# -------------- P-V13-3: Race-Schutz + Bounded outcomes --------------


def test_register_strategy_during_active_chaos_raises() -> None:
    """V13-3: Mid-injection-replace einer EXISTING strategy_id raises RuntimeError.

    Block-Handler haelt _active_chaos_count > 0, parallel-Thread versucht
    Handler von SCHON registrierter strategy_id zu ueberschreiben.
    Erwartung: RuntimeError + alter Handler bleibt aktiv.
    """
    chaos = KPMChaosEngineering()
    enter_evt = threading.Event()
    release_evt = threading.Event()

    def blocking_handler(scenario: ChaosScenario) -> ChaosOutcome:
        enter_evt.set()
        release_evt.wait(timeout=5.0)
        return ChaosOutcome(
            scenario_id=scenario.scenario_id,
            success=True,
            actual_recovery_s=0.0,
            pnl_impact=0.0,
            observations=("blocked",),
            timestamp=time.time(),
        )

    chaos.register_strategy("strat_v13_3", blocking_handler)

    inject_done = threading.Event()
    inject_outcome: list[ChaosOutcome] = []

    def runner_inject() -> None:
        try:
            outcome = chaos.inject(_build_scenario(
                sid="v13-3-block",
                target="strat_v13_3",
            ))
            inject_outcome.append(outcome)
        finally:
            inject_done.set()

    t = threading.Thread(target=runner_inject)
    t.start()

    # Wait for injection to enter handler (active_chaos_count > 0)
    assert enter_evt.wait(timeout=5.0), "blocking handler did not enter"
    assert chaos.active_chaos_count == 1

    # V13-3: Re-register EXISTING strategy_id while active -> RuntimeError
    with pytest.raises(RuntimeError, match="while.*chaos injection"):
        chaos.register_strategy("strat_v13_3", _success_handler)

    # V13-3: Register NEW strategy_id while active -> ALLOWED
    chaos.register_strategy("strat_v13_3_new", _success_handler)
    assert "strat_v13_3_new" in chaos.registered_strategies

    # Release blocking injection
    release_evt.set()
    inject_done.wait(timeout=5.0)
    t.join(timeout=5.0)

    assert chaos.active_chaos_count == 0
    assert len(inject_outcome) == 1
    assert inject_outcome[0].success is True


def test_outcomes_bounded_at_maxlen() -> None:
    """V13-3: _outcomes deque ist bounded auf max_outcomes_history."""
    chaos = KPMChaosEngineering(max_outcomes_history=5)
    chaos.register_strategy("kelly_0.4", _success_handler)

    # 10 injects -> 10 outcomes erzeugt, aber maxlen=5 -> nur letzte 5
    for i in range(10):
        chaos.inject(_build_scenario(sid=f"v13-3-{i}"))

    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 5
    # Letzte 5 (5..9) bleiben
    ids = [o.scenario_id for o in outcomes]
    assert ids == ["v13-3-5", "v13-3-6", "v13-3-7", "v13-3-8", "v13-3-9"]


def test_max_outcomes_history_validation() -> None:
    """V13-3: max_outcomes_history Pre-Condition >= 1."""
    # OK
    KPMChaosEngineering(max_outcomes_history=1)
    KPMChaosEngineering(max_outcomes_history=10000)

    # NOT OK
    with pytest.raises(ValueError, match="max_outcomes_history"):
        KPMChaosEngineering(max_outcomes_history=0)
    with pytest.raises(ValueError, match="max_outcomes_history"):
        KPMChaosEngineering(max_outcomes_history=-1)


# CRUX-MK
