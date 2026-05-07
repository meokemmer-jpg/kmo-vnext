# [CRUX-MK]
"""Tests for retry_strategy_engine [CRUX-MK].

Welle-20 Phase-13.2: 14+ pflicht-tests fuer alle Strategien + Edge-Cases.
"""

from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.retry_strategy_engine import (
    RetryAttempt,
    RetryConfig,
    RetryEngine,
    RetryOutcome,
    RetryStrategy,
)


# ---------------------------------------------------------------------------
# Config Validation Tests
# ---------------------------------------------------------------------------


def test_config_validation() -> None:
    """RetryConfig enforces all pre-conditions."""
    # Valid baseline
    cfg = RetryConfig(max_attempts=3, base_delay_s=0.1, max_delay_s=5.0)
    assert cfg.max_attempts == 3

    # max_attempts must be >= 1
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        RetryConfig(max_attempts=0)

    # base_delay_s must be > 0
    with pytest.raises(ValueError, match="base_delay_s must be > 0"):
        RetryConfig(base_delay_s=0)
    with pytest.raises(ValueError, match="base_delay_s must be > 0"):
        RetryConfig(base_delay_s=-1.0)

    # max_delay_s must be >= base_delay_s
    with pytest.raises(ValueError, match="max_delay_s must be >= base_delay_s"):
        RetryConfig(base_delay_s=10.0, max_delay_s=5.0)

    # jitter_factor must be in [0, 1]
    with pytest.raises(ValueError, match=r"jitter_factor must be in \[0\.0, 1\.0\]"):
        RetryConfig(jitter_factor=-0.1)
    with pytest.raises(ValueError, match=r"jitter_factor must be in \[0\.0, 1\.0\]"):
        RetryConfig(jitter_factor=1.5)


# ---------------------------------------------------------------------------
# Built-in Strategy Delay-Computation Tests
# ---------------------------------------------------------------------------


def test_linear_delay_computation() -> None:
    """LINEAR: attempt 1->base, attempt 2->2*base, attempt 3->3*base, attempt 4->4*base."""
    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=0.5,
        max_delay_s=100.0,
        strategy=RetryStrategy.LINEAR,
    )
    engine = RetryEngine(default_config=cfg)
    assert engine.compute_delay(1, cfg) == pytest.approx(0.5)
    assert engine.compute_delay(2, cfg) == pytest.approx(1.0)
    assert engine.compute_delay(3, cfg) == pytest.approx(1.5)
    assert engine.compute_delay(4, cfg) == pytest.approx(2.0)


def test_exponential_delay_computation() -> None:
    """EXPONENTIAL: base * 2^(attempt-1) (1, 2, 4, 8, ...) with cap."""
    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=1.0,
        max_delay_s=100.0,
        strategy=RetryStrategy.EXPONENTIAL,
    )
    engine = RetryEngine(default_config=cfg)
    assert engine.compute_delay(1, cfg) == pytest.approx(1.0)
    assert engine.compute_delay(2, cfg) == pytest.approx(2.0)
    assert engine.compute_delay(3, cfg) == pytest.approx(4.0)
    assert engine.compute_delay(4, cfg) == pytest.approx(8.0)
    assert engine.compute_delay(5, cfg) == pytest.approx(16.0)


def test_fibonacci_delay_computation() -> None:
    """FIBONACCI: base * fib(attempt) (1, 1, 2, 3, 5, 8, ...)."""
    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=1.0,
        max_delay_s=100.0,
        strategy=RetryStrategy.FIBONACCI,
    )
    engine = RetryEngine(default_config=cfg)
    assert engine.compute_delay(1, cfg) == pytest.approx(1.0)
    assert engine.compute_delay(2, cfg) == pytest.approx(1.0)
    assert engine.compute_delay(3, cfg) == pytest.approx(2.0)
    assert engine.compute_delay(4, cfg) == pytest.approx(3.0)
    assert engine.compute_delay(5, cfg) == pytest.approx(5.0)
    assert engine.compute_delay(6, cfg) == pytest.approx(8.0)


def test_constant_delay_computation() -> None:
    """CONSTANT: same base_delay_s independent of attempt-num."""
    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=2.5,
        max_delay_s=100.0,
        strategy=RetryStrategy.CONSTANT,
    )
    engine = RetryEngine(default_config=cfg)
    for attempt in range(1, 8):
        assert engine.compute_delay(attempt, cfg) == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Cap & Jitter Tests
# ---------------------------------------------------------------------------


