# [CRUX-MK]
"""KPM-Observability-Layer (Welle-35 Phase-28 Bio-Pattern-Lift, 17. Lift).

Bio-Aequivalent: Vagusnerv (Nervus Vagus) auf KPM-Trading-Metriken.
Pattern-Quelle: kmo_governance.observability_layer (Welle-9, Hotel-Domain,
Counter + Gauge + Histogram + MetricsRegistry + Prometheus-Compliance).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Trading-Metriken: P&L, Sharpe-Ratio, Drawdown, Latency-p99, Slippage,
  trades_total, current_position_size, kelly_fraction
- Thread-safe Counter / Gauge / Histogram (per-metric Lock-Striping)
- Prometheus-Text-Format-Export fuer externes Monitoring

Bio-Mapping (Vagusnerv -> Trading-Observability):
    Counter (events)           -> Counter (trades_total)              -> Sympathetic-Activation-Pulse
    Gauge (current_state)      -> Gauge (current_position_size)       -> Parasympathetic-Steady-State
    Histogram (latency_buckets)-> Histogram (slippage_buckets)        -> Heart-Rate-Variability-Distribution
    Lock-Striping per metric   -> Lock-Striping per metric            -> Multi-Receptor-Independence

NO external Dependencies (stdlib-only): threading, time, dataclasses, enum, typing.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Public Enums + Dataclasses
# ---------------------------------------------------------------------------
class MetricType(Enum):
    """Drei zugelassene Metric-Typen (Prometheus-konform)."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(frozen=True)
class TradingMetric:
    """Immutable Snapshot eines Trading-Metric-Werts.

    Pre:
      - metric_name non-empty
      - metric_type in MetricType
      - labels: tuple-of-tuples (key, value) -- Hashable + frozen-friendly
      - timestamp: epoch seconds (float)

    Post:
      - frozen, kann in Sets / als Dict-Key verwendet werden
      - eq + hash deterministisch
    """

    metric_name: str
    metric_type: MetricType
    value: float
    labels: tuple[tuple[str, str], ...] = ()
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Internal Storage Structures (private, not exported)
# ---------------------------------------------------------------------------
@dataclass
class _MetricSpec:
    """Registrierung einer Metric (interner State-Holder)."""

    metric_name: str
    metric_type: MetricType
    description: str
    labels: tuple[str, ...]
    buckets: tuple[float, ...] = ()  # nur fuer HISTOGRAM
    # je-Label-Kombination ein Wert (key = sorted-label-values-tuple)
    values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    # je-Label-Kombination ein Bucket-Counter (nur fuer HISTOGRAM)
    bucket_counts: dict[tuple[tuple[str, str], ...], dict[float, int]] = field(
        default_factory=dict
    )
    histogram_sum: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    histogram_count: dict[tuple[tuple[str, str], ...], int] = field(default_factory=dict)
    last_update: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main Class: KPMObservabilityLayer
