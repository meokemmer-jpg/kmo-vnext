"""Tenant-Model Tests [CRUX-MK]."""
import pytest
from datetime import datetime, timezone
from uuid import UUID

from src.tenant import Tenant, TenantStatus, PlanTier, canonical_record_hash


def test_tenant_creation_happy_path():
    t = Tenant(name="Hotel Alpha", plan_tier=PlanTier.PROFESSIONAL)
    assert t.status == TenantStatus.PROVISIONED
    assert isinstance(t.id, UUID)
    assert t.created_at.tzinfo is not None
    assert t.activated_at is None


def test_tenant_empty_name_rejected():
    with pytest.raises(ValueError, match="name"):
        Tenant(name="", plan_tier=PlanTier.STARTER)


def test_tenant_string_plan_tier_normalized():
    t = Tenant(name="Hotel B", plan_tier="ENTERPRISE")
    assert t.plan_tier == PlanTier.ENTERPRISE


def test_tenant_to_dict_serializable():
    t = Tenant(name="Hotel C", plan_tier=PlanTier.STARTER)
    d = t.to_dict()
    assert d["status"] == "PROVISIONED"
    assert d["plan_tier"] == "STARTER"
    assert isinstance(d["id"], str)


def test_canonical_hash_deterministic():
    t1 = Tenant(name="Hotel D", plan_tier=PlanTier.PROFESSIONAL)
    h1 = t1.compute_hash()
    h2 = t1.compute_hash()
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex


def test_canonical_hash_different_for_different_tenants():
    t1 = Tenant(name="Hotel A", plan_tier=PlanTier.STARTER)
    t2 = Tenant(name="Hotel B", plan_tier=PlanTier.STARTER)
    assert t1.compute_hash() != t2.compute_hash()


def test_tenant_activated_before_created_rejected():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    activated = datetime(2025, 12, 31, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="activated_at"):
        Tenant(
            name="Hotel X", plan_tier=PlanTier.STARTER,
            created_at=created, activated_at=activated,
        )
