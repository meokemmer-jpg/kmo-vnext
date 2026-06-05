"""Cross-Module Integration-Tests [CRUX-MK].

End-to-End-Flow:
1. Tenant provisioned (Module-1)
2. Approval-Gate genehmigt Activation (Module-2)
3. Compliance-Backbone audit Tenant (Module-3)
4. Cross-Tenant-Sharing wird angefragt + entschieden (Module-4)
5. Hot-Switch-Router routed Operations (Module-5)

Da die 5 Module den Namespace `src/` teilen, wird jeder Test in einem
isolierten Subprocess ausgefuehrt (via subprocess.run mit Python-Snippet).
Dies entspricht dem real-world-Pattern von DF-Cron-Workflows.
"""
import pytest
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _run_in_module(module_dir: str, code: str) -> str:
    """Fuehrt Python-Code im Kontext eines Modul-Verzeichnisses aus."""
    full_code = textwrap.dedent(f"""
import sys
sys.path.insert(0, r"{ROOT / module_dir}")
{code}
print("INTEGRATION_OK")
""")
    proc = subprocess.run(
        [sys.executable, "-c", full_code],
        capture_output=True, text=True, cwd=str(ROOT / module_dir),
    )
    if "INTEGRATION_OK" not in proc.stdout:
        raise AssertionError(
            f"Test failed.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return proc.stdout


def test_full_onboarding_flow():
    """E2E: Provision -> Approval-Gate -> Activation."""
    # Tenant-Lifecycle Test
    _run_in_module("tenant_lifecycle", """
from src.lifecycle_pipeline import provision, activate
from src.tenant import PlanTier, TenantStatus
t = provision("Hotel Charlie", PlanTier.PROFESSIONAL)
assert t.status == TenantStatus.PROVISIONED
activate(t)
assert t.status == TenantStatus.ACTIVE
""")

    # Approval-Gate Test (separate process, no namespace clash)
    _run_in_module("multi_tenant_approval", """
from uuid import uuid4
from src.approval_request import ApprovalRequest, OperationCategory
from src.approval_gate import pre_action_check, is_approved
req = ApprovalRequest(
    tenant_id=uuid4(),
    operation_category=OperationCategory.TENANT_ACTIVATION,
    operation_description="Activate Hotel Charlie",
    requested_by="onboarding_pipeline",
    env_tag="prod",
    blast_radius=1,
)
result = pre_action_check(req)
assert is_approved(result)
""")


def test_approval_gate_blocks_phronesis_required():
    """K_0-Hard-No-Delegate: requires_martin_phronesis -> ESCALATE."""
    _run_in_module("multi_tenant_approval", """
from uuid import uuid4
from src.approval_request import ApprovalRequest, OperationCategory
from src.approval_gate import pre_action_check, needs_escalation
req = ApprovalRequest(
    tenant_id=uuid4(),
    operation_category=OperationCategory.PLAN_UPGRADE,
    operation_description="upgrade to Enterprise (K_0)",
    requested_by="auto",
    env_tag="prod",
    requires_martin_phronesis=True,
)
result = pre_action_check(req)
assert needs_escalation(result)
assert any("PHRONESIS" in r for r in result["reasons"])
""")


def test_dpia_lifecycle_per_tenant():
    """DPIA-Lifecycle pro Tenant: DRAFT -> ACTIVE -> SUPERSEDED."""
    _run_in_module("compliance_backbone", """
from uuid import uuid4
from src.dpia_per_tenant import (
    DPIAPerTenant, DPIAStatus, RiskLevel, activate_dpia, supersede_dpia,
)
tid = uuid4()
d1 = DPIAPerTenant(
    tenant_id=tid, processing_activity="v1", risk_score=0.4,
    risk_level=RiskLevel.MEDIUM,
)
activate_dpia(d1)
assert d1.status == DPIAStatus.ACTIVE
d2 = DPIAPerTenant(
    tenant_id=tid, processing_activity="v2-revised", risk_score=0.6,
    risk_level=RiskLevel.HIGH,
)
supersede_dpia(d1, d2)
assert d1.status == DPIAStatus.SUPERSEDED
assert d2.status == DPIAStatus.ACTIVE
""")


def test_cross_tenant_sharing_blocked_by_default():
    """Cross-Tenant-Sharing default DENY ohne Policy."""
    _run_in_module("cross_tenant_filter", """
from uuid import uuid4
from src.data_sharing_policy import (
    PolicyDecisionPoint, SharingRequest, DataSensitivity, PolicyDecision,
)
pdp = PolicyDecisionPoint()
req = SharingRequest(
    source_tenant_id=uuid4(), target_tenant_id=uuid4(),
    sensitivity=DataSensitivity.INTERNAL, record_count=10,
    purpose="benchmark",
)
result = pdp.decide(req)
assert result["decision"] == PolicyDecision.DENY.value
""")


def test_hot_switch_failover_isolates_per_tenant():
    """Adapter-Failure Tenant A betrifft Tenant B nicht."""
    _run_in_module("hot_switch_adapter", """
from src.failover_orchestrator import FailoverOrchestrator
o = FailoverOrchestrator()
o.configure_tenant(
    "tenant-A", primary="apaleo",
    adapter_hooks={"apaleo": lambda tid, p: (_ for _ in ()).throw(RuntimeError("down"))},
)
o.configure_tenant(
    "tenant-B", primary="apaleo",
    adapter_hooks={"apaleo": lambda tid, p: {"ok": True}},
)
o.call("tenant-A", {})
res_b = o.call("tenant-B", {})
assert res_b.success
overview = o.health_overview()
assert overview["tenant-A"]["apaleo"]["consecutive_fails"] == 1
assert overview["tenant-B"]["apaleo"]["consecutive_successes"] == 1
""")
