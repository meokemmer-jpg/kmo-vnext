"""DPIA-per-Tenant Tests [CRUX-MK]."""
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.dpia_per_tenant import (
    DPIAPerTenant, DPIAStatus, RiskLevel,
    activate_dpia, supersede_dpia, expire_if_overdue,
    is_active, derive_risk_level,
)


def test_dpia_creation_happy_path():
    d = DPIAPerTenant(
        tenant_id=uuid4(), processing_activity="Hotel-Booking",
        risk_score=0.5, risk_level=RiskLevel.MEDIUM,
    )
    assert d.status == DPIAStatus.DRAFT


def test_invalid_risk_score_rejected():
    with pytest.raises(ValueError):
        DPIAPerTenant(
            tenant_id=uuid4(), processing_activity="x",
            risk_score=1.5, risk_level=RiskLevel.HIGH,
        )


def test_empty_activity_rejected():
    with pytest.raises(ValueError):
        DPIAPerTenant(
            tenant_id=uuid4(), processing_activity="",
            risk_score=0.5, risk_level=RiskLevel.MEDIUM,
        )


def test_activate_sets_validity():
    d = DPIAPerTenant(
        tenant_id=uuid4(), processing_activity="x",
        risk_score=0.4, risk_level=RiskLevel.MEDIUM,
    )
    activate_dpia(d, validity_days=30)
    assert d.status == DPIAStatus.ACTIVE
    assert d.valid_until is not None
    assert d.valid_until > d.valid_from


def test_supersede_dpia():
    tid = uuid4()
    old = DPIAPerTenant(tenant_id=tid, processing_activity="v1",
                         risk_score=0.4, risk_level=RiskLevel.MEDIUM)
    activate_dpia(old)
    new = DPIAPerTenant(tenant_id=tid, processing_activity="v2",
                         risk_score=0.5, risk_level=RiskLevel.MEDIUM)
    supersede_dpia(old, new)
    assert old.status == DPIAStatus.SUPERSEDED
    assert old.superseded_by == new.id
    assert new.status == DPIAStatus.ACTIVE


def test_supersede_different_tenant_rejected():
    old = DPIAPerTenant(tenant_id=uuid4(), processing_activity="x",
                         risk_score=0.4, risk_level=RiskLevel.MEDIUM)
    activate_dpia(old)
    new = DPIAPerTenant(tenant_id=uuid4(), processing_activity="y",
                         risk_score=0.5, risk_level=RiskLevel.MEDIUM)
    with pytest.raises(ValueError, match="tenant"):
        supersede_dpia(old, new)


def test_expire_if_overdue():
    d = DPIAPerTenant(tenant_id=uuid4(), processing_activity="x",
                       risk_score=0.4, risk_level=RiskLevel.MEDIUM)
    activate_dpia(d, validity_days=10)
    future = datetime.now(timezone.utc) + timedelta(days=20)
    expire_if_overdue(d, now=future)
    assert d.status == DPIAStatus.EXPIRED


def test_is_active_currently():
    d = DPIAPerTenant(tenant_id=uuid4(), processing_activity="x",
                       risk_score=0.5, risk_level=RiskLevel.MEDIUM)
    activate_dpia(d)
    assert is_active(d)


def test_is_not_active_after_expiry():
    d = DPIAPerTenant(tenant_id=uuid4(), processing_activity="x",
                       risk_score=0.5, risk_level=RiskLevel.MEDIUM)
    activate_dpia(d, validity_days=1)
    future = datetime.now(timezone.utc) + timedelta(days=5)
    assert not is_active(d, now=future)


def test_derive_risk_level():
    assert derive_risk_level(0.1) == RiskLevel.LOW
    assert derive_risk_level(0.4) == RiskLevel.MEDIUM
    assert derive_risk_level(0.7) == RiskLevel.HIGH
    assert derive_risk_level(0.9) == RiskLevel.VERY_HIGH


def test_compute_hash():
    d = DPIAPerTenant(tenant_id=uuid4(), processing_activity="x",
                       risk_score=0.5, risk_level=RiskLevel.MEDIUM)
    h1 = d.compute_hash()
    h2 = d.compute_hash()
    assert h1 == h2
    assert len(h1) == 64


def test_activate_only_from_draft():
    d = DPIAPerTenant(tenant_id=uuid4(), processing_activity="x",
                       risk_score=0.5, risk_level=RiskLevel.MEDIUM)
    activate_dpia(d)
    with pytest.raises(ValueError, match="DRAFT"):
        activate_dpia(d)
