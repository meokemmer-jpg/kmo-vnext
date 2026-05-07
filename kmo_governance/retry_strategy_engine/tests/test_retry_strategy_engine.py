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


# ---------------------------------------------------------------------------
# W20-P1 Patch Tests (Welle-25 Phase-18, 2026-05-07)
# Custom-Strategy-by-Name + HTTP-Status-Aware-Stop-Condition
# ---------------------------------------------------------------------------


def test_retry_config_accepts_string_strategy_name() -> None:
    """W20-P1: RetryConfig.strategy can be a plain str (custom strategy name)."""
    # Plain str is accepted at config-creation
    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy="my_custom_strategy",
    )
    assert cfg.strategy == "my_custom_strategy"
    assert isinstance(cfg.strategy, str)
    # Empty string rejected
    with pytest.raises(ValueError, match="strategy str must be non-empty"):
        RetryConfig(
            max_attempts=3,
            base_delay_s=0.001,
            max_delay_s=0.01,
            strategy="",
        )


def test_retry_engine_dispatches_to_custom_strategy_function() -> None:
    """W20-P1: compute_delay correctly dispatches to registered custom strategies."""
    cfg_default = RetryConfig(max_attempts=3, base_delay_s=1.0, max_delay_s=100.0)
    engine = RetryEngine(default_config=cfg_default)

    def cubic(attempt: int, c: RetryConfig) -> float:
        return (attempt ** 3) * c.base_delay_s

    engine.register_strategy("cubic", cubic)

    cfg = RetryConfig(
        max_attempts=5,
        base_delay_s=1.0,
        max_delay_s=1000.0,
        strategy="cubic",
    )
    # attempt=1 -> 1, attempt=2 -> 8, attempt=3 -> 27
    assert engine.compute_delay(1, cfg) == pytest.approx(1.0)
    assert engine.compute_delay(2, cfg) == pytest.approx(8.0)
    assert engine.compute_delay(3, cfg) == pytest.approx(27.0)


def test_retry_config_unknown_string_strategy_raises() -> None:
    """W20-P1: Unknown custom-strategy name raises at compute_delay time."""
    cfg_default = RetryConfig(max_attempts=3, base_delay_s=0.001, max_delay_s=0.01)
    engine = RetryEngine(default_config=cfg_default)

    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy="never_registered",
    )
    with pytest.raises(ValueError, match="unknown custom strategy"):
        engine.compute_delay(1, cfg)


def test_stop_condition_aborts_retry_early() -> None:
    """W20-P1: stop_condition returning True aborts retry-loop immediately."""
    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=lambda exc: isinstance(exc, ValueError),
    )
    engine = RetryEngine(default_config=cfg)

    counter = {"calls": 0}

    def fail_with_value_error() -> None:
        counter["calls"] += 1
        raise ValueError("non-retriable")

    outcome = engine.execute(fail_with_value_error)
    assert outcome.success is False
    assert outcome.total_attempts == 1  # aborted after 1st failure
    assert outcome.stopped_by_condition is True
    assert counter["calls"] == 1
    assert "non-retriable" in (outcome.final_error or "")


def test_stop_condition_optional_default_continues_retry() -> None:
    """W20-P1: stop_condition=None (default) -> all attempts used until max."""
    cfg = RetryConfig(
        max_attempts=4,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        # no stop_condition -> default None
    )
    engine = RetryEngine(default_config=cfg)

    def always_fail() -> None:
        raise RuntimeError("transient")

    outcome = engine.execute(always_fail)
    assert outcome.success is False
    assert outcome.total_attempts == 4  # full max_attempts used
    assert outcome.stopped_by_condition is False


def test_stop_condition_invalid_type_raises() -> None:
    """W20-P1: stop_condition must be callable or None."""
    with pytest.raises(ValueError, match="stop_condition must be callable or None"):
        RetryConfig(
            max_attempts=3,
            base_delay_s=0.001,
            max_delay_s=0.01,
            stop_condition="not_a_callable",  # type: ignore[arg-type]
        )


def test_http_status_aware_stop_condition_4xx_stops() -> None:
    """W20-P1 builtin: HTTP-403/404 (4xx not 408/429) stops retry."""
    class HttpException(Exception):
        def __init__(self, status_code: int, message: str = "") -> None:
            super().__init__(message)
            self.status_code = status_code

    cfg = RetryConfig(
        max_attempts=10,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=RetryEngine.http_status_aware_stop_condition,
    )
    engine = RetryEngine(default_config=cfg)

    counter = {"calls": 0}

    def fail_with_403() -> None:
        counter["calls"] += 1
        raise HttpException(status_code=403, message="forbidden")

    outcome = engine.execute(fail_with_403)
    assert outcome.stopped_by_condition is True
    assert outcome.total_attempts == 1
    assert counter["calls"] == 1

    # Also check 404
    counter2 = {"calls": 0}

    def fail_with_404() -> None:
        counter2["calls"] += 1
        raise HttpException(status_code=404, message="not-found")

    outcome2 = engine.execute(fail_with_404)
    assert outcome2.stopped_by_condition is True
    assert outcome2.total_attempts == 1


