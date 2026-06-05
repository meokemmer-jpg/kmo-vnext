"""Approval-Gate Tests [CRUX-MK]."""
import pytest
from uuid import uuid4

from src.approval_request import (
    ApprovalRequest, ApprovalStatus, OperationCategory,
)
from src.approval_gate import (
    pre_action_check, apply_decision, is_approved, is_blocked, needs_escalation,
)


def _req(category=OperationCategory.TENANT_ACTIVATION, env_tag="prod",
         blast_radius=1, reversibility="state-only", phronesis=False):
    return ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=category,
        operation_description="test",
        requested_by="test_pipeline",
        env_tag=env_tag,
        blast_radius=blast_radius,
        reversibility=reversibility,
        requires_martin_phronesis=phronesis,
    )


def test_happy_path_approval():
    r = _req()
    result = pre_action_check(r)
    assert is_approved(result)


def test_phronesis_always_escalates():
    r = _req(phronesis=True)
    result = pre_action_check(r)
    assert needs_escalation(result)
    assert any("PHRONESIS" in s for s in result["reasons"])


def test_cross_tenant_sharing_blocked_without_policy():
    r = _req(category=OperationCategory.CROSS_TENANT_DATA_SHARING)
    result = pre_action_check(r, allow_cross_tenant_sharing=False)
    assert is_blocked(result)


def test_cross_tenant_sharing_escalates_with_policy():
    r = _req(category=OperationCategory.CROSS_TENANT_DATA_SHARING)
    result = pre_action_check(r, allow_cross_tenant_sharing=True)
    assert needs_escalation(result)


def test_data_deletion_nonreversible_prod_blocked():
    r = _req(
        category=OperationCategory.DATA_DELETION,
        reversibility="non-reversible",
    )
    result = pre_action_check(r)
    assert is_blocked(result)


def test_high_blast_radius_prod_escalates():
    r = _req(blast_radius=200)
    result = pre_action_check(r)
    assert needs_escalation(result)


def test_extreme_blast_radius_prod_blocked():
    r = _req(blast_radius=10000)
    result = pre_action_check(r)
    assert is_blocked(result)


def test_dev_env_low_blast_approved():
    r = _req(env_tag="dev", blast_radius=500)
    result = pre_action_check(r)
    assert is_approved(result)  # dev kein blast-radius-cap


def test_apply_decision_mutates_request():
    r = _req()
    result = pre_action_check(r)
    apply_decision(r, result, decided_by="auto_gate")
    assert r.status == ApprovalStatus.APPROVED
    assert r.decided_by == "auto_gate"
    assert r.decided_at is not None


def test_non_reversible_prod_escalates():
    r = _req(reversibility="non-reversible")
    result = pre_action_check(r)
    assert needs_escalation(result)
