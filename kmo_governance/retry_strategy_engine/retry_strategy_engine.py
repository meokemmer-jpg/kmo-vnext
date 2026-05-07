# [CRUX-MK]
"""KMO Retry-Strategy-Engine [CRUX-MK].

Welle-20 Phase-13.2 Modul-2/3: Generalized Retry mit pluggable Strategien.

Bio-Aequivalent: Wundheilungs-Phasen-Kaskade (Haemostase / Inflammation / Proliferation
isomorph zu linear / exponential / fibonacci Backoff).

Pre/Post-Conditions sind als Dataclass-`__post_init__`-Validatoren + Method-Docstrings
codiert. Nur stdlib (random + time + threading + dataclasses + enum).

Welle-25 Phase-18 W20-P1 Patch (2026-05-07):
- RetryConfig.strategy akzeptiert nun RetryStrategy | str (custom strategy by name).
- HTTP-Status-Aware-Stop-Condition: RetryConfig.stop_condition optional callable,
  bei True wird Retry-Loop sofort abgebrochen (nicht-retriable Errors wie 4xx).
"""

from __future__ import annotations

import enum
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union


# ---------------------------------------------------------------------------
# Strategy Enum
# ---------------------------------------------------------------------------


class RetryStrategy(str, enum.Enum):
    """Built-in Retry-Strategies (delay-curve dispatch)."""

    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    FIBONACCI = "fibonacci"
    CONSTANT = "constant"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryAttempt:
    """Single retry attempt outcome.

    Pre-Conditions:
        attempt_number >= 1
        delay_s >= 0
        timestamp >= 0

    Post-Conditions:
        Frozen / hashable.
    """

    attempt_number: int
    delay_s: float
    timestamp: float
    error: Optional[str] = None
    success: bool = False

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")
        if self.delay_s < 0:
            raise ValueError("delay_s must be >= 0")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")


@dataclass(frozen=True)
class RetryConfig:
    """Retry configuration.

    Pre-Conditions:
        max_attempts >= 1
        base_delay_s > 0
        max_delay_s >= base_delay_s
        0 <= jitter_factor <= 1
        strategy: RetryStrategy enum value OR str (custom strategy name registered
            via RetryEngine.register_strategy()).
        stop_condition: optional Callable[[Exception], bool]. If returns True for
            an exception, retry-loop aborts immediately (no further retries).
            Use-case: HTTP-401/403/404 should NOT be retried.

    Post-Conditions:
        Frozen / hashable (note: stop_condition Callable is part of identity).
    """

    max_attempts: int = 3
    base_delay_s: float = 0.1
    max_delay_s: float = 60.0
    strategy: Union[RetryStrategy, str] = RetryStrategy.EXPONENTIAL
    jitter_factor: float = 0.0
    stop_condition: Optional[Callable[[Exception], bool]] = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_s <= 0:
            raise ValueError("base_delay_s must be > 0")
        if self.max_delay_s < self.base_delay_s:
            raise ValueError("max_delay_s must be >= base_delay_s")
        if not (0.0 <= self.jitter_factor <= 1.0):
            raise ValueError("jitter_factor must be in [0.0, 1.0]")
        # Strategy: must be RetryStrategy enum OR non-empty string
        if not isinstance(self.strategy, (RetryStrategy, str)):
            raise ValueError(
                "strategy must be a RetryStrategy enum or str (custom strategy name)"
            )
        if isinstance(self.strategy, str) and not isinstance(self.strategy, RetryStrategy):
            if not self.strategy:
                raise ValueError("strategy str must be non-empty")
        # stop_condition: must be callable or None
        if self.stop_condition is not None and not callable(self.stop_condition):
            raise ValueError("stop_condition must be callable or None")


@dataclass(frozen=True)
class RetryOutcome:
    """Aggregated outcome of a full retry-execution.

    Pre-Conditions:
        total_attempts >= 0
        total_elapsed_s >= 0

    Post-Conditions:
        Frozen / hashable. attempts is a tuple (immutable).
        stopped_by_condition: True if retry-loop aborted via stop_condition
            (vs reached max_attempts naturally).
    """

    success: bool
    total_attempts: int
    total_elapsed_s: float
    attempts: tuple[RetryAttempt, ...] = field(default_factory=tuple)
    final_error: Optional[str] = None
    result: Any = None
    stopped_by_condition: bool = False

    def __post_init__(self) -> None:
        if self.total_attempts < 0:
            raise ValueError("total_attempts must be >= 0")
        if self.total_elapsed_s < 0:
            raise ValueError("total_elapsed_s must be >= 0")


# ---------------------------------------------------------------------------
# Built-in Strategy Functions
# ---------------------------------------------------------------------------


def _linear_delay(attempt: int, config: RetryConfig) -> float:
    """Linear backoff: attempt * base_delay (1, 2, 3, 4, ...)."""
    return float(attempt) * config.base_delay_s