def test_max_delay_cap_enforced() -> None:
    """Even with EXPONENTIAL growth, delay is capped at max_delay_s."""
    cfg = RetryConfig(
        max_attempts=20,
        base_delay_s=1.0,
        max_delay_s=10.0,
        strategy=RetryStrategy.EXPONENTIAL,
    )
    engine = RetryEngine(default_config=cfg)
    # attempt=10 -> 1 * 2^9 = 512, but capped to 10
    delay = engine.compute_delay(10, cfg)
    assert delay <= 10.0
    assert delay == pytest.approx(10.0)


def test_jitter_within_bounds() -> None:
    """1000 samples: all delays must be in [base*(1-j), base*(1+j)] (with cap).

    Jitter factor 0.2 on EXPONENTIAL attempt=1 (base=1.0, no cap-effect):
    expected range [0.8, 1.2].
    """
    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=1.0,
        max_delay_s=100.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_factor=0.2,
    )
    engine = RetryEngine(default_config=cfg)
    samples = [engine.compute_delay(1, cfg) for _ in range(1000)]
    # All in [0.8, 1.2] (jitter symmetric around base=1.0)
    for s in samples:
        assert 0.8 <= s <= 1.2, f"jitter sample {s} outside [0.8, 1.2]"
    # Also: not all equal (non-zero jitter actually applied)
    assert min(samples) < max(samples), "jitter has no effect; all samples equal"


# ---------------------------------------------------------------------------
# Execute Tests
# ---------------------------------------------------------------------------


def test_execute_success_first_attempt() -> None:
    """Callable that succeeds on first try -> total_attempts=1, success=True."""
    cfg = RetryConfig(max_attempts=3, base_delay_s=0.001, max_delay_s=0.01)
    engine = RetryEngine(default_config=cfg)

    def succeed() -> str:
        return "ok"

    outcome = engine.execute(succeed)
    assert isinstance(outcome, RetryOutcome)
    assert outcome.success is True
    assert outcome.total_attempts == 1
    assert outcome.result == "ok"
    assert outcome.final_error is None
    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].success is True
    assert outcome.attempts[0].error is None


def test_execute_success_after_retries() -> None:
    """Callable that fails twice then succeeds -> total_attempts=3, success=True."""
    cfg = RetryConfig(
        max_attempts=5,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
    )
    engine = RetryEngine(default_config=cfg)

    counter = {"calls": 0}

    def flaky() -> str:
        counter["calls"] += 1
        if counter["calls"] < 3:
            raise RuntimeError(f"transient-fail-{counter['calls']}")
        return "recovered"

    outcome = engine.execute(flaky)
    assert outcome.success is True
    assert outcome.total_attempts == 3
    assert outcome.result == "recovered"
    assert outcome.final_error is None
    assert len(outcome.attempts) == 3
    assert outcome.attempts[0].error is not None
    assert outcome.attempts[1].error is not None
    assert outcome.attempts[2].error is None
    assert outcome.attempts[2].success is True


def test_execute_max_attempts_exceeded() -> None:
    """Callable that always fails -> total_attempts=max, success=False."""
    cfg = RetryConfig(
        max_attempts=4,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
    )
    engine = RetryEngine(default_config=cfg)

    def always_fail() -> None:
        raise ValueError("permanent-fail")

    outcome = engine.execute(always_fail)
    assert outcome.success is False
    assert outcome.total_attempts == 4
    assert outcome.result is None
    assert outcome.final_error is not None
    assert "permanent-fail" in outcome.final_error
    assert "ValueError" in outcome.final_error
    assert len(outcome.attempts) == 4
    assert all(a.success is False for a in outcome.attempts)


# ---------------------------------------------------------------------------
# Custom Strategies & Immutability Tests
# ---------------------------------------------------------------------------


def test_register_custom_strategy() -> None:
    """Custom strategy can be registered and then used via RetryStrategy."""
    cfg = RetryConfig(
        max_attempts=5,
        base_delay_s=1.0,
        max_delay_s=100.0,
        strategy=RetryStrategy.LINEAR,
    )
    engine = RetryEngine(default_config=cfg)

    # Define a custom "polynomial" strategy: attempt^3 * base
    def cubic(attempt: int, c: RetryConfig) -> float:
        return (attempt ** 3) * c.base_delay_s

    engine.register_strategy("cubic", cubic)
    assert "cubic" in engine._custom_strategies

    # Cannot register collision with built-in
    with pytest.raises(ValueError, match="collides with built-in"):
        engine.register_strategy("linear", cubic)
    with pytest.raises(ValueError, match="collides with built-in"):
        engine.register_strategy("exponential", cubic)

    # Cannot register empty name
    with pytest.raises(ValueError, match="non-empty"):
        engine.register_strategy("", cubic)

    # Cannot register non-callable
    with pytest.raises(ValueError, match="callable"):
        engine.register_strategy("bad_strat", "not_a_callable")  # type: ignore[arg-type]


