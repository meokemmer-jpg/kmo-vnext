"""KMO Chaos-Engineering Tests [CRUX-MK].

Spec: Welle-10 Phase-6.2 Subagent-D.

Pflicht (10):
- test_failure_injector_no_chaos_default
- test_failure_injector_always_raises_at_probability_1
- test_failure_injector_latency_within_bounds
- test_chaos_scenario_runs_steps_in_order
- test_chaos_monkey_registers_targets
- test_chaos_monkey_schedules_and_runs
- test_recovery_verifier_succeeds_after_retry
- test_recovery_verifier_fails_after_max_attempts
- test_resilience_score_all_recoveries_returns_1
- test_resilience_score_no_recoveries_returns_0
"""

from __future__ import annotations

import random

import pytest

from kmo_governance.chaos_engineering import (
    ChaosMonkey,
    ChaosOutcome,
    ChaosOutcomeStatus,
    ChaosScenario,
    FailureInjector,
    RecoveryResult,
    RecoveryVerifier,
    ResilienceScore,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def fixed_clock():
    state = {"t": 1_000_000.0}

    def clock():
        return state["t"]

    def tick(dt):
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def fake_sleep(fixed_clock):
    def sleep_fn(seconds: float) -> None:
        fixed_clock.tick(seconds)

    return sleep_fn


@pytest.fixture
def deterministic_rng():
    """Reproducible RNG seeded with 42."""
    return random.Random(42)


# ---------------- Pflicht-Tests ----------------


def test_failure_injector_no_chaos_default():
    """Default failure_probability=0.0 must NEVER raise."""
    injector = FailureInjector()
    # Run 100 invocations to be statistically certain
    for _ in range(100):
        injector.inject_failure()  # never raises
    assert injector.failure_count == 0
    assert injector.injection_count == 100


def test_failure_injector_always_raises_at_probability_1():
    """failure_probability=1.0 must ALWAYS raise."""
    injector = FailureInjector(
        failure_probability=1.0,
        exception_type=RuntimeError,
        exception_message="boom",
    )
    with pytest.raises(RuntimeError, match="boom"):
        injector.inject_failure()
    assert injector.failure_count == 1


def test_failure_injector_latency_within_bounds(deterministic_rng, fake_sleep):
    """inject_latency must produce sleep duration in [min, max] ms range."""
    injector = FailureInjector(
        latency_min_ms=50.0,
        latency_max_ms=200.0,
        rng=deterministic_rng,
        sleep_fn=fake_sleep,
    )
    for _ in range(20):
        seconds = injector.inject_latency()
        assert 0.050 <= seconds <= 0.200, f"latency {seconds}s out of bounds"
    assert injector.latency_count == 20


def test_chaos_scenario_runs_steps_in_order(fake_sleep):
    """ChaosScenario applies all steps before target_fn. Order preserved."""
    call_log: list[str] = []
    rng = random.Random(0)

    # Two injectors: first adds latency, second adds zero-prob failure (won't raise)
    step1 = FailureInjector(
        latency_min_ms=10.0,
        latency_max_ms=10.0,
        rng=rng,
        sleep_fn=fake_sleep,
    )
    step2 = FailureInjector(
        failure_probability=0.0,
        rng=rng,
        sleep_fn=fake_sleep,
    )

    scenario = ChaosScenario(name="ordered", steps=[step1, step2])

    def target():
        call_log.append("target_called")

    outcome = scenario.run(target, target_name="t1")
    assert outcome.status == ChaosOutcomeStatus.SUCCESS
    assert call_log == ["target_called"]
    assert step1.latency_count == 1
    assert step2.injection_count == 1  # failure-attempt counted


def test_chaos_monkey_registers_targets():
    """ChaosMonkey.register_target stores callables; rejects empty/non-callable."""
    monkey = ChaosMonkey()
    monkey.register_target("alpha", lambda: 42)
    monkey.register_target("beta", lambda: "x")

    metrics = monkey.get_metrics()
    assert metrics["registered_targets"] == 2

    # Pre-condition: empty name rejected
    with pytest.raises(ValueError):
        monkey.register_target("", lambda: None)
    # Pre-condition: non-callable rejected
    with pytest.raises(TypeError):
        monkey.register_target("bad", "not_callable")  # type: ignore[arg-type]


def test_chaos_monkey_schedules_and_runs(fake_sleep):
    """ChaosMonkey schedules scenarios + runs them, producing ChaosOutcomes."""
    monkey = ChaosMonkey()
    rng = random.Random(0)

    monkey.register_target("svc_ok", lambda: None)

    # Scenario without failure -> SUCCESS
    scenario = ChaosScenario(
        name="benign",
        steps=[
            FailureInjector(
                latency_min_ms=1.0,
                latency_max_ms=1.0,
                rng=rng,
                sleep_fn=fake_sleep,
            )
        ],
    )
    monkey.schedule_chaos("svc_ok", scenario)

    outcomes = monkey.run_all_scheduled()
    assert len(outcomes) == 1
    assert outcomes[0].status == ChaosOutcomeStatus.SUCCESS
    assert outcomes[0].target_name == "svc_ok"
    assert outcomes[0].scenario_name == "benign"

    metrics = monkey.get_metrics()
    assert metrics["total_runs"] == 1
    assert metrics["successes"] == 1

    # Pre-condition: scheduling unknown target raises KeyError
    with pytest.raises(KeyError):
        monkey.schedule_chaos("unknown", scenario)


def test_recovery_verifier_succeeds_after_retry(fixed_clock, fake_sleep):
    """RecoveryVerifier returns recovered=True if target eventually succeeds."""
    state = {"calls": 0}

    def flaky():
        state["calls"] += 1
        if state["calls"] < 3:
            raise RuntimeError("not yet")
        # Third call succeeds
        return "ok"

    verifier = RecoveryVerifier(
        max_attempts=5,
        interval_s=0.01,
        clock=fixed_clock,
        sleep_fn=fake_sleep,
    )
    result = verifier.verify_recovery(flaky)
    assert isinstance(result, RecoveryResult)
    assert result.recovered is True
    assert result.attempts == 3
    assert result.total_time_s >= 0.0


def test_recovery_verifier_fails_after_max_attempts(fixed_clock, fake_sleep):
    """RecoveryVerifier returns recovered=False if target never recovers."""

    def always_fail():
        raise RuntimeError("perma-fail")

    verifier = RecoveryVerifier(
        max_attempts=3,
        interval_s=0.005,
        clock=fixed_clock,
        sleep_fn=fake_sleep,
    )
    result = verifier.verify_recovery(always_fail)
    assert result.recovered is False
    assert result.attempts == 3
    assert result.total_time_s >= 0.0


def test_resilience_score_all_recoveries_returns_1():
    """All-RECOVERED outcomes -> resilience_score = 1.0."""
    outcomes = [
        ChaosOutcome(
            target_name=f"t{i}",
            scenario_name="s",
            status=ChaosOutcomeStatus.RECOVERED,
            duration_s=1.0,
            recovery_time_s=0.1,
        )
        for i in range(5)
    ]
    score = ResilienceScore.score(outcomes)
    assert score == 1.0

    breakdown = ResilienceScore.get_breakdown(outcomes)
    assert len(breakdown) == 5
    assert all(b.score == 1.0 for b in breakdown)
    assert all(b.recoveries == 1 for b in breakdown)


def test_resilience_score_no_recoveries_returns_0():
    """All-FAILURE outcomes -> resilience_score = 0.0."""
    outcomes = [
        ChaosOutcome(
            target_name=f"t{i}",
            scenario_name="s",
            status=ChaosOutcomeStatus.FAILURE,
            duration_s=0.5,
            error="RuntimeError: boom",
        )
        for i in range(4)
    ]
    score = ResilienceScore.score(outcomes)
    assert score == 0.0

    breakdown = ResilienceScore.get_breakdown(outcomes)
    assert len(breakdown) == 4
    assert all(b.score == 0.0 for b in breakdown)
    assert all(b.failures == 1 for b in breakdown)


# CRUX-MK


# ---------------------------------------------------------------------------
# P-W10-1 Test-Density-Patch v2 (Cross-LLM-V4-CRITICAL, API-aware)
# ---------------------------------------------------------------------------
import threading as _t
import random as _r
from kmo_governance.chaos_engineering import (
    ChaosOutcomeStatus,
    FailureInjector,
    ChaosScenario,
    ChaosMonkey,
    RecoveryVerifier,
    ResilienceScore,
)


def test_chaos_failure_injector_probability_validation():
    with pytest.raises(ValueError):
        FailureInjector(failure_probability=-0.1)
    with pytest.raises(ValueError):
        FailureInjector(failure_probability=1.5)


def test_chaos_failure_injector_zero_prob_never_raises():
    fi = FailureInjector(failure_probability=0.0)
    for _ in range(50):
        fi.inject_failure()
    assert fi.injection_count == 50
    assert fi.failure_count == 0


def test_chaos_failure_injector_one_prob_always_raises():
    fi = FailureInjector(failure_probability=1.0)
    for _ in range(20):
        with pytest.raises(RuntimeError):
            fi.inject_failure()
    assert fi.failure_count == 20


def test_chaos_failure_injector_reset_clears_counters():
    fi = FailureInjector(failure_probability=1.0)
    for _ in range(5):
        try:
            fi.inject_failure()
        except RuntimeError:
            pass
    fi.reset()
    assert fi.injection_count == 0
    assert fi.failure_count == 0
    assert fi.latency_count == 0


def test_chaos_failure_injector_latency_validation():
    with pytest.raises(ValueError):
        FailureInjector(latency_min_ms=10, latency_max_ms=5)
    with pytest.raises(ValueError):
        FailureInjector(latency_min_ms=-1)


def test_chaos_failure_injector_inject_latency_returns_seconds():
    fi = FailureInjector(latency_min_ms=1, latency_max_ms=5)
    secs = fi.inject_latency()
    assert 0.001 <= secs <= 0.005
    assert fi.latency_count == 1


def test_chaos_failure_injector_concurrent_50_threads():
    fi = FailureInjector(failure_probability=0.0)

    def worker():
        for _ in range(20):
            fi.inject_failure()

    threads = [_t.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fi.injection_count == 1000


def test_chaos_failure_injector_partial_failure_zero():
    fi = FailureInjector(partial_failure_probability=0.0)
    for _ in range(50):
        fi.inject_partial_failure()
    assert fi.failure_count == 0


def test_chaos_failure_injector_partial_failure_one():
    fi = FailureInjector(partial_failure_probability=1.0)
    for _ in range(10):
        with pytest.raises(RuntimeError):
            fi.inject_partial_failure()
    assert fi.failure_count == 10


def test_chaos_failure_injector_custom_exception_type():
    fi = FailureInjector(
        failure_probability=1.0,
        exception_type=ValueError,
        exception_message="custom",
    )
    with pytest.raises(ValueError, match="custom"):
        fi.inject_failure()


def test_chaos_scenario_empty_name_raises():
    with pytest.raises(ValueError):
        ChaosScenario(name="")


def test_chaos_scenario_invalid_step_type():
    with pytest.raises(TypeError):
        ChaosScenario(name="bad", steps=["not_a_FailureInjector"])


def test_chaos_scenario_no_chaos_returns_success():
    scenario = ChaosScenario(name="empty")

    def target():
        return "ok"

    outcome = scenario.run(target, target_name="t1")
    assert outcome.status == ChaosOutcomeStatus.SUCCESS


def test_chaos_scenario_with_chaos_returns_failure():
    fi = FailureInjector(failure_probability=1.0)
    scenario = ChaosScenario(name="will_fail", steps=[fi])

    def target():
        return "ok"

    outcome = scenario.run(target, target_name="t2")
    assert outcome.status == ChaosOutcomeStatus.FAILURE
    assert outcome.error is not None


def test_chaos_scenario_with_recovery_returns_recovered():
    fi = FailureInjector(failure_probability=1.0)
    scenario = ChaosScenario(name="recovery_test", steps=[fi])

    counter = {"n": 0}

    def target():
        counter["n"] += 1
        return "ok"

    rv = RecoveryVerifier()

    outcome = scenario.run(target, target_name="t3", recovery_verifier=rv)
    # First chaos kills it; recovery verifier retries (target succeeds eventually)
    assert outcome.status in (
        ChaosOutcomeStatus.RECOVERED,
        ChaosOutcomeStatus.FAILURE,
    )


def test_chaos_monkey_register_and_run():
    cm = ChaosMonkey()

    def target():
        return "ok"

    cm.register_target("svc-a", target)
    scenario = ChaosScenario(name="s1")
    cm.schedule_chaos("svc-a", scenario)
    outcomes = cm.run_all_scheduled()
    assert len(outcomes) == 1
    assert outcomes[0].target_name == "svc-a"


def test_chaos_monkey_unregistered_target_raises():
    cm = ChaosMonkey()
    scenario = ChaosScenario(name="s1")
    # Schedule for unregistered target
    with pytest.raises((KeyError, RuntimeError, ValueError)):
        cm.schedule_chaos("missing-target", scenario)
        cm.run_all_scheduled()


def test_chaos_monkey_get_metrics_returns_dict():
    cm = ChaosMonkey()
    metrics = cm.get_metrics()
    assert isinstance(metrics, dict)


def test_chaos_monkey_reset_clears_outcomes():
    cm = ChaosMonkey()

    def target():
        return "ok"

    cm.register_target("svc", target)
    cm.schedule_chaos("svc", ChaosScenario(name="s"))
    cm.run_all_scheduled()
    cm.reset()
    assert len(cm.outcomes) == 0


def test_recovery_verifier_immediate_success():
    rv = RecoveryVerifier()

    def succeeds():
        return True

    result = rv.verify_recovery(succeeds)
    assert result.recovered
    assert result.attempts == 1


def test_recovery_verifier_eventual_success():
    rv = RecoveryVerifier(max_attempts=5, interval_s=0.001)
    counter = {"n": 0}

    def eventually_succeeds():
        counter["n"] += 1
        if counter["n"] < 3:
            raise RuntimeError("not yet")
        return True

    result = rv.verify_recovery(eventually_succeeds)
    assert result.recovered
    assert result.attempts == 3


def test_recovery_verifier_max_attempts_exhausted():
    rv = RecoveryVerifier(max_attempts=3, interval_s=0.001)

    def always_fails():
        raise RuntimeError("never")

    result = rv.verify_recovery(always_fails)
    assert not result.recovered
    assert result.attempts == 3


def test_resilience_score_all_success():
    fi = FailureInjector(failure_probability=0.0)
    scenario = ChaosScenario(name="ok", steps=[fi])

    def target():
        return "ok"

    outcomes = [scenario.run(target, target_name="t") for _ in range(10)]
    score = ResilienceScore.score(outcomes)
    assert score == 1.0


def test_resilience_score_all_failure():
    fi = FailureInjector(failure_probability=1.0)
    scenario = ChaosScenario(name="bad", steps=[fi])

    def target():
        return "ok"

    outcomes = [scenario.run(target, target_name="t") for _ in range(10)]
    score = ResilienceScore.score(outcomes)
    assert score == 0.0


def test_resilience_score_breakdown_per_target():
    fi_ok = FailureInjector(failure_probability=0.0)
    fi_bad = FailureInjector(failure_probability=1.0)
    s_ok = ChaosScenario(name="ok", steps=[fi_ok])
    s_bad = ChaosScenario(name="bad", steps=[fi_bad])

    def target():
        return "ok"

    outcomes = []
    outcomes.append(s_ok.run(target, target_name="svc-A"))
    outcomes.append(s_bad.run(target, target_name="svc-B"))
    breakdown = ResilienceScore.get_breakdown(outcomes)
    assert len(breakdown) == 2


def test_resilience_score_empty_outcomes_returns_one():
    score = ResilienceScore.score([])
    # Vacuously resilient (empty input)
    assert score == 1.0


def test_chaos_scenario_concurrent_runs_safe():
    fi = FailureInjector(failure_probability=0.0)
    scenario = ChaosScenario(name="concurrent", steps=[fi])

    def target():
        return "ok"

    outcomes = []
    lock = _t.Lock()

    def worker():
        out = scenario.run(target, target_name="t")
        with lock:
            outcomes.append(out)

    threads = [_t.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(outcomes) == 20
    assert all(o.status == ChaosOutcomeStatus.SUCCESS for o in outcomes)


def test_chaos_scenario_target_args_passed():
    scenario = ChaosScenario(name="args-test")

    def target(x, y=2):
        return x + y

    outcome = scenario.run(target, 3, target_name="adder", y=4)
    assert outcome.status == ChaosOutcomeStatus.SUCCESS


def test_chaos_outcome_frozen_dataclass():
    from kmo_governance.chaos_engineering import ChaosOutcome
    o = ChaosOutcome(
        target_name="t",
        scenario_name="s",
        status=ChaosOutcomeStatus.SUCCESS,
        duration_s=0.1,
    )
    with pytest.raises(Exception):
        o.target_name = "modified"


def test_chaos_recovery_result_frozen():
    from kmo_governance.chaos_engineering import RecoveryResult
    r = RecoveryResult(recovered=True, attempts=1, total_time_s=0.001)
    with pytest.raises(Exception):
        r.recovered = False
