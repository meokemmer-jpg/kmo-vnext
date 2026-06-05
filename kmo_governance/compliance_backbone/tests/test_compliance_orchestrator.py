"""Compliance-Orchestrator Tests [CRUX-MK]."""
import pytest
from uuid import uuid4

from src.compliance_orchestrator import (
    ComplianceOrchestrator, ComplianceCheckResult, ComplianceStatus,
)


def test_default_check_returns_pass():
    o = ComplianceOrchestrator()
    r = o.check_consent(uuid4())
    assert r.status == ComplianceStatus.PASS


def test_check_with_stale_context_fails():
    o = ComplianceOrchestrator()
    r = o.check_retention(uuid4(), context={"backup": "stale"})
    assert r.status == ComplianceStatus.FAIL


def test_check_with_warn_context():
    o = ComplianceOrchestrator()
    r = o.check_cross_border(uuid4(), context={"alert": "warn"})
    assert r.status == ComplianceStatus.WARN


def test_summary_aggregates_pass():
    o = ComplianceOrchestrator()
    s = o.compliance_summary(uuid4())
    assert s["overall_status"] == "PASS"
    assert "consent" in s["details"]
    assert "retention" in s["details"]
    assert "cross_border" in s["details"]
    assert "dpia" in s["details"]


def test_summary_aggregates_fail():
    o = ComplianceOrchestrator()
    s = o.compliance_summary(uuid4(), context={"flag": "missing"})
    assert s["overall_status"] == "FAIL"


def test_summary_aggregates_warn():
    o = ComplianceOrchestrator()
    s = o.compliance_summary(uuid4(), context={"flag": "warn"})
    assert s["overall_status"] == "WARN"


def test_record_hash_set():
    o = ComplianceOrchestrator()
    r = o.check_consent(uuid4())
    assert r.record_hash is not None
    assert len(r.record_hash) == 64


def test_custom_auditor_hook():
    def my_auditor(tenant_id, check_type, context):
        return {"status": "FAIL", "findings": ["custom"]}
    o = ComplianceOrchestrator(auditor_hook=my_auditor)
    r = o.check_dpia(uuid4())
    assert r.status == ComplianceStatus.FAIL
    assert "custom" in r.findings


def test_to_dict_serializable():
    r = ComplianceCheckResult(
        tenant_id=uuid4(), check_type="consent", status=ComplianceStatus.PASS,
    )
    d = r.to_dict()
    assert d["status"] == "PASS"
    assert d["check_type"] == "consent"


def test_check_dpia_method_exists():
    o = ComplianceOrchestrator()
    r = o.check_dpia(uuid4())
    assert r.check_type == "dpia"
