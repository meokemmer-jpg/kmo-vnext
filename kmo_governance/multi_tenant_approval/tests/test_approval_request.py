"""ApprovalRequest Tests [CRUX-MK]."""
import pytest
from uuid import uuid4

from src.approval_request import (
    ApprovalRequest, ApprovalStatus, OperationCategory,
)


def test_request_creation_happy_path():
    r = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.TENANT_ACTIVATION,
        operation_description="Activate Hotel Alpha",
        requested_by="onboarding_pipeline",
        env_tag="prod",
        blast_radius=1,
    )
    assert r.status == ApprovalStatus.PENDING
    assert r.operation_category == OperationCategory.TENANT_ACTIVATION


def test_invalid_env_tag_rejected():
    with pytest.raises(ValueError, match="env_tag"):
        ApprovalRequest(
            tenant_id=uuid4(),
            operation_category=OperationCategory.TENANT_ACTIVATION,
            operation_description="x",
            requested_by="y",
            env_tag="production",  # invalid
        )


def test_empty_description_rejected():
    with pytest.raises(ValueError, match="operation_description"):
        ApprovalRequest(
            tenant_id=uuid4(),
            operation_category=OperationCategory.TENANT_ACTIVATION,
            operation_description="   ",
            requested_by="y",
            env_tag="dev",
        )


def test_negative_blast_radius_rejected():
    with pytest.raises(ValueError, match="blast_radius"):
        ApprovalRequest(
            tenant_id=uuid4(),
            operation_category=OperationCategory.TENANT_ACTIVATION,
            operation_description="x",
            requested_by="y",
            env_tag="dev",
            blast_radius=-1,
        )


def test_to_dict_serializable():
    r = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.PLAN_UPGRADE,
        operation_description="upgrade",
        requested_by="x",
        env_tag="staging",
    )
    d = r.to_dict()
    assert d["operation_category"] == "PLAN_UPGRADE"
    assert d["status"] == "PENDING"


def test_compute_hash_deterministic():
    r = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.PLAN_UPGRADE,
        operation_description="upgrade",
        requested_by="x",
        env_tag="staging",
    )
    h1 = r.compute_hash()
    h2 = r.compute_hash()
    assert h1 == h2
    assert len(h1) == 64


def test_string_category_normalized():
    r = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category="DATA_DELETION",
        operation_description="x",
        requested_by="y",
        env_tag="dev",
    )
    assert r.operation_category == OperationCategory.DATA_DELETION
