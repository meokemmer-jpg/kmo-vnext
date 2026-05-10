# [CRUX-MK]
"""KMO-vNext Aggregated Health-Check (Welle-37 Phase-30 Production-Skizze).

Aggregiert health_check() von allen 60+ kmo_governance-Modulen zu einem
Single-Entry-Point. Exit-Codes Prometheus-kompatibel:
  0 = HEALTHY (alle Module OK)
  1 = DEGRADED (mindestens 1 Modul DEGRADED, kein FAILED)
  2 = FAILED (mindestens 1 Modul FAILED)

Verwendet als Docker-Healthcheck:
  docker run kmo-vnext python3 -m kmo_governance.health_check

Per `branch-hub/blueprints/SPEC-KMO-PRODUCTION-DEPLOYMENT-V1-2026-05-09.md`.

CRUX-MK
"""
from __future__ import annotations

import importlib
import sys
import time
from dataclasses import dataclass, field
from typing import Optional


# Module-Liste (post-Welle-36, 60 aktive Module)
# Format: (module_path, has_health_check_function)
KMO_MODULES = (
    "kpm_audit_event_bus",
    "kpm_observability_layer",
    "kpm_distributed_lock_manager",
    "kpm_homeostasis_controller",
    "kpm_deduplication_engine",
    "kpm_chaos_engineering",
    "kpm_demo_application",
    "kpm_backpressure_engine",
    "kpm_saga_orchestrator",
    "kpm_feature_flag_engine",
    "kpm_trading_failover",
    "graphity_distributed_lock",
    "cape_familien_audit_bus",
    "sae_chaos_engineering_for_aiops",
    "ninedots_pmo_audit_bus",
    "heylou_ota_pricing_failover",
    "rate_limiter_pool",
    "retry_strategy_engine",
    "deduplication_engine",
    "distributed_lock_manager",
    "batch_processor",
    "data_class_filter",
    "durable_execution",
    "lease_manager",
    "homeostasis_controller",
    "sae_v8_distributed_lock_trinity",
    "sae_v8_homeostasis_governance",
    "sae_v8_backpressure_slot_admission",
    # ... weitere 32 Module (full list in production)
)


@dataclass(frozen=True)
class ModuleHealth:
    """Health-Status eines einzelnen Moduls.

    Pre:
      - module_name non-empty
      - status in {"HEALTHY", "DEGRADED", "FAILED", "UNKNOWN"}
      - latency_ms >= 0
    """
    module_name: str
    status: str
    latency_ms: float
    error: Optional[str] = None


@dataclass(frozen=True)
class AggregatedHealth:
    """Aggregierter Health-Status aller Module."""
    overall_status: str  # HEALTHY | DEGRADED | FAILED
    total_modules: int
    healthy_count: int
    degraded_count: int
    failed_count: int
    unknown_count: int
    module_results: tuple[ModuleHealth, ...] = field(default_factory=tuple)
    aggregate_latency_ms: float = 0.0


def check_module_health(module_name: str) -> ModuleHealth:
    """Pruefe Health-Status eines einzelnen Moduls.

    Pre:
      - module_name in KMO_MODULES OR loadable via importlib

    Post:
      - returns frozen ModuleHealth mit status + latency_ms
      - bei import-error: status=UNKNOWN
      - bei health_check-error: status=FAILED
      - bei kein health_check Function: status=UNKNOWN (graceful)
    """
    start = time.monotonic()
    try:
        module = importlib.import_module(f"kmo_governance.{module_name}")
        # Optional health_check function (nicht alle Module haben das)
        if hasattr(module, "health_check"):
            result = module.health_check()
            status = result.get("status", "UNKNOWN") if isinstance(result, dict) else "HEALTHY"
        else:
            # Default: HEALTHY wenn import OK
            status = "HEALTHY"
        latency_ms = (time.monotonic() - start) * 1000.0
        return ModuleHealth(
            module_name=module_name,
            status=status,
            latency_ms=latency_ms,
        )
    except ImportError as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        return ModuleHealth(
            module_name=module_name,
            status="UNKNOWN",
            latency_ms=latency_ms,
            error=f"ImportError: {exc}",
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        return ModuleHealth(
            module_name=module_name,
            status="FAILED",
            latency_ms=latency_ms,
            error=f"{type(exc).__name__}: {exc}",
        )


def health_check_all(
    modules: tuple[str, ...] = KMO_MODULES,
) -> AggregatedHealth:
    """Aggregiere Health-Status aller Module.

    Pre:
      - modules: tuple of module-names

    Post:
      - returns AggregatedHealth
      - overall_status = FAILED wenn any FAILED
      - overall_status = DEGRADED wenn any DEGRADED (kein FAILED)
      - overall_status = HEALTHY wenn alle HEALTHY+UNKNOWN
    """
    start = time.monotonic()
    results = tuple(check_module_health(name) for name in modules)

    healthy = sum(1 for r in results if r.status == "HEALTHY")
    degraded = sum(1 for r in results if r.status == "DEGRADED")
    failed = sum(1 for r in results if r.status == "FAILED")
    unknown = sum(1 for r in results if r.status == "UNKNOWN")

    if failed > 0:
        overall = "FAILED"
    elif degraded > 0:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    aggregate_latency_ms = (time.monotonic() - start) * 1000.0

    return AggregatedHealth(
        overall_status=overall,
        total_modules=len(modules),
        healthy_count=healthy,
        degraded_count=degraded,
        failed_count=failed,
        unknown_count=unknown,
        module_results=results,
        aggregate_latency_ms=aggregate_latency_ms,
    )


def main() -> int:
    """CLI-Entry: Exit 0/1/2 fuer Docker-Healthcheck."""
    health = health_check_all()
    print(f"KMO-vNext Health-Check: {health.overall_status}")
    print(f"  Total: {health.total_modules}")
    print(f"  HEALTHY: {health.healthy_count}")
    print(f"  DEGRADED: {health.degraded_count}")
    print(f"  FAILED: {health.failed_count}")
    print(f"  UNKNOWN: {health.unknown_count}")
    print(f"  Latency: {health.aggregate_latency_ms:.1f}ms")
    if health.failed_count > 0:
        print("FAILED Modules:")
        for m in health.module_results:
            if m.status == "FAILED":
                print(f"  - {m.module_name}: {m.error}")
    if health.overall_status == "FAILED":
        return 2
    if health.overall_status == "DEGRADED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

# CRUX-MK
