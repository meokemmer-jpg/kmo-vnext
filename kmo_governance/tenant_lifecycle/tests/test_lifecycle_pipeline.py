"""Lifecycle-Pipeline Tests [CRUX-MK]."""
import pytest

from src.lifecycle_pipeline import (
    provision, activate, suspend, reactivate, decommission, archive,
    is_billable, is_terminal, LifecycleTransitionError,
)
from src.tenant import Tenant, TenantStatus, PlanTier


def test_provision_happy_path():
    t = provision("Hotel Alpha", PlanTier.PROFESSIONAL)
    assert t.status == TenantStatus.PROVISIONED
    assert t.activated_at is None


def test_activate_from_provisioned():
    t = provision("Hotel B", PlanTier.STARTER)
    activate(t)
    assert t.status == TenantStatus.ACTIVE
    assert t.activated_at is not None


def test_suspend_from_active():
    t = provision("Hotel C", PlanTier.ENTERPRISE)
    activate(t)
    suspend(t, reason="payment failed")
    assert t.status == TenantStatus.SUSPENDED
    assert t.metadata["suspension_reason"] == "payment failed"


def test_reactivate_from_suspended():
    t = provision("Hotel D", PlanTier.STARTER)
    activate(t)
    suspend(t)
    reactivate(t)
    assert t.status == TenantStatus.ACTIVE
    assert t.suspended_at is None


def test_decommission_from_active():
    t = provision("Hotel E", PlanTier.STARTER)
    activate(t)
    decommission(t, reason="customer cancellation")
    assert t.status == TenantStatus.DECOMMISSIONED


def test_archive_from_decommissioned():
    t = provision("Hotel F", PlanTier.STARTER)
    activate(t)
    decommission(t)
    archive(t)
    assert t.status == TenantStatus.ARCHIVED
    assert is_terminal(t)


def test_invalid_transition_archive_from_active():
    t = provision("Hotel G", PlanTier.STARTER)
    activate(t)
    with pytest.raises(LifecycleTransitionError):
        archive(t)


def test_invalid_transition_activate_from_archived():
    t = provision("Hotel H", PlanTier.STARTER)
    activate(t)
    decommission(t)
    archive(t)
    with pytest.raises(LifecycleTransitionError):
        activate(t)


def test_invalid_transition_suspend_from_provisioned():
    t = provision("Hotel I", PlanTier.STARTER)
    with pytest.raises(LifecycleTransitionError):
        suspend(t)


def test_decommission_from_provisioned_allowed():
    """Cancel before activation."""
    t = provision("Hotel J", PlanTier.STARTER)
    decommission(t)
    assert t.status == TenantStatus.DECOMMISSIONED


def test_is_billable_only_active_or_suspended():
    t = provision("Hotel K", PlanTier.STARTER)
    assert not is_billable(t)
    activate(t)
    assert is_billable(t)
    suspend(t)
    assert is_billable(t)  # Suspended ist immer noch abrechenbar


def test_reactivate_only_from_suspended():
    t = provision("Hotel L", PlanTier.STARTER)
    activate(t)
    with pytest.raises(LifecycleTransitionError):
        reactivate(t)
