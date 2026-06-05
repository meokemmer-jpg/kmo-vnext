# Compliance-Orchestrator [CRUX-MK]
"""
Compliance-Orchestrator (Mock-Integration mit DF-W8-11-Auditor).

Kapselt DF-W8-11-Aufrufe pro Tenant. In Phase-1 mit Mock-Implementierung,
in Phase-2 wird DF-W8-11 direkt importiert.

Funktionen:
- check_consent: Tenant-spezifischer Consent-Check
- check_retention: DSGVO-Retention-Check pro Tenant
- check_cross_border: Cross-Border-Transfer-Check pro Tenant
- compliance_summary: Aggregat-Status pro Tenant
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import UUID, uuid4


class ComplianceStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Type {type(obj)} not JSON-serializable")


def canonical_record_hash(record_dict: dict[str, Any]) -> str:
    clean = {k: v for k, v in record_dict.items() if k not in ("hash_chain", "record_hash")}
    canonical_json = json.dumps(
        clean, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=_json_default,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass
class ComplianceCheckResult:
    """Ergebnis eines Compliance-Checks pro Tenant + Domaene."""
    tenant_id: UUID | str
    check_type: str  # consent/retention/cross_border/dpia
    status: ComplianceStatus
    findings: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=_now_utc)
    auditor_source: str = "DF-W8-11-mock"
    record_hash: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = ComplianceStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tenant_id"] = str(self.tenant_id)
        d["status"] = self.status.value
        d["checked_at"] = self.checked_at.isoformat()
        return d


# Mock-Auditor-Hook: Kann mit echtem DF-W8-11-Auditor ueberschrieben werden in Phase-2
AuditorHook = Callable[[UUID | str, str, dict[str, Any]], dict[str, Any]]


def _mock_auditor(tenant_id: UUID | str, check_type: str,
                  context: dict[str, Any]) -> dict[str, Any]:
    """Mock-Auditor: deterministisches PASS fuer Tests, ausser bei Trigger-Keywords."""
    findings = []
    if "stale" in str(context).lower():
        return {"status": "FAIL", "findings": ["Mock: stale-Trigger detected"]}
    if "missing" in str(context).lower():
        return {"status": "FAIL", "findings": ["Mock: missing-Trigger detected"]}
    if "warn" in str(context).lower():
        return {"status": "WARN", "findings": ["Mock: warn-Trigger detected"]}
    return {"status": "PASS", "findings": []}


class ComplianceOrchestrator:
    """Orchestriert DSGVO + AI-Act Checks pro Tenant.

    Pre-Conditions: auditor_hook ist Callable mit (tenant_id, check_type, context) -> dict.
    """

    def __init__(self, auditor_hook: AuditorHook | None = None) -> None:
        self.auditor_hook = auditor_hook or _mock_auditor

    def _run_check(self, tenant_id: UUID | str, check_type: str,
                   context: dict[str, Any]) -> ComplianceCheckResult:
        result_dict = self.auditor_hook(tenant_id, check_type, context)
        result = ComplianceCheckResult(
            tenant_id=tenant_id,
            check_type=check_type,
            status=ComplianceStatus(result_dict.get("status", "UNKNOWN")),
            findings=list(result_dict.get("findings", [])),
        )
        result.record_hash = canonical_record_hash(result.to_dict())
        return result

    def check_consent(self, tenant_id: UUID | str,
                      context: dict[str, Any] | None = None) -> ComplianceCheckResult:
        return self._run_check(tenant_id, "consent", context or {})

    def check_retention(self, tenant_id: UUID | str,
                        context: dict[str, Any] | None = None) -> ComplianceCheckResult:
        return self._run_check(tenant_id, "retention", context or {})

    def check_cross_border(self, tenant_id: UUID | str,
                            context: dict[str, Any] | None = None) -> ComplianceCheckResult:
        return self._run_check(tenant_id, "cross_border", context or {})

    def check_dpia(self, tenant_id: UUID | str,
                   context: dict[str, Any] | None = None) -> ComplianceCheckResult:
        return self._run_check(tenant_id, "dpia", context or {})

    def compliance_summary(self, tenant_id: UUID | str,
                            context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Aggregiert alle 4 Checks zu Tenant-Compliance-Score."""
        ctx = context or {}
        results = {
            "consent": self.check_consent(tenant_id, ctx),
            "retention": self.check_retention(tenant_id, ctx),
            "cross_border": self.check_cross_border(tenant_id, ctx),
            "dpia": self.check_dpia(tenant_id, ctx),
        }
        statuses = [r.status for r in results.values()]
        if any(s == ComplianceStatus.FAIL for s in statuses):
            overall = ComplianceStatus.FAIL
        elif any(s == ComplianceStatus.WARN for s in statuses):
            overall = ComplianceStatus.WARN
        elif all(s == ComplianceStatus.PASS for s in statuses):
            overall = ComplianceStatus.PASS
        else:
            overall = ComplianceStatus.UNKNOWN

        return {
            "tenant_id": str(tenant_id),
            "overall_status": overall.value,
            "details": {k: v.to_dict() for k, v in results.items()},
            "summarized_at": datetime.now(timezone.utc).isoformat(),
        }
