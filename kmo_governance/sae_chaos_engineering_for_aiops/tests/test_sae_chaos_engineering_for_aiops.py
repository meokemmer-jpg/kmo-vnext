# [CRUX-MK]
"""Tests fuer SAE-Chaos-Engineering-for-AIOps (Welle-30 Phase-23 Bio-Pattern-Lift 2/3).

16 Tests (alle Pflicht-Tests aus Auftrag + Bonus + bounded-deque-Test):

1.  test_init_validation
2.  test_register_slot
3.  test_inject_calls_handler
4.  test_inject_unknown_slot_raises
5.  test_inject_random_picks_fault
6.  test_get_outcomes_filtered_by_slot
7.  test_get_outcomes_filtered_by_agent_class
8.  test_stability_score_all_success
9.  test_stability_score_no_outcomes_default
10. test_pause_blocks_inject
11. test_resume_allows_inject
12. test_max_concurrent_chaos_enforced
13. test_concurrent_inject_50_threads
14. test_scenario_frozen
15. test_outcome_frozen
16. test_outcomes_bounded_at_maxlen
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.sae_chaos_engineering_for_aiops import (
    FaultSeverity,
    SAEChaosEngineering,
    SAEChaosOutcome,
    SAEChaosScenario,
    SAEFaultType,
)


# -------------- Helpers --------------


def _success_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
    """Handler that always returns a success outcome (Trinity-Voting recovered)."""
    return SAEChaosOutcome(
        scenario_id=scenario.scenario_id,
        success=True,
        actual_recovery_s=0.5,
        slots_impacted=1,
        trinity_voting_recovered=True,
        observations=(f"handled {scenario.fault_type.value}",),
        timestamp=time.time(),
    )


def _failure_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
    """Handler that always returns a failure outcome (Trinity-Voting broken)."""
    return SAEChaosOutcome(
        scenario_id=scenario.scenario_id,
        success=False,
        actual_recovery_s=10.0,
        slots_impacted=3,
        trinity_voting_recovered=False,
        observations=("slot crashed, trinity voting broken",),
        timestamp=time.time(),
    )


def _build_scenario(
    target: str = "slot_42",
    sid: str = "test-1",
    ftype: SAEFaultType = SAEFaultType.SLOT_CRASH,
    sev: FaultSeverity = FaultSeverity.MINOR,
    agent_class: str = "HOUSEKEEPING",
) -> SAEChaosScenario:
    return SAEChaosScenario(
        scenario_id=sid,
        fault_type=ftype,
        severity=sev,
        target_slot_id=target,
        agent_class=agent_class,
        duration_s=1.0,
        params=(("crash_window_s", 0.5),),
        expected_recovery_s=1.0,
    )


# -------------- 1. Init-Validation --------------


def test_init_validation() -> None:
    """SAEChaosEngineering rejects invalid constructor args."""
    chaos = SAEChaosEngineering()
    assert chaos.default_severity == FaultSeverity.MINOR
    assert chaos.max_concurrent_chaos == 3
    assert chaos.max_outcomes_history == 10000

    chaos2 = SAEChaosEngineering(
        default_severity=FaultSeverity.SEVERE,
        max_concurrent_chaos=5,
        max_outcomes_history=50,
    )
    assert chaos2.default_severity == FaultSeverity.SEVERE
    assert chaos2.max_concurrent_chaos == 5
    assert chaos2.max_outcomes_history == 50

    with pytest.raises(ValueError):
        SAEChaosEngineering(max_concurrent_chaos=0)
    with pytest.raises(ValueError):
        SAEChaosEngineering(max_concurrent_chaos=-1)
    with pytest.raises(ValueError):
        SAEChaosEngineering(max_outcomes_history=0)
    with pytest.raises(TypeError):
        SAEChaosEngineering(default_severity="minor")  # type: ignore[arg-type]


# -------------- 2. Register-Slot --------------


def test_register_slot() -> None:
    """register_slot binds (slot_id, agent_class) -> handler."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_1", "HOUSEKEEPING", _success_handler)
    chaos.register_slot("slot_2", "REVENUE_MGMT", _success_handler)

    assert "slot_1" in chaos.registered_slots
    assert "slot_2" in chaos.registered_slots
    assert "HOUSEKEEPING" in chaos.registered_agent_classes
    assert "REVENUE_MGMT" in chaos.registered_agent_classes

    with pytest.raises(ValueError):
        chaos.register_slot("", "HOUSEKEEPING", _success_handler)
    with pytest.raises(ValueError):
        chaos.register_slot("slot_3", "", _success_handler)
    with pytest.raises(TypeError):
        chaos.register_slot("slot_4", "HOUSEKEEPING", "not-callable")  # type: ignore[arg-type]


