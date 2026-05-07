# [CRUX-MK]
"""KMO Retry-Strategy-Engine [CRUX-MK].

Welle-20 Phase-13.2 Modul: Generalized Retry-Engine mit pluggable Strategien.

Bio-Aequivalent: Wundheilungs-Phasen-Kaskade.
Drei Phasen Haemostase/Inflammation/Proliferation isomorph zu
linear/exponential/fibonacci-Backoff. Body waehlt adaptiv je nach
Wundgroesse die richtige Strategie.

Module-2/3 in Welle-20.

Pattern-Inspiration:
- saga_step_orchestrator (Multi-Step-State-Tracking, RetryPolicy frozen Dataclass)
- adaptive_throttle (Strategy-Pattern via Enum + dispatching)

CRUX-Bindung:
- K_0: max_attempts + max_delay_s Cap verhindert Runaway-Retries (Cost-Containment)
- Q_0: pluggable Strategien erhoehen Wiederverwendbarkeit + Test-Coverage
- I_min: 4 Strategien + custom-register als minimale strukturierte API
- W_0: Jitter randomisiert Concurrent-Retry-Stampedes (Thundering-Herd-Schutz)

Usage:
    >>> from retry_strategy_engine import RetryEngine, RetryConfig, RetryStrategy
    >>> config = RetryConfig(max_attempts=5, base_delay_s=0.1, max_delay_s=10.0,
    ...                       strategy=RetryStrategy.EXPONENTIAL, jitter_factor=0.2)
    >>> engine = RetryEngine(default_config=config)
    >>> outcome = engine.execute(lambda: external_api_call())
    >>> if outcome.success:
    ...     print(f"Succeeded after {outcome.total_attempts} attempts")

Public API:
    - RetryStrategy (Enum)
    - RetryAttempt (frozen Dataclass)
    - RetryConfig (frozen Dataclass)
    - RetryOutcome (frozen Dataclass)
    - RetryEngine (Hauptklasse)
"""
from __future__ import annotations

from .retry_strategy_engine import (
    RetryAttempt,
    RetryConfig,
    RetryEngine,
    RetryOutcome,
    RetryStrategy,
)

__all__ = [
    "RetryAttempt",
    "RetryConfig",
    "RetryEngine",
    "RetryOutcome",
    "RetryStrategy",
]

# CRUX-MK
