# Approval-Request-Model [CRUX-MK]
"""
ApprovalRequest fuer Tenant-spezifische Operationen.

Beispiel-Operationen:
- Tenant-Activation
- Plan-Tier-Upgrade
- Cross-Tenant-Data-Sharing
- Adapter-Switch (Apaleo->Mews)

Pre-Action-Hook (K13 PocketOS-Lehre): JEDER Request bekommt env_tag/blast_radius/reversibility.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"


class OperationCategory(str, Enum):
    """Kategorie der Operation (steuert Default-Policy)."""
    TENANT_ACTIVATION = "TENANT_ACTIVATION"
    PLAN_UPGRADE = "PLAN_UPGRADE"
    CROSS_TENANT_DATA_SHARING = "CROSS_TENANT_DATA_SHARING"
    ADAPTER_SWITCH = "ADAPTER_SWITCH"
    DATA_DELETION = "DATA_DELETION"
    BULK_OPERATION = "BULK_OPERATION"


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
class ApprovalRequest:
    """Approval-Request fuer Multi-Tenant-Operation.

    Pre-Conditions:
        - tenant_id ist UUID oder str-UUID
        - operation_category in OperationCategory
        - blast_radius >= 0
    """
    tenant_id: UUID | str
    operation_category: OperationCategory
    operation_description: str
    requested_by: str
    env_tag: str  # dev/staging/prod
    blast_radius: int = 1
    reversibility: str = "state-only"  # state-only/side-effect/non-reversible
    requires_martin_phronesis: bool = False
    id: UUID = field(default_factory=uuid4)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = field(default_factory=_now_utc)
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.operation_category, str):
            self.operation_category = OperationCategory(self.operation_category)
        if isinstance(self.status, str):
            self.status = ApprovalStatus(self.status)
        if isinstance(self.tenant_id, str):
            try:
                self.tenant_id = UUID(self.tenant_id)
            except ValueError:
                pass  # Allow string-IDs in tests
        if not self.operation_description.strip():
            raise ValueError("operation_description darf nicht leer sein")
        if self.env_tag not in {"dev", "staging", "prod"}:
            raise ValueError(f"env_tag '{self.env_tag}' ungueltig")
        if self.blast_radius < 0:
            raise ValueError("blast_radius muss >= 0")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = str(self.id)
        d["tenant_id"] = str(self.tenant_id)
        d["operation_category"] = self.operation_category.value
        d["status"] = self.status.value
        d["requested_at"] = self.requested_at.isoformat()
        d["decided_at"] = self.decided_at.isoformat() if self.decided_at else None
        return d

    def compute_hash(self) -> str:
        return canonical_record_hash(self.to_dict())