def _exponential_delay(attempt: int, config: RetryConfig) -> float:
    """Exponential backoff: base * 2^(attempt-1) (1, 2, 4, 8, ...)."""
    return config.base_delay_s * (2.0 ** (attempt - 1))


def _fibonacci_delay(attempt: int, config: RetryConfig) -> float:
    """Fibonacci backoff: base * fib(attempt) (1, 1, 2, 3, 5, 8, ...)."""
    if attempt <= 0:
        return 0.0
    a, b = 1, 1
    for _ in range(attempt - 1):
        a, b = b, a + b
    return float(a) * config.base_delay_s


def _constant_delay(attempt: int, config: RetryConfig) -> float:
    """Constant delay: always base_delay_s (independent of attempt)."""
    return config.base_delay_s


_BUILTIN_STRATEGIES: dict[RetryStrategy, Callable[[int, RetryConfig], float]] = {
    RetryStrategy.LINEAR: _linear_delay,
    RetryStrategy.EXPONENTIAL: _exponential_delay,
    RetryStrategy.FIBONACCI: _fibonacci_delay,
    RetryStrategy.CONSTANT: _constant_delay,
}


# ---------------------------------------------------------------------------
# Retry Engine
# ---------------------------------------------------------------------------


class RetryEngine:
    """Generalized Retry-Engine mit pluggable Strategien.

    Pre-Conditions:
        default_config: valid RetryConfig instance.

    Post-Conditions:
        Thread-safe via internal RLock.
        Built-in strategies (LINEAR / EXPONENTIAL / FIBONACCI / CONSTANT) verfuegbar.
        Custom strategies via register_strategy() registrierbar (Name -> Callable).
        Custom strategies sind ueber RetryConfig.strategy=<name-str> nutzbar (W20-P1).
    """

    def __init__(self, default_config: RetryConfig) -> None:
        if not isinstance(default_config, RetryConfig):
            raise ValueError("default_config must be a RetryConfig instance")
        self._default_config = default_config
        self._custom_strategies: dict[str, Callable[[int, RetryConfig], float]] = {}
        self._lock = threading.RLock()

    @property
    def default_config(self) -> RetryConfig:
        """Snapshot of the default config (frozen)."""
        with self._lock:
            return self._default_config

    def register_strategy(
        self,
        name: str,
        fn: Callable[[int, RetryConfig], float],
    ) -> None:
        """Register a custom delay-strategy by name.

        Pre-Conditions:
            name: non-empty string, not collisioning with built-in RetryStrategy values.
            fn: callable (attempt: int, config: RetryConfig) -> float (>= 0).

        Post-Conditions:
            self._custom_strategies[name] = fn.
            Custom strategy ist nun via RetryConfig(strategy=name) referenzierbar.
        """
        if not name:
            raise ValueError("name must be non-empty")
        if not callable(fn):
            raise ValueError("fn must be callable")
        # Avoid collision with built-in enum values
        builtin_values = {s.value for s in RetryStrategy}
        if name in builtin_values:
            raise ValueError(
                f"name '{name}' collides with built-in RetryStrategy"
            )
        with self._lock:
            self._custom_strategies[name] = fn

    @staticmethod
    def http_status_aware_stop_condition(exception: Exception) -> bool:
        """Built-in stop_condition for HTTP-status-aware retries.

        Returns True (=> STOP retry) for non-retriable HTTP status codes:
            - 4xx (Client errors) EXCEPT 408 (Request Timeout) and 429 (Rate Limit)
              which are retry-friendly.

        Returns False (=> CONTINUE retry) for:
            - 5xx (Server errors)
            - 408 (Timeout, transient)
            - 429 (Rate Limit, retry-friendly with backoff)
            - Any exception without status_code attribute (be conservative, retry)

        Pre-Conditions:
            exception: an Exception instance, optionally with status_code attribute
                (int). Common attribute names checked: status_code, http_status_code,
                code (in that order).

        Post-Conditions:
            Returns bool deterministically.
        """
        # Try common attribute names for HTTP status
        status: Optional[int] = None
        for attr in ("status_code", "http_status_code", "code"):
            value = getattr(exception, attr, None)
            if isinstance(value, int):
                status = value
                break

        if status is None:
            # No status info -> be conservative, allow retry
            return False

        # 4xx EXCEPT 408 / 429 -> stop (non-retriable client error)
        if 400 <= status < 500 and status not in (408, 429):
            return True

        # 5xx, 408, 429, others -> continue retrying
        return False

    def compute_delay(self, attempt: int, config: RetryConfig) -> float:
        """Compute the delay for a given attempt under a given config.

        Pre-Conditions:
            attempt >= 1
            config: valid RetryConfig (strategy: RetryStrategy enum or registered str)

        Post-Conditions:
            return value >= 0
            return value <= config.max_delay_s (cap enforced)
            if jitter_factor > 0: delay scaled by random.uniform(1-j, 1+j)
            Resolves config.strategy via:
                1. RetryStrategy enum -> _BUILTIN_STRATEGIES dispatch
                2. str -> _custom_strategies dispatch
                3. unknown -> ValueError
        """
        if attempt < 1:
            raise ValueError("attempt must be >= 1")

        # Resolve strategy: RetryStrategy enum -> builtin, plain str -> custom
        with self._lock:
            if isinstance(config.strategy, RetryStrategy):
                # Enum: lookup in _BUILTIN_STRATEGIES (always present)
                delay_fn = _BUILTIN_STRATEGIES[config.strategy]
            elif isinstance(config.strategy, str):
                # Plain str: must be a registered custom strategy name
                if config.strategy in self._custom_strategies:
                    delay_fn = self._custom_strategies[config.strategy]
                else:
                    raise ValueError(
                        f"unknown custom strategy: '{config.strategy}'. "
                        f"Registered: {list(self._custom_strategies.keys())}"
                    )
            else:
                raise ValueError(
                    f"unknown strategy type: {type(config.strategy).__name__}"
                )

        raw_delay = float(delay_fn(attempt, config))
        if raw_delay < 0:
            raw_delay = 0.0

        # Apply jitter (multiplicative, symmetric around 1.0)
        if config.jitter_factor > 0.0:
            jitter_lo = 1.0 - config.jitter_factor
            jitter_hi = 1.0 + config.jitter_factor
            raw_delay *= random.uniform(jitter_lo, jitter_hi)

        # Enforce max_delay_s cap
        return min(raw_delay, config.max_delay_s)

    def execute(
        self,
        callable_: Callable[[], Any],
        config: Optional[RetryConfig] = None,
        on_retry: Optional[Callable[[RetryAttempt], None]] = None,
    ) -> RetryOutcome:
        """Execute callable_ with retries per config.

        Pre-Conditions:
            callable_: callable () -> Any.
            config: optional RetryConfig (None -> use default_config).
            on_retry: optional callback fn(RetryAttempt) -> None.

        Post-Conditions:
            Returns RetryOutcome with success/total_attempts/total_elapsed_s/attempts.
            On final failure: RetryOutcome.success == False, final_error set.
            On success: RetryOutcome.success == True, result set.
            Each attempt produces a RetryAttempt entry in outcome.attempts.
            on_retry (if provided) is called AFTER each non-final failed attempt.
            If config.stop_condition returns True for an exception, retry-loop
            aborts immediately and outcome.stopped_by_condition = True.
        """
        if not callable(callable_):
            raise ValueError("callable_ must be callable")
        cfg = config if config is not None else self._default_config

        attempts: list[RetryAttempt] = []
        start = time.monotonic()
        last_error: Optional[str] = None
        result: Any = None
        success = False
        stopped_by_condition = False

        for attempt_num in range(1, cfg.max_attempts + 1):
            # Compute delay before this attempt (attempt 1 -> no delay yet)
            if attempt_num > 1:
                delay = self.compute_delay(attempt_num - 1, cfg)
                time.sleep(delay)
            else:
                delay = 0.0

            timestamp = time.monotonic() - start
            try:
                result = callable_()
                attempt_record = RetryAttempt(
                    attempt_number=attempt_num,
                    delay_s=delay,
                    timestamp=timestamp,
                    error=None,
                    success=True,
                )
                attempts.append(attempt_record)
                success = True
                break
            except Exception as exc:  # noqa: BLE001 - capture all retry-eligible errors
                err_msg = f"{type(exc).__name__}: {exc}"
                last_error = err_msg
                attempt_record = RetryAttempt(
                    attempt_number=attempt_num,
                    delay_s=delay,
                    timestamp=timestamp,
                    error=err_msg,
                    success=False,
                )
                attempts.append(attempt_record)

                # W20-P1: stop_condition check BEFORE on_retry callback.
                # If stop_condition signals "do not retry", abort the loop.
                if cfg.stop_condition is not None:
                    try:
                        should_stop = bool(cfg.stop_condition(exc))
                    except Exception:  # noqa: BLE001 - never fail loop on bad cond
                        should_stop = False
                    if should_stop:
                        stopped_by_condition = True
                        break

                # Call on_retry callback for non-final failures
                if on_retry is not None and attempt_num < cfg.max_attempts:
                    try:
                        on_retry(attempt_record)
                    except Exception:  # noqa: BLE001 - never fail the retry-loop on callback
                        pass

        total_elapsed_s = time.monotonic() - start
        return RetryOutcome(
            success=success,
            total_attempts=len(attempts),
            total_elapsed_s=total_elapsed_s,
            attempts=tuple(attempts),
            final_error=None if success else last_error,
            result=result if success else None,
            stopped_by_condition=stopped_by_condition,
        )


# CRUX-MK
