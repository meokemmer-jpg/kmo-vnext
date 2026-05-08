# [CRUX-MK]
"""KPM-Observability-Layer (Welle-35 Phase-28 Bio-Pattern-Lift, 17. Lift).

Bio-Aequivalent: Vagusnerv (Nervus Vagus) auf KPM-Trading-Metriken.
Pattern-Quelle: kmo_governance.observability_layer (Welle-9, Hotel-Domain,
Counter + Gauge + Histogram + MetricsRegistry + Prometheus-Compliance).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Trading-Metriken (kontinuierlich): P&L, Sharpe-Ratio, Drawdown, Latency-p99,
  Slippage-Buckets, trades_total (Counter), current_position_size (Gauge),
  kelly_fraction (Gauge)
- Thread-safe Counter / Gauge / Histogram mit per-metric Lock-Striping
- Prometheus-Text-Format-Export fuer externes Monitoring (Grafana, etc.)
- Severity-Stufen NICHT noetig (Metriken sind kontinuierliche Skalare)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern (Counter/Gauge/Histogram +
thread-safe Aggregation + Prometheus-Compliance), andere Domaene
(Trading-Metriken statt Hotel-Service-Metriken).

Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Pattern-Inspiration:
- observability_layer (Hotel-Domain): Counter + Gauge + Histogram + MetricsRegistry
- Prometheus-Standard: https://prometheus.io/docs/practices/naming/
- Vagusnerv: parasympathische Multi-Sensor-Aggregation (Heart-Rate-Variability,
  Digestion-State, Breathing-Rate) - kontinuierliche Steady-State-Regulation

NO external Dependencies (stdlib-only): threading, time, dataclasses, enum, typing.

Public API:
    from kmo_governance.kpm_observability_layer import (
        MetricType,
        TradingMetric,
        KPMObservabilityLayer,
    )

Usage:
    obs = KPMObservabilityLayer()
    obs.register_metric("trades_total", MetricType.COUNTER,
                        description="Total trades executed", labels=("strategy",))
    obs.register_metric("current_position_size", MetricType.GAUGE,
                        description="Current open position EUR")
    obs.register_metric("slippage_buckets", MetricType.HISTOGRAM,
                        description="Slippage distribution in bps")

    obs.inc_counter("trades_total", strategy="kelly_0.4")
    obs.set_gauge("current_position_size", 12500.0)
    obs.observe_histogram("slippage_buckets", 0.015)

    snap = obs.get_metric("trades_total", strategy="kelly_0.4")
    prom_text = obs.export_prometheus()
"""
from .kpm_observability_layer import (
    KPMObservabilityLayer,
    MetricType,
    TradingMetric,
)

__all__ = [
    "KPMObservabilityLayer",
    "MetricType",
    "TradingMetric",
]

# CRUX-MK
