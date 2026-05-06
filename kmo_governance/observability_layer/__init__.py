# [CRUX-MK]
"""KMO Observability-Layer (Welle-10 Phase-6).

Bio-Aequivalent: Vagusnerv (peripheres Sensing + Centralisierung in ZNS).
Centralisiert:
  - Counter-Metrics (events, errors, duration)
  - Tracing-Spans (Request-Flow durch Layer)
  - Health-Checks (Per-Module-Status)

Zero externe Dependencies (nur stdlib). Prometheus-kompatibles Output-Format.
"""
from .observability_layer import (
    Counter,
    Gauge,
    Histogram,
    HealthCheckRegistry,
    HealthStatus,
    LockStripedMetricsRegistry,
    MetricsRegistry,
    PrometheusComplianceValidator,
    Span,
    Tracer,
)

__all__ = [
    "Counter",
    "Gauge",
    "Histogram",
    "HealthCheckRegistry",
    "HealthStatus",
    "LockStripedMetricsRegistry",
    "MetricsRegistry",
    "PrometheusComplianceValidator",
    "Span",
    "Tracer",
]

# CRUX-MK
