"""CRUX-MK M-15: Hotel-Membrane tenant-isolation pattern (Welle-11.3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import field
import time
from typing import TYPE_CHECKING

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from df_89.knowledge import KnowledgeStore

AuditCallback = Callable[[str, str, str, bool], None]
WELLE_VERSION = "11.3-bottleneck-lift"


@dataclass(config=ConfigDict(validate_assignment=True))
class Tenant:
    """Single tenant in hotel-membrane network.

    Pre: tenant_id non-blank, quota values non-negative. Post: isolated quota cytoplasm.
    """

    tenant_id: str
    quota_remaining: dict[str, int]
    allowed_cross_tenants: set[str] = field(default_factory=set)
    last_activity: float = 0.0

    def __post_init__(self) -> None:
        """Pre: pydantic assigned fields. Post: Tenant invariants hold."""
        _tenant_id(self.tenant_id)
        _validate_quota(self.quota_remaining, allow_empty=False)
        if self.last_activity < 0.0:
            raise ValueError("last_activity must be non-negative")


class HotelMembrane:
    """Tenant-Isolation via cell-membrane-style boundary.

    Implements selective permeability + active transport + audit.
    Use-cases:
    - Multi-Hotel-DF-System (DF-89 instance per Hotel-Tenant)
    - LLM-Token-Quota-Enforcement (pro Hotel)
    - Cross-Hotel-Audit (Compliance, GDPR)
    - Resource-Allocation in Multi-Tenant SaaS

    Pre: default_quota non-empty and non-negative. Post: append-only audit is initialized.
    """

    def __init__(
        self,
        default_quota: dict[str, int],
        strict_mode: bool = True,
        audit_callback: AuditCallback | None = None,
        knowledge_store: "KnowledgeStore | None" = None,
    ):
        """Pre: default_quota has named resources. Post: empty membrane exists."""
        _validate_quota(default_quota, allow_empty=False)
        self.default_quota = dict(default_quota)
        self.strict_mode = strict_mode
        self.audit_callback = audit_callback
        self.knowledge_store = knowledge_store
        self.tenants: dict[str, Tenant] = {}
        self._audit_violations: list[tuple[str, str, str]] = []
        self._quota_denials: list[tuple[str, str, int, str]] = []
        self._event_count = 0

    def register_tenant(self, tenant_id: str, quota: dict[str, int] | None = None) -> None:
        """Pre: tenant_id non-empty, quota >= 0. Post: tenant accessible via APIs."""
        tenant_id = _tenant_id(tenant_id)
        if tenant_id in self.tenants:
            raise ValueError(f"tenant already exists: {tenant_id}")
        quota_remaining = dict(self.default_quota if quota is None else quota)
        _validate_quota(quota_remaining, allow_empty=False)
        self.tenants[tenant_id] = Tenant(tenant_id, quota_remaining, last_activity=time.monotonic())

    def request_resource(self, tenant_id: str, resource: str, amount: int = 1) -> bool:
        """Active transport. Returns True if permitted, False else.

        Pre: tenant registered, resource known, amount positive.
        Post: quota decremented only when True; overflow is append-only audited.
        """
        tenant = self._tenant(tenant_id)
        _amount(amount)
        self._known_resource(tenant, resource)
        if tenant.quota_remaining[resource] < amount:
            self._audit_quota_denial(tenant.tenant_id, resource, amount)
            return False
        tenant.quota_remaining[resource] -= amount
        tenant.last_activity = time.monotonic()
        return True

    def grant_cross_tenant(self, tenant_id: str, target: str) -> None:
        """Explicit receptor-binding. Pre: tenants registered. Post: grant marker stored."""
        source_tenant = self._tenant(tenant_id)
        target_tenant = self._tenant(target)
        source_tenant.allowed_cross_tenants.add(target_tenant.tenant_id)

    def revoke_cross_tenant(self, tenant_id: str, target: str) -> None:
        """Reverse the grant. Pre: source exists. Post: target absent from grant set."""
        self._tenant(tenant_id).allowed_cross_tenants.discard(_tenant_id(target))

    def is_allowed_cross_tenant(self, source: str, target: str) -> bool:
        """True if source has access. Pre: tenants exist. Post: self-reference is True."""
        if source == target:
            self._tenant(source)
            return True
        source_tenant = self._tenant(source)
        self._tenant(target)
        return (not self.strict_mode) or target in source_tenant.allowed_cross_tenants

    def access_cross_tenant(
        self,
        source: str,
        target: str,
        resource: str,
        amount: int = 1,
    ) -> bool:
        """Cross-tenant resource request. Audited. Returns True if granted + quota ok.

        Pre: tenants registered, resource known on target, amount positive.
        Post: denied cross-tenant attempts are append-only audited.
        """
        _amount(amount)
        source_tenant = self._tenant(source)
        target_tenant = self._tenant(target)
        self._known_resource(target_tenant, resource)
        if source_tenant.tenant_id == target_tenant.tenant_id:
            return self.request_resource(target_tenant.tenant_id, resource, amount)
        allowed = self.is_allowed_cross_tenant(source_tenant.tenant_id, target_tenant.tenant_id)
        if not allowed:
            self._audit(source_tenant.tenant_id, target_tenant.tenant_id, resource, False)
            return False
        permitted = self.request_resource(target_tenant.tenant_id, resource, amount)
        self._audit(source_tenant.tenant_id, target_tenant.tenant_id, resource, permitted)
        return permitted

    def audit_violations(self) -> list[tuple[str, str, str]]:
        """Pre: attempts may have occurred. Post: violation tuple copy is returned."""
        return list(self._audit_violations)

    def audit_quota_denials(self) -> list[tuple[str, str, int, str]]:
        """Return intra-tenant quota-denial audit entries.

        Pre: quota requests may have exceeded tenant limits.
        Post: append-only (tenant_id, resource, requested_amount, reason) copy is returned.
        """
        return list(self._quota_denials)

    def reset_quotas(self, tenant_id: str | None = None) -> None:
        """Reset quota to defaults. Pre: optional tenant exists. Post: defaults restored."""
        tenant_ids = list(self.tenants) if tenant_id is None else [tenant_id]
        for current_id in tenant_ids:
            tenant = self._tenant(current_id)
            tenant.quota_remaining = dict(self.default_quota)
            tenant.last_activity = time.monotonic()

    def _audit(self, source: str, target: str, resource: str, permitted: bool) -> None:
        if not permitted:
            self._audit_violations.append((source, target, resource))
        if self.audit_callback is not None:
            self.audit_callback(source, target, resource, permitted)
        if self.knowledge_store is None:
            return
        self._event_count += 1
        self.knowledge_store.add_methodik(
            name=f"m01_hotel_membrane:{source}:{target}:{self._event_count}",
            description=f"source={source}; target={target}; resource={resource}; permitted={permitted}",
            confidence=0.81,
            status="observed",
        )

    def _audit_quota_denial(self, tenant_id: str, resource: str, amount: int) -> None:
        reason = "quota_exhausted"
        self._quota_denials.append((tenant_id, resource, amount, reason))
        if self.audit_callback is not None:
            self.audit_callback(tenant_id, tenant_id, resource, False)
        if self.knowledge_store is None:
            return
        self._event_count += 1
        self.knowledge_store.add_methodik(
            name=f"m01_hotel_membrane:{tenant_id}:{tenant_id}:{self._event_count}",
            description=(
                f"source={tenant_id}; target={tenant_id}; resource={resource}; "
                f"amount={amount}; permitted=False; reason={reason}"
            ),
            confidence=0.81,
            status="observed",
        )

    def _tenant(self, tenant_id: str) -> Tenant:
        tenant_id = _tenant_id(tenant_id)
        if tenant_id not in self.tenants:
            raise KeyError(f"unknown tenant: {tenant_id}")
        return self.tenants[tenant_id]

    @staticmethod
    def _known_resource(tenant: Tenant, resource: str) -> None:
        if not resource.strip():
            raise ValueError("resource must not be blank")
        if resource not in tenant.quota_remaining:
            raise KeyError(f"unknown resource: {resource}")


def _tenant_id(value: str) -> str:
    if not value.strip():
        raise ValueError("tenant_id must not be blank")
    return value


def _amount(value: int) -> None:
    if value <= 0:
        raise ValueError("amount must be positive")


def _validate_quota(quota: dict[str, int], *, allow_empty: bool) -> None:
    if not allow_empty and not quota:
        raise ValueError("quota must not be empty")
    for resource, remaining in quota.items():
        if not resource.strip():
            raise ValueError("quota resource must not be blank")
        if remaining < 0:
            raise ValueError("quota values must be non-negative")


__all__ = ["AuditCallback", "Tenant", "HotelMembrane", "WELLE_VERSION"]