# -------------- 3. Inject-Calls-Handler --------------


def test_inject_calls_handler() -> None:
    """inject() invokes the registered handler and stores outcome."""
    chaos = SAEChaosEngineering()
    handler_calls: list[SAEChaosScenario] = []

    def tracking_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
        handler_calls.append(scenario)
        return _success_handler(scenario)

    chaos.register_slot("slot_42", "HOUSEKEEPING", tracking_handler)
    scenario = _build_scenario()
    outcome = chaos.inject(scenario)

    assert isinstance(outcome, SAEChaosOutcome)
    assert outcome.success is True
    assert outcome.trinity_voting_recovered is True
    assert len(handler_calls) == 1
    assert handler_calls[0].scenario_id == "test-1"

    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 1


# -------------- 4. Unknown-Slot-Raises --------------


def test_inject_unknown_slot_raises() -> None:
    """inject() raises KeyError for unregistered target_slot_id."""
    chaos = SAEChaosEngineering()
    scenario = _build_scenario(target="nonexistent_slot")
    with pytest.raises(KeyError):
        chaos.inject(scenario)

    with pytest.raises(TypeError):
        chaos.inject("not-a-scenario")  # type: ignore[arg-type]


# -------------- 5. Inject-Random-Picks-Fault --------------


def test_inject_random_picks_fault() -> None:
    """inject_random() selects fault_type, falls back to default_severity."""
    chaos = SAEChaosEngineering(default_severity=FaultSeverity.MODERATE)
    chaos.register_slot("slot_x", "HOUSEKEEPING", _success_handler)

    outcome = chaos.inject_random("slot_x")
    assert outcome.success is True

    outcome2 = chaos.inject_random(
        "slot_x", fault_type=SAEFaultType.TRINITY_VOTING_FAILURE
    )
    assert outcome2.success is True

    outcome3 = chaos.inject_random(
        "slot_x",
        fault_type=SAEFaultType.SLOT_CRASH,
        severity=FaultSeverity.CRITICAL,
    )
    assert outcome3.success is True

    with pytest.raises(KeyError):
        chaos.inject_random("nonexistent")


# -------------- 6. Get-Outcomes-Filtered-by-Slot --------------


