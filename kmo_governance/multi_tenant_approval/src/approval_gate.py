# Approval-Gate-Logic [CRUX-MK]
"""
Approval-Gate mit Pre-Action-Check (PocketOS-Lehre Pattern aus DF-W8-11).

Decision-Logic:
- Wenn requires_martin_phronesis=True -> ESCALATE (Hard-No-Delegate)
- Wenn env_tag=prod + non-reversible + blast_radius>100 -> ESCALATE
- Wenn env_tag=prod + DATA_DELETION + non-reversible -> BLOCK (zu riskant)
- Wenn CROSS_TENANT_DATA_SHARING ohne explicit policy -> BLOCK
- Sonst: APPROVE (mit Audit-Trail)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .approval_request import (
    ApprovalRequest, ApprovalStatus, OperationCategory,
)


# === Default-Policy Konstanten ===

PROD_ESCALATE_BLAST_THRESHOLD = 100
PROD_BLOCK_BLAST_THRESHOLD = 5000
HARD_BLOCKED_CATEGORIES_ON_PROD_NONREVERSIBLE = {
    OperationCategory.DATA_DELETION,
}
ESCALATE_ALWAYS_CATEGORIES = {
    OperationCategory.CROSS_TENANT_DATA_SHARING,
}


def pre_action_check(request: ApprovalRequest,
                     allow_cross_tenant_sharing: bool = False) -> dict[str, Any]:
    """Approval-Gate Pre-Action-Check.

    Args:
        request: ApprovalRequest mit env_tag, blast_radius, reversibility, category.
        allow_cross_tenant_sharing: Wenn True, Cross-Tenant-Sharing wird durchgelassen
            (sonst BLOCK ohne explizite Policy).

    Returns:
        {
            "decision": "APPROVED"|"BLOCKED"|"ESCALATED",
            "reasons": [str, ...],
            "checked_at": iso-datetime,
            "request_id": str,
        }
    """
    reasons: list[str] = []
    decision = ApprovalStatus.APPROVED

    # 1. Phronesis-Hard-No-Delegate
    if request.requires_martin_phronesis:
        reasons.append(
            "PHRONESIS-PFLICHT: requires_martin_phronesis=True (K_0/Q_0/L13)"
        )
        decision = ApprovalStatus.ESCALATED

    # 2. Cross-Tenant-Data-Sharing braucht explicit policy
    if request.operation_category in ESCALATE_ALWAYS_CATEGORIES:
        if not allow_cross_tenant_sharing:
            reasons.append(
                f"BLOCK: {request.operation_category.value} braucht explicit policy "
                f"(allow_cross_tenant_sharing=False)"
            )
            decision = ApprovalStatus.BLOCKED
        else:
            reasons.append(
                f"ESCALATE: {request.operation_category.value} mit policy "
                f"-> Audit-Pflicht"
            )
            if decision != ApprovalStatus.BLOCKED:
                decision = ApprovalStatus.ESCALATED

    # 3. Prod + DATA_DELETION + non-reversible -> Hard-Block
    if (
        request.env_tag == "prod"
        and request.operation_category in HARD_BLOCKED_CATEGORIES_ON_PROD_NONREVERSIBLE
        and request.reversibility == "non-reversible"
    ):
        reasons.append(
            "BLOCK: DATA_DELETION + non-reversible auf prod (PocketOS-Lehre)"
        )
        decision = ApprovalStatus.BLOCKED

    # 4. Prod-Blast-Radius-Schwellen
    if request.env_tag == "prod":
        if request.blast_radius >= PROD_BLOCK_BLAST_THRESHOLD:
            reasons.append(
                f"BLOCK: blast_radius {request.blast_radius} >= "
                f"PROD_BLOCK_BLAST_THRESHOLD {PROD_BLOCK_BLAST_THRESHOLD}"
            )
            decision = ApprovalStatus.BLOCKED
        elif request.blast_radius >= PROD_ESCALATE_BLAST_THRESHOLD:
            reasons.append(
                f"ESCALATE: blast_radius {request.blast_radius} >= "
                f"PROD_ESCALATE_BLAST_THRESHOLD {PROD_ESCALATE_BLAST_THRESHOLD}"
            )
            if decision == ApprovalStatus.APPROVED:
                decision = ApprovalStatus.ESCALATED

    # 5. Non-reversible auf prod -> ESCALATE (analog DF-W8-11)
    if (
        request.env_tag == "prod"
        and request.reversibility == "non-reversible"
        and decision == ApprovalStatus.APPROVED
    ):
        reasons.append(
            "ESCALATE: non-reversible Operation auf prod (PocketOS-Lehre)"
        )
        decision = ApprovalStatus.ESCALATED

    return {
        "decision": decision.value,
        "reasons": reasons,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "request_id": str(request.id),
    }


def apply_decision(request: ApprovalRequest, check_result: dict[str, Any],
                   decided_by: str = "approval_gate") -> ApprovalRequest:
    """Wendet check_result auf Request an (mutiert request)."""
    decision_str = check_result["decision"]
    request.status = ApprovalStatus(decision_str)
    request.decision_reasons = list(check_result.get("reasons", []))
    request.decided_at = datetime.now(timezone.utc)
    request.decided_by = decided_by
    return request


def is_approved(check_result: dict[str, Any]) -> bool:
    return check_result.get("decision") == ApprovalStatus.APPROVED.value


def is_blocked(check_result: dict[str, Any]) -> bool:
    return check_result.get("decision") == ApprovalStatus.BLOCKED.value


def needs_escalation(check_result: dict[str, Any]) -> bool:
    return check_result.get("decision") == ApprovalStatus.ESCALATED.value
