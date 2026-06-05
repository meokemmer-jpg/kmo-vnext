# Lifecycle-Pipeline [CRUX-MK]
"""
Tenant-Lifecycle-Pipeline (provision/activate/suspend/decommission/archive).

State-Transitions (gueltig):
    PROVISIONED -> ACTIVE        : activate()
    PROVISIONED -> DECOMMISSIONED: decommission()  (Cancel before activation)
    ACTIVE      -> SUSPENDED     : suspend()
    SUSPENDED   -> ACTIVE        : reactivate()
    ACTIVE      -> DECOMMISSIONED: decommission()
    SUSPENDED   -> DECOMMISSIONED: decommission()
    DECOMMISSIONED -> ARCHIVED   : archive()

Andere Transitions = ValueError (State-Machine-Pflicht).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .tenant import Tenant, TenantStatus, PlanTier


VALID_TRANSITIONS: dict[TenantStatus, set[TenantStatus]] = {
    TenantStatus.PROVISIONED: {TenantStatus.ACTIVE, TenantStatus.DECOMMISSIONED},
    TenantStatus.ACTIVE: {TenantStatus.SUSPENDED, TenantStatus.DECOMMISSIONED},
    TenantStatus.SUSPENDED: {TenantStatus.ACTIVE, TenantStatus.DECOMMISSIONED},
    TenantStatus.DECOMMISSIONED: {TenantStatus.ARCHIVED},
    TenantStatus.ARCHIVED: set(),  # Terminal
}


class LifecycleTransitionError(ValueError):
    """Wird geworfen bei ungueltiger State-Transition."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def provision(name: str, plan_tier: PlanTier | str,
              metadata: dict[str, Any] | None = None) -> Tenant:
    """Erzeugt einen neuen Tenant im PROVISIONED-Status.

    Pre-Conditions:
        - name nicht leer
        - plan_tier in PlanTier
    Post-Conditions:
        - tenant.status == PROVISIONED
        - tenant.created_at gesetzt
    """
    if isinstance(plan_tier, str):
        plan_tier = PlanTier(plan_tier)
    return Tenant(
        name=name,
        plan_tier=plan_tier,
        status=TenantStatus.PROVISIONED,
        metadata=metadata or {},
    )


def _check_transition(current: TenantStatus, target: TenantStatus) -> None:
    """Prueft ob Transition erlaubt ist. Raise sonst."""
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise LifecycleTransitionError(
            f"Ungueltige Transition: {current.value} -> {target.value}. "
            f"Gueltig: {[t.value for t in VALID_TRANSITIONS.get(current, set())]}"
        )


def activate(tenant: Tenant) -> Tenant:
    """PROVISIONED|SUSPENDED -> ACTIVE."""
    _check_transition(tenant.status, TenantStatus.ACTIVE)
    tenant.status = TenantStatus.ACTIVE
    if tenant.activated_at is None:
        tenant.activated_at = _now_utc()
    tenant.suspended_at = None  # Clear auf re-activation
    return tenant


def suspend(tenant: Tenant, reason: str = "") -> Tenant:
    """ACTIVE -> SUSPENDED."""
    _check_transition(tenant.status, TenantStatus.SUSPENDED)
    tenant.status = TenantStatus.SUSPENDED
    tenant.suspended_at = _now_utc()
    if reason:
        tenant.metadata["suspension_reason"] = reason
    return tenant


def reactivate(tenant: Tenant) -> Tenant:
    """SUSPENDED -> ACTIVE (Alias auf activate)."""
    if tenant.status != TenantStatus.SUSPENDED:
        raise LifecycleTransitionError(
            f"reactivate nur aus SUSPENDED, war {tenant.status.value}"
        )
    return activate(tenant)


def decommission(tenant: Tenant, reason: str = "") -> Tenant:
    """PROVISIONED|ACTIVE|SUSPENDED -> DECOMMISSIONED."""
    _check_transition(tenant.status, TenantStatus.DECOMMISSIONED)
    tenant.status = TenantStatus.DECOMMISSIONED
    tenant.decommissioned_at = _now_utc()
    if reason:
        tenant.metadata["decommission_reason"] = reason
    return tenant


def archive(tenant: Tenant) -> Tenant:
    """DECOMMISSIONED -> ARCHIVED (Terminal)."""
    _check_transition(tenant.status, TenantStatus.ARCHIVED)
    tenant.status = TenantStatus.ARCHIVED
    tenant.archived_at = _now_utc()
    return tenant


def is_billable(tenant: Tenant) -> bool:
    """True wenn Tenant abrechenbar (ACTIVE oder SUSPENDED)."""
    return tenant.status in (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


def is_terminal(tenant: Tenant) -> bool:
    """True wenn Tenant in Terminal-State (ARCHIVED)."""
    return tenant.status == TenantStatus.ARCHIVED