# ---------------------------------------------------------------------------
class KPMObservabilityLayer:
    """Thread-safe Observability-Layer fuer KPM-Trading-Metriken.

    Pre:
      - default_buckets sortiert ascending, alle Werte > 0

    Post:
      - register_metric idempotent fuer gleiche Spec, raises bei Konflikt
      - inc_counter / set_gauge / observe_histogram type-checked
      - per-metric Lock-Striping (Multi-Receptor-Independence)
      - Prometheus-Text-Export-Format-konform

    Bio-Aequivalent: Vagusnerv mit kontinuierlichem Multi-Sensor-Input
    (Heart-Rate, Digestion, Breathing) -> hier kontinuierliche Trading-Metriken.
    """

    DEFAULT_BUCKETS: tuple[float, ...] = (0.001, 0.01, 0.1, 1.0, 10.0)

    def __init__(
        self,
        default_buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        # Pre-Condition: default_buckets sortiert ascending, alle > 0
        if not default_buckets:
            raise ValueError("default_buckets must be non-empty")
        for v in default_buckets:
            if v <= 0:
                raise ValueError(f"bucket value must be > 0: {v}")
        if list(default_buckets) != sorted(default_buckets):
            raise ValueError("default_buckets must be sorted ascending")

        self._default_buckets: tuple[float, ...] = tuple(default_buckets)
        self._metrics: dict[str, _MetricSpec] = {}
        # global lock (registry mutation)
        self._global_lock = threading.RLock()
        # per-metric Lock-Striping (Multi-Receptor-Independence)
        self._metric_locks: dict[str, threading.RLock] = {}

    # -----------------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------------
    def register_metric(
        self,
        metric_name: str,
        metric_type: MetricType,
        description: str = "",
        labels: tuple[str, ...] = (),
    ) -> None:
        """Registriere eine neue Metric.

        Pre:
          - metric_name non-empty
          - metric_type in MetricType
          - labels: tuple-of-strings, jede non-empty

        Post:
          - Metric registriert + per-metric Lock erzeugt
          - Doppel-Registrierung mit anderem Spec raises ValueError
          - Doppel-Registrierung mit identischem Spec ist idempotent (no-op)
        """
        if not metric_name:
            raise ValueError("metric_name must be non-empty")
        if not isinstance(metric_type, MetricType):
            raise TypeError(f"metric_type must be MetricType, got {type(metric_type).__name__}")
        for lbl in labels:
            if not lbl:
                raise ValueError("label names must be non-empty")

        with self._global_lock:
            if metric_name in self._metrics:
                existing = self._metrics[metric_name]
                if (
                    existing.metric_type != metric_type
                    or existing.labels != tuple(labels)
                ):
                    raise ValueError(
                        f"metric {metric_name!r} already registered with different spec "
                        f"(existing: {existing.metric_type.value}/{existing.labels}, "
                        f"new: {metric_type.value}/{tuple(labels)})"
                    )
                # idempotent: same spec re-registered, no-op
                return

            spec = _MetricSpec(
                metric_name=metric_name,
                metric_type=metric_type,
                description=description,
                labels=tuple(labels),
            )
            if metric_type == MetricType.HISTOGRAM:
                spec.buckets = self._default_buckets
            self._metrics[metric_name] = spec
            self._metric_locks[metric_name] = threading.RLock()

    # -----------------------------------------------------------------------
    # Helpers (Label-Key-Erzeugung)
    # -----------------------------------------------------------------------
    @staticmethod
    def _label_key(label_values: dict[str, str]) -> tuple[tuple[str, str], ...]:
        """Stable tuple-of-tuples Key fuer label-Kombination."""
        return tuple(sorted((k, str(v)) for k, v in label_values.items()))

    def _check_metric_type(
        self,
        metric_name: str,
        expected: MetricType,
    ) -> _MetricSpec:
        """Pre-Condition: Metric ist registriert + hat erwarteten Typ."""
        if metric_name not in self._metrics:
            raise KeyError(f"metric {metric_name!r} not registered")
        spec = self._metrics[metric_name]
        if spec.metric_type != expected:
            raise TypeError(
                f"metric {metric_name!r} is {spec.metric_type.value}, "
                f"expected {expected.value}"
            )
        return spec

    # -----------------------------------------------------------------------
    # COUNTER Operations
    # -----------------------------------------------------------------------
    def inc_counter(
        self,
        metric_name: str,
        value: float = 1.0,
        **label_values: str,
    ) -> None:
        """Inkrementiere Counter um value.

        Pre:
          - metric_name registriert als COUNTER
          - value >= 0 (Counter sind monoton steigend)

        Post:
          - Counter-Wert um value erhoeht (race-safe)
        """
        if value < 0:
            raise ValueError(
                f"counter inc value must be >= 0 (use Gauge for decrease): {value}"
            )

        # type-check + spec-lookup
        spec = self._check_metric_type(metric_name, MetricType.COUNTER)
        key = self._label_key(label_values)

        # per-metric Lock (Multi-Receptor-Independence)
        with self._metric_locks[metric_name]:
            spec.values[key] = spec.values.get(key, 0.0) + float(value)
            spec.last_update[key] = time.time()

    # -----------------------------------------------------------------------
    # GAUGE Operations
    # -----------------------------------------------------------------------
    def set_gauge(
        self,
        metric_name: str,
        value: float,
        **label_values: str,
    ) -> None:
        """Setze Gauge auf value (kann fallen + steigen)."""
        spec = self._check_metric_type(metric_name, MetricType.GAUGE)
        key = self._label_key(label_values)

        with self._metric_locks[metric_name]:
            spec.values[key] = float(value)
            spec.last_update[key] = time.time()

    # -----------------------------------------------------------------------
    # HISTOGRAM Operations
    # -----------------------------------------------------------------------
    def observe_histogram(
        self,
        metric_name: str,
        value: float,
        **label_values: str,
    ) -> None:
        """Observe einen Wert im Histogram (default-buckets oder per-Metric).

        Pre:
          - value >= 0 (negative values are nonsensical for histograms,
            e.g. negative latencies or durations)
        """
        if value < 0:
            raise ValueError(f"histogram value must be >= 0, got {value}")
        spec = self._check_metric_type(metric_name, MetricType.HISTOGRAM)
        key = self._label_key(label_values)

        with self._metric_locks[metric_name]:
            # init Bucket-Counter falls erste Observation fuer diesen Label-Key
            if key not in spec.bucket_counts:
                spec.bucket_counts[key] = {b: 0 for b in spec.buckets}
                spec.bucket_counts[key][float("inf")] = 0
                spec.histogram_sum[key] = 0.0
                spec.histogram_count[key] = 0

            # Bucket-Increment (cumulative, Prometheus-Konvention)
            for b in spec.buckets:
                if value <= b:
                    spec.bucket_counts[key][b] += 1
            spec.bucket_counts[key][float("inf")] += 1
            spec.histogram_sum[key] += float(value)
            spec.histogram_count[key] += 1
            spec.last_update[key] = time.time()

    # -----------------------------------------------------------------------
    # Read-Operations (Snapshots)
    # -----------------------------------------------------------------------
    def get_metric(
        self,
        metric_name: str,
        **label_values: str,
    ) -> TradingMetric:
        """Snapshot des Metric-Werts fuer Label-Kombination.

        Pre:
          - metric_name registriert (sonst KeyError)
          - fuer COUNTER/GAUGE: liefert aktuellen Wert
          - fuer HISTOGRAM: liefert count (sum/buckets via get_histogram_buckets)

        Post:
          - frozen TradingMetric-Snapshot
        """
        if metric_name not in self._metrics:
            raise KeyError(f"metric {metric_name!r} not registered")

        spec = self._metrics[metric_name]
        key = self._label_key(label_values)

        with self._metric_locks[metric_name]:
            if spec.metric_type == MetricType.HISTOGRAM:
                value = float(spec.histogram_count.get(key, 0))
            else:
                value = spec.values.get(key, 0.0)
            ts = spec.last_update.get(key, 0.0)

        return TradingMetric(
            metric_name=metric_name,
            metric_type=spec.metric_type,
            value=value,
            labels=key,
            timestamp=ts,
        )

    def get_histogram_buckets(
        self,
        metric_name: str,
        **label_values: str,
    ) -> dict[float, int]:
        """Snapshot der Bucket-Counter fuer HISTOGRAM."""
        spec = self._check_metric_type(metric_name, MetricType.HISTOGRAM)
        key = self._label_key(label_values)

        with self._metric_locks[metric_name]:
            buckets = spec.bucket_counts.get(key, {})
            # immutable copy
            return dict(buckets)

    def list_metrics(self) -> tuple[str, ...]:
        """Tuple aller registrierten Metric-Namen."""
        with self._global_lock:
            return tuple(sorted(self._metrics.keys()))

    # -----------------------------------------------------------------------
    # Prometheus-Text-Format-Export
    # -----------------------------------------------------------------------
    def export_prometheus(self) -> str:
        """Export aller Metrics im Prometheus-Text-Format.

        Format (vereinfacht, spec-konform):
            # HELP metric_name description
            # TYPE metric_name counter|gauge|histogram
            metric_name{label="value"} value

        Histogramme zusaetzlich:
            metric_name_bucket{le="0.001"} count
            metric_name_count value
            metric_name_sum value
        """
        lines: list[str] = []
        with self._global_lock:
            metric_names = sorted(self._metrics.keys())

        for metric_name in metric_names:
            spec = self._metrics[metric_name]
            with self._metric_locks[metric_name]:
                if spec.description:
                    lines.append(f"# HELP {metric_name} {spec.description}")
                lines.append(f"# TYPE {metric_name} {spec.metric_type.value}")

                if spec.metric_type in (MetricType.COUNTER, MetricType.GAUGE):
                    if not spec.values:
                        # registriert aber nie geschrieben -> 0-Default ohne Labels
                        lines.append(f"{metric_name} 0.0")
                    else:
                        for key, val in sorted(spec.values.items()):
                            label_str = self._format_labels_prometheus(key)
                            lines.append(f"{metric_name}{label_str} {val}")

                elif spec.metric_type == MetricType.HISTOGRAM:
                    if not spec.bucket_counts:
                        # registriert aber nie observed -> Default empty
                        lines.append(f"{metric_name}_count 0")
                        lines.append(f"{metric_name}_sum 0.0")
                    else:
                        for key in sorted(spec.bucket_counts.keys()):
                            buckets = spec.bucket_counts[key]
                            base_labels = list(key)
                            for b in spec.buckets:
                                bucket_labels = tuple(base_labels + [("le", str(b))])
                                label_str = self._format_labels_prometheus(bucket_labels)
                                lines.append(
                                    f"{metric_name}_bucket{label_str} {buckets.get(b, 0)}"
                                )
                            # +Inf bucket
                            inf_labels = tuple(base_labels + [("le", "+Inf")])
                            label_str = self._format_labels_prometheus(inf_labels)
                            lines.append(
                                f"{metric_name}_bucket{label_str} "
                                f"{buckets.get(float('inf'), 0)}"
                            )
                            # _count + _sum
                            base_label_str = self._format_labels_prometheus(key)
                            lines.append(
                                f"{metric_name}_count{base_label_str} "
                                f"{spec.histogram_count.get(key, 0)}"
                            )
                            lines.append(
                                f"{metric_name}_sum{base_label_str} "
                                f"{spec.histogram_sum.get(key, 0.0)}"
                            )

        return "\n".join(lines)

    @staticmethod
    def _format_labels_prometheus(
        labels: tuple[tuple[str, str], ...],
    ) -> str:
        """Prometheus-Label-Format: {key="value",key2="value2"}."""
        if not labels:
            return ""
        parts = ",".join(f'{k}="{v}"' for k, v in labels)
        return "{" + parts + "}"

    # -----------------------------------------------------------------------
    # Reset (Test-Support)
    # -----------------------------------------------------------------------
    def reset(self) -> None:
        """Loescht alle Metrics + Locks (nur fuer Tests / Re-Init).

        Post:
          - leerer Registry-State
          - alle per-metric Locks freigegeben
        """
        with self._global_lock:
            self._metrics.clear()
            self._metric_locks.clear()


# CRUX-MK
