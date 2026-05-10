from __future__ import annotations

from threading import RLock
from typing import Any


class ObservabilityLayer:
    def __init__(self) -> None:
        self._lock = RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}

    def inc_counter(
        self, name: str, value: int = 1, labels: dict[str, Any] | None = None
    ) -> None:
        key = self._metric_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + int(value)

    def set_gauge(
        self, name: str, value: float, labels: dict[str, Any] | None = None
    ) -> None:
        key = self._metric_key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def observe_histogram(
        self, name: str, value: float, labels: dict[str, Any] | None = None
    ) -> None:
        if value < 0:
            raise ValueError("histogram value must be non-negative")

        key = self._metric_key(name, labels)
        with self._lock:
            self._histograms.setdefault(key, []).append(float(value))

    def get_counter(self, name: str, labels: dict[str, Any] | None = None) -> int:
        key = self._metric_key(name, labels)
        with self._lock:
            return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict[str, Any] | None = None) -> float:
        key = self._metric_key(name, labels)
        with self._lock:
            return self._gauges.get(key, 0.0)

    def get_histogram_stats(
        self, name: str, labels: dict[str, Any] | None = None
    ) -> dict[str, float | int | None]:
        key = self._metric_key(name, labels)
        with self._lock:
            values = list(self._histograms.get(key, []))

        if not values:
            return {
                "count": 0,
                "sum": 0.0,
                "min": None,
                "max": None,
                "p50": None,
                "p95": None,
                "p99": None,
            }

        sorted_values = sorted(values)
        return {
            "count": len(sorted_values),
            "sum": float(sum(sorted_values)),
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "p50": self._percentile(sorted_values, 50),
            "p95": self._percentile(sorted_values, 95),
            "p99": self._percentile(sorted_values, 99),
        }

    def export_prometheus(self) -> str:
        lines: list[str] = []

        with self._lock:
            counters = sorted(self._counters.items())
            gauges = sorted(self._gauges.items())
            histograms = sorted(
                (key, list(values)) for key, values in self._histograms.items()
            )

        for (name, labels), value in counters:
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{self._format_labels(labels)} {value}")

        for (name, labels), value in gauges:
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name}{self._format_labels(labels)} {self._format_number(value)}")

        for (name, labels), values in histograms:
            stats = self._stats_from_values(values)
            label_text = self._format_labels(labels)
            lines.append(f"# TYPE {name} summary")
            lines.append(f"{name}_count{label_text} {stats['count']}")
            lines.append(f"{name}_sum{label_text} {self._format_number(stats['sum'])}")
            for quantile in ("p50", "p95", "p99"):
                quantile_labels = tuple(labels) + (("quantile", quantile[1:]),)
                lines.append(
                    f"{name}{self._format_labels(quantile_labels)} "
                    f"{self._format_number(stats[quantile])}"
                )

        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _metric_key(
        name: str, labels: dict[str, Any] | None
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not name:
            raise ValueError("metric name must not be empty")

        normalized_labels = tuple(
            sorted((str(key), str(value)) for key, value in (labels or {}).items())
        )
        return name, normalized_labels

    @classmethod
    def _stats_from_values(cls, values: list[float]) -> dict[str, float | int | None]:
        if not values:
            return {
                "count": 0,
                "sum": 0.0,
                "min": None,
                "max": None,
                "p50": None,
                "p95": None,
                "p99": None,
            }

        sorted_values = sorted(values)
        return {
            "count": len(sorted_values),
            "sum": float(sum(sorted_values)),
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "p50": cls._percentile(sorted_values, 50),
            "p95": cls._percentile(sorted_values, 95),
            "p99": cls._percentile(sorted_values, 99),
        }

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: int) -> float:
        if not sorted_values:
            raise ValueError("cannot calculate percentile of empty values")

        if len(sorted_values) == 1:
            return sorted_values[0]

        rank = (percentile / 100) * (len(sorted_values) - 1)
        lower_index = int(rank)
        upper_index = min(lower_index + 1, len(sorted_values) - 1)
        weight = rank - lower_index
        return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight

    @staticmethod
    def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""

        rendered = ",".join(
            f'{key}="{ObservabilityLayer._escape_label_value(value)}"'
            for key, value in labels
        )
        return f"{{{rendered}}}"

    @staticmethod
    def _escape_label_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

    @staticmethod
    def _format_number(value: float | int | None) -> str:
        if value is None:
            return "nan"

        if isinstance(value, float) and value.is_integer():
            return str(int(value))

        return str(value)
