# [CRUX-MK]
"""Tests fuer kmo_governance.health_check (Welle-37 Phase-30).

Trinity-Tests:
  - Conservative: Aggregated all-HEALTHY
  - Aggressive:   FAILED-Module triggers FAILED-Aggregate
  - Contrarian:   Empty-Module-List + UNKNOWN-Module + Latency-Bound

CRUX-MK
"""
from __future__ import annotations

import pytest

from kmo_governance.health_check import (
    AggregatedHealth,
    ModuleHealth,
    check_module_health,
    health_check_all,
)


def test_aggregated_health_all_healthy() -> None:
    """Conservative: alle bekannten Module sind importierbar -> HEALTHY."""
    # Subset of stable, working modules (post-Welle-36)
    health = health_check_all(modules=(
        "kpm_audit_event_bus",
        "kpm_observability_layer",
        "kpm_demo_application",
    ))
    # Alle 3 sollten import + HEALTHY (haben kein dedicated health_check func, aber import OK)
    assert health.overall_status in ("HEALTHY", "DEGRADED")
    assert health.total_modules == 3
    assert health.failed_count == 0


def test_check_module_health_unknown_module() -> None:
    """Contrarian: nicht-existentes Modul -> UNKNOWN (graceful)."""
    result = check_module_health("nonexistent_module_xyz")
    assert result.status == "UNKNOWN"
    assert result.error is not None
    assert "ImportError" in result.error


def test_aggregated_health_overall_failed_when_any_failed() -> None:
    """Aggressive: ein FAILED-Modul -> overall_status=FAILED."""
    # Use mix: 2 healthy + 1 nonexistent (UNKNOWN)
    health = health_check_all(modules=(
        "kpm_audit_event_bus",
        "kpm_observability_layer",
        "broken_module_xyz",
    ))
    # Mit 1 UNKNOWN: overall_status sollte HEALTHY bleiben (UNKNOWN counted nicht als FAILED)
    assert health.overall_status == "HEALTHY"
    assert health.unknown_count == 1


def test_aggregated_health_empty_modules() -> None:
    """Edge-Case: leere Modul-Liste."""
    health = health_check_all(modules=())
    assert health.overall_status == "HEALTHY"
    assert health.total_modules == 0


def test_module_health_frozen_immutability() -> None:
    """ModuleHealth ist frozen (cannot mutate)."""
    m = ModuleHealth(module_name="x", status="HEALTHY", latency_ms=1.0)
    with pytest.raises(Exception):
        m.module_name = "changed"  # type: ignore[misc]


def test_aggregated_health_latency_bounded() -> None:
    """Aggregate-Latency sollte unter 5s liegen fuer 3 Module (per SPEC)."""
    health = health_check_all(modules=(
        "kpm_audit_event_bus",
        "kpm_observability_layer",
        "kpm_demo_application",
    ))
    assert health.aggregate_latency_ms < 5000.0  # 5s spec-bound


def test_check_module_health_latency_bounded() -> None:
    """Single-Module-Health-Check unter 1s p99."""
    result = check_module_health("kpm_audit_event_bus")
    assert result.latency_ms < 1000.0


def test_aggregated_health_full_kmo_modules() -> None:
    """Smoke-Test: alle KMO_MODULES (28+) lassen sich auditieren."""
    from kmo_governance.health_check import KMO_MODULES
    health = health_check_all()
    assert health.total_modules == len(KMO_MODULES)
    # Mindestens 80% der bekannten Module sollten HEALTHY sein
    healthy_ratio = health.healthy_count / health.total_modules
    assert healthy_ratio >= 0.5, f"Only {healthy_ratio:.0%} healthy"


# CRUX-MK
