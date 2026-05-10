from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any, Mapping


class BrokerStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BrokerHealth:
    broker_id: str
    latency_ms: float
    error_rate: float
    status: BrokerStatus


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    chosen_broker_id: str
    fallback_chain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BrokerRegistration:
    broker_id: str
    priority: int
    sequence: int


class KPMFailoverRouter:
    def __init__(
        self,
        *,
        healthy_latency_ms: float = 250.0,
        degraded_latency_ms: float = 1_000.0,
        healthy_error_rate: float = 0.05,
        degraded_error_rate: float = 0.25,
    ) -> None:
        if healthy_latency_ms < 0 or degraded_latency_ms < 0:
            raise ValueError("latency thresholds must be non-negative")
        if not 0 <= healthy_error_rate <= degraded_error_rate <= 1:
            raise ValueError("error-rate thresholds must satisfy 0 <= healthy <= degraded <= 1")
        if healthy_latency_ms > degraded_latency_ms:
            raise ValueError("healthy latency threshold must be <= degraded latency threshold")

        self._healthy_latency_ms = healthy_latency_ms
        self._degraded_latency_ms = degraded_latency_ms
        self._healthy_error_rate = healthy_error_rate
        self._degraded_error_rate = degraded_error_rate
        self._lock = RLock()
        self._sequence = 0
        self._brokers: dict[str, _BrokerRegistration] = {}
        self._health: dict[str, BrokerHealth] = {}

    def register_broker(self, broker_id: str, priority: int) -> None:
        broker_id = self._normalize_broker_id(broker_id)
        if not isinstance(priority, int):
            raise TypeError("priority must be an int")
        if priority < 0:
            raise ValueError("priority must be non-negative")

        with self._lock:
            existing = self._brokers.get(broker_id)
            if existing is None:
                registration = _BrokerRegistration(
                    broker_id=broker_id,
                    priority=priority,
                    sequence=self._sequence,
                )
                self._sequence += 1
            else:
                registration = _BrokerRegistration(
                    broker_id=broker_id,
                    priority=priority,
                    sequence=existing.sequence,
                )

            self._brokers[broker_id] = registration
            self._health.setdefault(
                broker_id,
                BrokerHealth(
                    broker_id=broker_id,
                    latency_ms=0.0,
                    error_rate=0.0,
                    status=BrokerStatus.HEALTHY,
                ),
            )

    def record_health(self, broker_id: str, latency_ms: float, error_rate: float) -> BrokerHealth:
        broker_id = self._normalize_broker_id(broker_id)
        latency_ms = self._normalize_latency(latency_ms)
        error_rate = self._normalize_error_rate(error_rate)

        with self._lock:
            if broker_id not in self._brokers:
                raise KeyError(f"unknown broker: {broker_id}")

            health = BrokerHealth(
                broker_id=broker_id,
                latency_ms=latency_ms,
                error_rate=error_rate,
                status=self._classify(latency_ms=latency_ms, error_rate=error_rate),
            )
            self._health[broker_id] = health
            return health

    def route_order(self, order_payload: Mapping[str, Any]) -> RoutingDecision:
        if not isinstance(order_payload, Mapping):
            raise TypeError("order_payload must be a mapping")

        with self._lock:
            candidates = [
                registration
                for registration in self._ordered_registrations()
                if self._health[registration.broker_id].status is not BrokerStatus.FAILED
            ]

            if not candidates:
                raise RuntimeError("no available broker for order routing")

            healthy = [
                registration
                for registration in candidates
                if self._health[registration.broker_id].status is BrokerStatus.HEALTHY
            ]
            ranked = healthy if healthy else candidates
            chosen = ranked[0]
            fallback_chain = tuple(
                registration.broker_id
                for registration in candidates
                if registration.broker_id != chosen.broker_id
            )

            return RoutingDecision(
                chosen_broker_id=chosen.broker_id,
                fallback_chain=fallback_chain,
            )

    def broker_health(self, broker_id: str) -> BrokerHealth:
        broker_id = self._normalize_broker_id(broker_id)
        with self._lock:
            if broker_id not in self._health:
                raise KeyError(f"unknown broker: {broker_id}")
            return self._health[broker_id]

    def _ordered_registrations(self) -> list[_BrokerRegistration]:
        return sorted(
            self._brokers.values(),
            key=lambda registration: (registration.priority, registration.sequence),
        )

    def _classify(self, *, latency_ms: float, error_rate: float) -> BrokerStatus:
        if latency_ms <= self._healthy_latency_ms and error_rate <= self._healthy_error_rate:
            return BrokerStatus.HEALTHY
        if latency_ms <= self._degraded_latency_ms and error_rate <= self._degraded_error_rate:
            return BrokerStatus.DEGRADED
        return BrokerStatus.FAILED

    @staticmethod
    def _normalize_broker_id(broker_id: str) -> str:
        if not isinstance(broker_id, str):
            raise TypeError("broker_id must be a str")
        broker_id = broker_id.strip()
        if not broker_id:
            raise ValueError("broker_id must not be blank")
        return broker_id

    @staticmethod
    def _normalize_latency(latency_ms: float) -> float:
        latency_ms = float(latency_ms)
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        return latency_ms

    @staticmethod
    def _normalize_error_rate(error_rate: float) -> float:
        error_rate = float(error_rate)
        if not 0 <= error_rate <= 1:
            raise ValueError("error_rate must be between 0 and 1")
        return error_rate