def test_outcome_frozen_immutability() -> None:
    """RetryAttempt + RetryConfig + RetryOutcome are frozen dataclasses."""
    cfg = RetryConfig()
    attempt = RetryAttempt(attempt_number=1, delay_s=0.0, timestamp=0.0)
    outcome = RetryOutcome(
        success=True,
        total_attempts=1,
        total_elapsed_s=0.001,
        attempts=(attempt,),
    )

    # Frozen: assignment must fail
    with pytest.raises((AttributeError, Exception)):
        cfg.max_attempts = 99  # type: ignore[misc]
    with pytest.raises((AttributeError, Exception)):
        attempt.attempt_number = 42  # type: ignore[misc]
    with pytest.raises((AttributeError, Exception)):
        outcome.success = False  # type: ignore[misc]

    # Tuples are immutable
    assert isinstance(outcome.attempts, tuple)


def test_concurrent_retry_executions_thread_safe() -> None:
    """Concurrent execute() calls remain thread-safe (no race conditions)."""
    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
    )
    engine = RetryEngine(default_config=cfg)

    n_threads = 10
    counters = [{"calls": 0, "outcome": None} for _ in range(n_threads)]
    barrier = threading.Barrier(n_threads)

    def worker(idx: int) -> None:
        barrier.wait()  # synchronize start

        def flaky() -> int:
            counters[idx]["calls"] += 1
            if counters[idx]["calls"] < 2:
                raise RuntimeError("flaky-fail")
            return idx

        counters[idx]["outcome"] = engine.execute(flaky)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads succeeded with exactly 2 attempts each
    for i, c in enumerate(counters):
        outcome = c["outcome"]
        assert outcome is not None
        assert outcome.success is True
        assert outcome.total_attempts == 2
        assert outcome.result == i


def test_on_retry_callback_invoked() -> None:
    """on_retry callback is called for each non-final failed attempt."""
    cfg = RetryConfig(
        max_attempts=4,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
    )
    engine = RetryEngine(default_config=cfg)

    callback_log: list[RetryAttempt] = []

    def on_retry_cb(attempt: RetryAttempt) -> None:
        callback_log.append(attempt)

    counter = {"calls": 0}

    def fail_then_succeed() -> str:
        counter["calls"] += 1
        if counter["calls"] < 3:
            raise RuntimeError("retry-me")
        return "done"

    outcome = engine.execute(fail_then_succeed, on_retry=on_retry_cb)
    # 2 failed attempts before success on 3rd -> callback invoked twice
    # (after non-final failures; not after final-success-attempt)
    assert outcome.success is True
    assert outcome.total_attempts == 3
    assert len(callback_log) == 2
    assert callback_log[0].attempt_number == 1
    assert callback_log[0].success is False
    assert callback_log[1].attempt_number == 2
    assert callback_log[1].success is False


def test_compute_delay_invalid_attempt() -> None:
    """compute_delay(attempt < 1) raises ValueError."""
    cfg = RetryConfig()
    engine = RetryEngine(default_config=cfg)
    with pytest.raises(ValueError, match="attempt must be >= 1"):
        engine.compute_delay(0, cfg)
    with pytest.raises(ValueError, match="attempt must be >= 1"):
        engine.compute_delay(-1, cfg)


def test_engine_init_validates_config() -> None:
    """RetryEngine __init__ validates default_config type."""
    with pytest.raises(ValueError, match="must be a RetryConfig instance"):
        RetryEngine(default_config="not_a_config")  # type: ignore[arg-type]


def test_execute_uses_per_call_config_override() -> None:
    """execute(callable, config=X) uses X instead of default_config."""
    default_cfg = RetryConfig(max_attempts=5, base_delay_s=0.001, max_delay_s=0.01)
    override_cfg = RetryConfig(max_attempts=2, base_delay_s=0.001, max_delay_s=0.01)
    engine = RetryEngine(default_config=default_cfg)

    def always_fail() -> None:
        raise RuntimeError("nope")

    outcome = engine.execute(always_fail, config=override_cfg)
    assert outcome.total_attempts == 2  # override_cfg.max_attempts, not default's 5


# CRUX-MK