def test_http_status_aware_stop_condition_5xx_continues() -> None:
    """W20-P1 builtin: HTTP-503 (5xx) does NOT stop retry."""
    class HttpException(Exception):
        def __init__(self, status_code: int, message: str = "") -> None:
            super().__init__(message)
            self.status_code = status_code

    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=RetryEngine.http_status_aware_stop_condition,
    )
    engine = RetryEngine(default_config=cfg)

    counter = {"calls": 0}

    def fail_with_503() -> None:
        counter["calls"] += 1
        raise HttpException(status_code=503, message="service-unavailable")

    outcome = engine.execute(fail_with_503)
    assert outcome.stopped_by_condition is False
    assert outcome.total_attempts == 3  # full max_attempts used (5xx is retry-friendly)
    assert counter["calls"] == 3


def test_http_status_aware_stop_condition_429_continues() -> None:
    """W20-P1 builtin: HTTP-429 (rate limit) is retry-friendly with backoff."""
    class HttpException(Exception):
        def __init__(self, status_code: int, message: str = "") -> None:
            super().__init__(message)
            self.status_code = status_code

    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=RetryEngine.http_status_aware_stop_condition,
    )
    engine = RetryEngine(default_config=cfg)

    counter = {"calls": 0}

    def fail_with_429() -> None:
        counter["calls"] += 1
        raise HttpException(status_code=429, message="rate-limit")

    outcome = engine.execute(fail_with_429)
    assert outcome.stopped_by_condition is False
    assert outcome.total_attempts == 3


def test_http_status_aware_stop_condition_408_continues() -> None:
    """W20-P1 builtin: HTTP-408 (request timeout) is retry-friendly."""
    class HttpException(Exception):
        def __init__(self, status_code: int, message: str = "") -> None:
            super().__init__(message)
            self.status_code = status_code

    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=RetryEngine.http_status_aware_stop_condition,
    )
    engine = RetryEngine(default_config=cfg)

    def fail_with_408() -> None:
        raise HttpException(status_code=408, message="timeout")

    outcome = engine.execute(fail_with_408)
    assert outcome.stopped_by_condition is False
    assert outcome.total_attempts == 3


def test_http_status_aware_stop_condition_no_status_attr_continues() -> None:
    """W20-P1 builtin: Exception without status_code attribute -> conservative retry."""
    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=RetryEngine.http_status_aware_stop_condition,
    )
    engine = RetryEngine(default_config=cfg)

    def fail_no_status() -> None:
        raise RuntimeError("plain-error-no-http-status")

    outcome = engine.execute(fail_no_status)
    # Conservative: no status -> allow retry to completion
    assert outcome.stopped_by_condition is False
    assert outcome.total_attempts == 3


def test_http_status_aware_stop_condition_alt_attribute_names() -> None:
    """W20-P1 builtin: Recognizes status_code, http_status_code, code attributes."""
    class HttpStatusCodeAttr(Exception):
        def __init__(self) -> None:
            super().__init__("alt-attr")
            self.http_status_code = 401  # alternative attr name

    class CodeAttr(Exception):
        def __init__(self) -> None:
            super().__init__("alt-attr")
            self.code = 403  # third alternative

    # Both should be recognized -> stop
    assert (
        RetryEngine.http_status_aware_stop_condition(HttpStatusCodeAttr()) is True
    ), "http_status_code attribute not recognized"
    assert (
        RetryEngine.http_status_aware_stop_condition(CodeAttr()) is True
    ), "code attribute not recognized"


def test_stop_condition_callback_exception_does_not_break_loop() -> None:
    """W20-P1: If stop_condition itself raises, treat as 'do not stop' (continue)."""

    def buggy_cond(exc: Exception) -> bool:
        raise RuntimeError("buggy stop_condition")

    cfg = RetryConfig(
        max_attempts=3,
        base_delay_s=0.001,
        max_delay_s=0.01,
        strategy=RetryStrategy.CONSTANT,
        stop_condition=buggy_cond,
    )
    engine = RetryEngine(default_config=cfg)

    def always_fail() -> None:
        raise ValueError("transient")

    outcome = engine.execute(always_fail)
    # Buggy cond -> treated as "no stop" -> full retries
    assert outcome.stopped_by_condition is False
    assert outcome.total_attempts == 3


# CRUX-MK
