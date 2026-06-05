# Failover-Orchestrator [CRUX-MK]
"""
Orchestriert Multi-Tenant-Adapter-Routing.

Pro Tenant kann eine andere Primary-Adapter-Konfiguration gelten.
Cross-Tenant-Daten-Kontamination verhindert (jeder Tenant eigene Router-Instanz).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .multi_adapter_router import (
    MultiAdapterRouter, AdapterName, AdapterCallResult, AdapterHook,
)


class FailoverOrchestrator:
    """Verwaltet Router pro Tenant.

    Pre-Conditions:
        - default_adapter_hooks ist dict
    Post-Conditions:
        - get_router(tenant_id) liefert tenant-spezifischen Router
    """

    def __init__(self, default_adapter_hooks: dict[str, AdapterHook] | None = None,
                 fail_threshold: int = 3) -> None:
        self.default_hooks = default_adapter_hooks or {}
        self.fail_threshold = fail_threshold
        self._routers: dict[str, MultiAdapterRouter] = {}
        self._tenant_configs: dict[str, dict[str, Any]] = {}

    def configure_tenant(self, tenant_id: UUID | str,
                         primary: AdapterName | str,
                         secondary: AdapterName | str | None = None,
                         tertiary: AdapterName | str | None = None,
                         adapter_hooks: dict[str, AdapterHook] | None = None) -> None:
        tid = str(tenant_id)
        hooks = adapter_hooks or self.default_hooks
        self._routers[tid] = MultiAdapterRouter(
            primary=primary, secondary=secondary, tertiary=tertiary,
            adapter_hooks=hooks, fail_threshold=self.fail_threshold,
        )
        self._tenant_configs[tid] = {
            "primary": primary.value if isinstance(primary, AdapterName) else primary,
            "secondary": secondary.value if isinstance(secondary, AdapterName) else secondary,
            "tertiary": tertiary.value if isinstance(tertiary, AdapterName) else tertiary,
        }

    def get_router(self, tenant_id: UUID | str) -> MultiAdapterRouter | None:
        return self._routers.get(str(tenant_id))

    def call(self, tenant_id: UUID | str,
             payload: dict[str, Any]) -> AdapterCallResult:
        tid = str(tenant_id)
        router = self._routers.get(tid)
        if router is None:
            return AdapterCallResult(
                used_adapter="",
                success=False,
                error=f"no router configured for tenant {tid}",
            )
        return router.call(tid, payload)

    def health_overview(self) -> dict[str, Any]:
        return {
            tid: router.health_summary()
            for tid, router in self._routers.items()
        }
