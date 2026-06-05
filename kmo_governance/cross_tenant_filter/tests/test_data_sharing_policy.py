"""Cross-Tenant Policy-Decision-Point Tests [CRUX-MK]."""
import pytest
from uuid import uuid4

from src.data_sharing_policy import (
    PolicyDecisionPoint, SharingPolicy, SharingRequest,
    PolicyDecision, DataSensitivity,
)


def test_no_policy_denies():
    pdp = PolicyDecisionPoint()
    req = SharingRequest(
        source_tenant_id=uuid4(), target_tenant_id=uuid4(),
        sensitivity=DataSensitivity.INTERNAL, record_count=100,
        purpose="Benchmarking",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.DENY.value


def test_same_tenant_always_allowed():
    pdp = PolicyDecisionPoint()
    tid = uuid4()
    req = SharingRequest(
        source_tenant_id=tid, target_tenant_id=tid,
        sensitivity=DataSensitivity.PII, record_count=1,
        purpose="self-access",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.ALLOW.value


def test_matching_policy_with_anonymization():
    src, tgt = uuid4(), uuid4()
    policy = SharingPolicy(
        source_tenant_id=src, target_tenant_id=tgt,
        allowed_data_sensitivities={DataSensitivity.INTERNAL},
        require_anonymization=True,
    )
    pdp = PolicyDecisionPoint(policies=[policy])
    req = SharingRequest(
        source_tenant_id=src, target_tenant_id=tgt,
        sensitivity=DataSensitivity.INTERNAL, record_count=10,
        purpose="benchmark",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.ALLOW_WITH_ANONYMIZATION.value


def test_low_record_count_violates_k_anonymity():
    src, tgt = uuid4(), uuid4()
    policy = SharingPolicy(
        source_tenant_id=src, target_tenant_id=tgt,
        allowed_data_sensitivities={DataSensitivity.INTERNAL},
        require_anonymization=True,
    )
    pdp = PolicyDecisionPoint(policies=[policy])
    req = SharingRequest(
        source_tenant_id=src, target_tenant_id=tgt,
        sensitivity=DataSensitivity.INTERNAL, record_count=2,  # < k=5
        purpose="too few",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.DENY.value
    assert any("k-Anonymity" in r for r in result["reasons"])


def test_public_data_no_anonymization_needed():
    src, tgt = uuid4(), uuid4()
    policy = SharingPolicy(
        source_tenant_id=src, target_tenant_id=tgt,
        allowed_data_sensitivities={DataSensitivity.PUBLIC},
        require_anonymization=True,
    )
    pdp = PolicyDecisionPoint(policies=[policy])
    req = SharingRequest(
        source_tenant_id=src, target_tenant_id=tgt,
        sensitivity=DataSensitivity.PUBLIC, record_count=1,
        purpose="public",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.ALLOW.value


def test_unmatched_sensitivity_denies():
    src, tgt = uuid4(), uuid4()
    policy = SharingPolicy(
        source_tenant_id=src, target_tenant_id=tgt,
        allowed_data_sensitivities={DataSensitivity.PUBLIC},
    )
    pdp = PolicyDecisionPoint(policies=[policy])
    req = SharingRequest(
        source_tenant_id=src, target_tenant_id=tgt,
        sensitivity=DataSensitivity.PII, record_count=100,
        purpose="x",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.DENY.value


def test_invalid_record_count_rejected():
    with pytest.raises(ValueError):
        SharingRequest(
            source_tenant_id=uuid4(), target_tenant_id=uuid4(),
            sensitivity=DataSensitivity.PUBLIC, record_count=-5,
            purpose="x",
        )


def test_empty_purpose_rejected():
    with pytest.raises(ValueError):
        SharingRequest(
            source_tenant_id=uuid4(), target_tenant_id=uuid4(),
            sensitivity=DataSensitivity.PUBLIC, record_count=10,
            purpose="",
        )


def test_add_policy_dynamically():
    pdp = PolicyDecisionPoint()
    src, tgt = uuid4(), uuid4()
    pdp.add_policy(SharingPolicy(
        source_tenant_id=src, target_tenant_id=tgt,
        allowed_data_sensitivities={DataSensitivity.PUBLIC},
        require_anonymization=False,
    ))
    req = SharingRequest(
        source_tenant_id=src, target_tenant_id=tgt,
        sensitivity=DataSensitivity.PUBLIC, record_count=10,
        purpose="x",
    )
    result = pdp.decide(req)
    assert result["decision"] == PolicyDecision.ALLOW.value


def test_policy_string_sensitivities_normalized():
    p = SharingPolicy(
        source_tenant_id=uuid4(), target_tenant_id=uuid4(),
        allowed_data_sensitivities={"INTERNAL", "PUBLIC"},
    )
    assert DataSensitivity.INTERNAL in p.allowed_data_sensitivities
    assert DataSensitivity.PUBLIC in p.allowed_data_sensitivities
