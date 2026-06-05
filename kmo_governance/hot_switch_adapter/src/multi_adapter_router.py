# Multi-Adapter-Router [CRUX-MK]
"""
Routing-Logic ueber mehrere PMS-Adapter (Apaleo, Mews, Cloudbeds).

Strategy:
- Primary -> Secondary -> Tertiary
- Bei Failure: Circuit-Breaker oeffnet, Failover triggert
- Anti-Pattern: Tenant-Hardcoding in Adapter-Code (verboten)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable

from .adapter_health import (
    AdapterHealthMonitor, AdapterStatus, CircuitState,
)


class AdapterName(str, Enum):
    APALEO = "apaleo"
    MEWS = "mews"
    CLOUDBEDS = "cloudbeds"


class RoutingDecision(str, Enum):
    PRIMARY = "PRIMARY"
    FAILOVER_SECONDARY = "FAILOVER_SECONDARY"
    FAILOVER_TERTIARY = "FAILOVER_TERTIARY"
    NO_AVAILABLE_ADAPTER = "NO_AVAILABLE_ADAPTER"


@dataclass
class AdapterCallResult:
    """Ergebnis eines Adapter-Calls (durch Router)."""
    used_adapter: str
    success: bool
    response: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    routing_decision: RoutingDecision = RoutingDecision.PRIMARY
    fallback_chain: list[str] = field(default_factory=list)


# Adapter-Hook-Type: Callable that takes a tenant_id + payload and returns response
AdapterHook = Callable[[str, dict[str, Any]], Any]


class MultiAdapterRouter:
    """Router mit Failover-Logic und Health-Monitoring.

    Pre-Conditions:
        - primary/secondary/tertiary sind AdapterName oder str
        - adapter_hooks: dict[str, AdapterHook]
    """

    def __init__(self, primary: AdapterName | str,
                 secondary: AdapterName | str | None = None,
                 tertiary: AdapterName | str | None = None,
                 adapter_hooks: dict[str, AdapterHook] | None = None,
                 fail_threshold: int = 3) -> None:
        self.primary = primary.value if isinstance(primary, AdapterName) else primary
        self.secondary = (secondary.value if isinstance(secondary, AdapterName)
                          else secondary)
        self.tertiary = (tertiary.value if isinstance(tertiary, AdapterName)
                         else tertiary)
        self.adapter_hooks = adapter_hooks or {}
        self.health_monitors: dict[str, AdapterHealthMonitor] = {}
        for adapter in [self.primary, self.secondary, self.tertiary]:
            if adapter:
                self.health_monitors[adapter] = AdapterHealthMonitor(
                    adapter, threshold_open_after_n_fails=fail_threshold,
                )

    def _candidates(self) -> list[tuple[str, RoutingDecision]]:
        out = [(self.primary, RoutingDecision.PRIMARY)]
        if self.secondary:
            out.append((self.secondary, RoutingDecision.FAILOVER_SECONDARY))
        if self.tertiary:
            out.append((self.tertiary, RoutingDecision.FAILOVER_TERTIARY))
        return out

    def call(self, tenant_id: str, payload: dict[str, Any]) -> AdapterCallResult:
        """Macht den Call ueber den ersten verfuegbaren Adapter.

        Failover wenn primary nicht verfuegbar.
        Returns AdapterCallResult mit fallback_chain.
        """
        chain: list[str] = []
        for adapter, decision in self._candidates():
            monitor = self.health_monitors.get(adapter)
            if monitor and not monitor.is_available():
                chain.append(f"{adapter}:CIRCUIT_OPEN")
                continue
            chain.append(adapter)
            hook = self.adapter_hooks.get(adapter)
            if hook is None:
                # Kein Hook -> failure
                if monitor:
                    monitor.record_failure(error="no_hook")
                continue
            try:
                t0 = time.monotonic()
                response = hook(tenant_id, payload)
                latency = (time.monotonic() - t0) * 1000.0
                if monitor:
                    monitor.record_success(latency_ms=latency)
                return AdapterCallResult(
                    used_adapter=adapter, success=True, response=response,
                    latency_ms=latency, routing_decision=decision,
                    fallback_chain=chain,
                )
            except Exception as e:  # noqa: BLE001
                if monitor:
                    monitor.record_failure(error=str(e))
                continue

        return AdapterCallResult(
            used_adapter="",
            success=False,
            error="all adapters failed or unavailable",
            routing_decision=RoutingDecision.NO_AVAILABLE_ADAPTER,
            fallback_chain=chain,
        )

    def health_summary(self) -> dict[str, Any]:
        return {
            adapter: {
                "status": m.get_status().value,
                "circuit_state": m.circuit_state.value,
                "consecutive_fails": m.consecutive_fails,
                "consecutive_successes": m.consecutive_successes,
            }
            for adapter, m in self.health_monitors.items()
        }