def test_get_outcomes_filtered_by_slot() -> None:
    """get_outcomes(slot_id=...) filters to that slot only."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_a", "HOUSEKEEPING", _success_handler)
    chaos.register_slot("slot_b", "REVENUE_MGMT", _failure_handler)

    chaos.inject(_build_scenario(target="slot_a", sid="a-1"))
    chaos.inject(
        _build_scenario(
            target="slot_b", sid="b-1", agent_class="REVENUE_MGMT"
        )
    )
    chaos.inject(_build_scenario(target="slot_a", sid="a-2"))

    all_outcomes = chaos.get_outcomes()
    assert len(all_outcomes) == 3

    a_outcomes = chaos.get_outcomes(slot_id="slot_a")
    assert len(a_outcomes) == 2
    assert all(o.success for o in a_outcomes)

    b_outcomes = chaos.get_outcomes(slot_id="slot_b")
    assert len(b_outcomes) == 1
    assert not b_outcomes[0].success


# -------------- 7. Get-Outcomes-Filtered-by-Agent-Class --------------


def test_get_outcomes_filtered_by_agent_class() -> None:
    """get_outcomes(agent_class=...) filters across slots of that class."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_h1", "HOUSEKEEPING", _success_handler)
    chaos.register_slot("slot_h2", "HOUSEKEEPING", _success_handler)
    chaos.register_slot("slot_r1", "REVENUE_MGMT", _failure_handler)

    chaos.inject(_build_scenario(target="slot_h1", sid="h1-1"))
    chaos.inject(_build_scenario(target="slot_h2", sid="h2-1"))
    chaos.inject(
        _build_scenario(
            target="slot_r1", sid="r1-1", agent_class="REVENUE_MGMT"
        )
    )

    hk = chaos.get_outcomes(agent_class="HOUSEKEEPING")
    assert len(hk) == 2

    rm = chaos.get_outcomes(agent_class="REVENUE_MGMT")
    assert len(rm) == 1

    # Schnittmenge: slot_h1 + class HOUSEKEEPING
    intersect = chaos.get_outcomes(
        slot_id="slot_h1", agent_class="HOUSEKEEPING"
    )
    assert len(intersect) == 1

    # Inkonsistente Filter (slot_h1 + REVENUE_MGMT) -> leer
    none_match = chaos.get_outcomes(
        slot_id="slot_h1", agent_class="REVENUE_MGMT"
    )
    assert len(none_match) == 0


# -------------- 8. Stability-Score-All-Success --------------


def test_stability_score_all_success() -> None:
    """stability_score = 1.0 when all outcomes succeeded."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", _success_handler)

    for i in range(5):
        chaos.inject(_build_scenario(sid=f"s-{i}"))

    score = chaos.get_stability_score("slot_42")
    assert score == 1.0

    global_score = chaos.get_stability_score()
    assert global_score == 1.0


# -------------- 9. Stability-Score-No-Outcomes-Default --------------


def test_stability_score_no_outcomes_default() -> None:
    """stability_score defaults to 1.0 when no outcomes recorded."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", _success_handler)
    assert chaos.get_stability_score("slot_42") == 1.0
    assert chaos.get_stability_score() == 1.0  # global, also empty -> 1.0

    with pytest.raises(KeyError):
        chaos.get_stability_score("nonexistent")


# -------------- 10. Pause-Blocks-Inject --------------


def test_pause_blocks_inject() -> None:
    """pause_chaos() blocks subsequent inject() calls."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", _success_handler)
    chaos.pause_chaos()
    assert chaos.is_paused is True

    with pytest.raises(RuntimeError):
        chaos.inject(_build_scenario())


# -------------- 11. Resume-Allows-Inject --------------


def test_resume_allows_inject() -> None:
    """resume_chaos() unblocks inject() calls."""
    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", _success_handler)
    chaos.pause_chaos()
    chaos.resume_chaos()
    assert chaos.is_paused is False

    outcome = chaos.inject(_build_scenario())
    assert outcome.success is True


# -------------- 12. Max-Concurrent-Chaos-Enforced --------------


def test_max_concurrent_chaos_enforced() -> None:
    """max_concurrent_chaos cap enforced via active_chaos_count."""
    barrier = threading.Event()
    proceed = threading.Event()
    enter_count = {"n": 0}
    enter_lock = threading.Lock()

    def slow_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
        with enter_lock:
            enter_count["n"] += 1
            if enter_count["n"] == 2:
                barrier.set()
        proceed.wait(timeout=5.0)
        return _success_handler(scenario)

    chaos = SAEChaosEngineering(max_concurrent_chaos=2)
    chaos.register_slot("slot_a", "HOUSEKEEPING", slow_handler)
    chaos.register_slot("slot_b", "HOUSEKEEPING", slow_handler)

    threads: list[threading.Thread] = []
    results: list[Exception] = []
    results_lock = threading.Lock()

    def worker(target: str, sid: str) -> None:
        try:
            chaos.inject(_build_scenario(target=target, sid=sid))
        except Exception as e:
            with results_lock:
                results.append(e)

    t1 = threading.Thread(target=worker, args=("slot_a", "a-1"))
    t2 = threading.Thread(target=worker, args=("slot_b", "b-1"))
    t1.start()
    t2.start()

    # Warte bis beide Handler laufen
    assert barrier.wait(timeout=5.0)

    # Dritter Inject sollte sofort failen (max_concurrent_chaos=2 erreicht)
    with pytest.raises(RuntimeError):
        chaos.inject(_build_scenario(target="slot_a", sid="a-2"))

    # Handler freigeben
    proceed.set()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert len(results) == 0  # keine Worker-Exceptions
    assert chaos.active_chaos_count == 0


# -------------- 13. Concurrent-Inject-50-Threads --------------


def test_concurrent_inject_50_threads() -> None:
    """50 concurrent injects on multiple slots succeed without race."""
    chaos = SAEChaosEngineering(max_concurrent_chaos=10)
    for i in range(5):
        chaos.register_slot(f"slot_{i}", "HOUSEKEEPING", _success_handler)

    errors: list[Exception] = []
    errors_lock = threading.Lock()

    def worker(idx: int) -> None:
        try:
            chaos.inject_random(
                f"slot_{idx % 5}", fault_type=SAEFaultType.SLOT_CRASH
            )
        except RuntimeError:
            # max_concurrent_chaos transient errors are acceptable under load
            pass
        except Exception as e:
            with errors_lock:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(errors) == 0
    assert chaos.active_chaos_count == 0
    # mindestens ein paar Outcomes sollten gespeichert sein
    assert len(chaos.get_outcomes()) > 0


# -------------- 14. Scenario-Frozen --------------


def test_scenario_frozen() -> None:
    """SAEChaosScenario is frozen (immutable Audit-Trail)."""
    scenario = _build_scenario()
    with pytest.raises(Exception):  # FrozenInstanceError
        scenario.scenario_id = "mutated"  # type: ignore[misc]

    # Validation in __post_init__
    with pytest.raises(ValueError):
        SAEChaosScenario(
            scenario_id="",
            fault_type=SAEFaultType.SLOT_CRASH,
            severity=FaultSeverity.MINOR,
            target_slot_id="slot_42",
            agent_class="HK",
            duration_s=1.0,
            expected_recovery_s=1.0,
        )
    with pytest.raises(ValueError):
        SAEChaosScenario(
            scenario_id="s",
            fault_type=SAEFaultType.SLOT_CRASH,
            severity=FaultSeverity.MINOR,
            target_slot_id="",
            agent_class="HK",
            duration_s=1.0,
            expected_recovery_s=1.0,
        )
    with pytest.raises(ValueError):
        SAEChaosScenario(
            scenario_id="s",
            fault_type=SAEFaultType.SLOT_CRASH,
            severity=FaultSeverity.MINOR,
            target_slot_id="slot_42",
            agent_class="HK",
            duration_s=0.0,  # invalid
            expected_recovery_s=1.0,
        )
    with pytest.raises(ValueError):
        SAEChaosScenario(
            scenario_id="s",
            fault_type=SAEFaultType.SLOT_CRASH,
            severity=FaultSeverity.MINOR,
            target_slot_id="slot_42",
            agent_class="HK",
            duration_s=1.0,
            expected_recovery_s=0.0,  # invalid (must be > 0)
        )
    with pytest.raises(TypeError):
        SAEChaosScenario(
            scenario_id="s",
            fault_type="slot_crash",  # type: ignore[arg-type]
            severity=FaultSeverity.MINOR,
            target_slot_id="slot_42",
            agent_class="HK",
            duration_s=1.0,
            expected_recovery_s=1.0,
        )


# -------------- 15. Outcome-Frozen --------------


def test_outcome_frozen() -> None:
    """SAEChaosOutcome is frozen (immutable Audit-Trail)."""
    outcome = SAEChaosOutcome(
        scenario_id="s",
        success=True,
        actual_recovery_s=0.5,
        slots_impacted=1,
        trinity_voting_recovered=True,
        observations=("ok",),
        timestamp=time.time(),
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        outcome.success = False  # type: ignore[misc]

    # Validation
    with pytest.raises(ValueError):
        SAEChaosOutcome(
            scenario_id="",
            success=True,
            actual_recovery_s=0.5,
            slots_impacted=1,
            trinity_voting_recovered=True,
        )
    with pytest.raises(ValueError):
        SAEChaosOutcome(
            scenario_id="s",
            success=True,
            actual_recovery_s=-1.0,  # invalid
            slots_impacted=1,
            trinity_voting_recovered=True,
        )
    with pytest.raises(ValueError):
        SAEChaosOutcome(
            scenario_id="s",
            success=True,
            actual_recovery_s=0.5,
            slots_impacted=-1,  # invalid
            trinity_voting_recovered=True,
        )
    with pytest.raises(TypeError):
        SAEChaosOutcome(
            scenario_id="s",
            success=True,
            actual_recovery_s=0.5,
            slots_impacted=1,
            trinity_voting_recovered=True,
            observations=["not-a-tuple"],  # type: ignore[arg-type]
        )


# -------------- 16. Outcomes-Bounded-At-Maxlen --------------


def test_outcomes_bounded_at_maxlen() -> None:
    """Outcomes deque evicts oldest when max_outcomes_history exceeded."""
    chaos = SAEChaosEngineering(max_outcomes_history=10)
    chaos.register_slot("slot_42", "HOUSEKEEPING", _success_handler)

    for i in range(25):
        chaos.inject(_build_scenario(sid=f"s-{i}"))

    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 10  # maxlen enforced, 15 oldest evicted


# -------------- Bonus: Handler-Exception --------------


def test_handler_exception_becomes_failure_outcome() -> None:
    """Handler raising Exception -> synthetic failure outcome (no crash)."""

    def crashing_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
        raise RuntimeError("simulated handler crash")

    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", crashing_handler)
    outcome = chaos.inject(_build_scenario())

    assert outcome.success is False
    assert outcome.trinity_voting_recovered is False
    assert outcome.slots_impacted == 0
    assert any("RuntimeError" in obs for obs in outcome.observations)


# -------------- Bonus: Handler-Wrong-Return-Type --------------


def test_handler_returning_non_outcome_becomes_failure() -> None:
    """Handler returning non-Outcome -> synthetic failure outcome."""

    def bad_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
        return "not-an-outcome"  # type: ignore[return-value]

    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", bad_handler)
    outcome = chaos.inject(_build_scenario())

    assert outcome.success is False
    assert outcome.trinity_voting_recovered is False
    assert any(
        "non-SAEChaosOutcome" in obs for obs in outcome.observations
    )


# -------------- Bonus: Race-Schutz Mid-Injection-Replace --------------


def test_register_slot_race_protection() -> None:
    """Mid-injection-replace of existing slot_id raises RuntimeError."""
    barrier = threading.Event()
    proceed = threading.Event()

    def slow_handler(scenario: SAEChaosScenario) -> SAEChaosOutcome:
        barrier.set()
        proceed.wait(timeout=5.0)
        return _success_handler(scenario)

    chaos = SAEChaosEngineering()
    chaos.register_slot("slot_42", "HOUSEKEEPING", slow_handler)

    def worker() -> None:
        chaos.inject(_build_scenario())

    t = threading.Thread(target=worker)
    t.start()

    assert barrier.wait(timeout=5.0)

    # Replace existing slot mid-injection -> raise
    with pytest.raises(RuntimeError):
        chaos.register_slot("slot_42", "HOUSEKEEPING", _success_handler)

    # Neue slot_id darf jederzeit registriert werden
    chaos.register_slot("slot_43", "REVENUE_MGMT", _success_handler)

    proceed.set()
    t.join(timeout=5.0)
    assert chaos.active_chaos_count == 0
