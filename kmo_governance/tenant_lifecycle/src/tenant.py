# Tenant-Model [CRUX-MK]
"""
Tenant-Datentyp (dataclass-Fallback, kein Pydantic).

Ein Tenant entspricht einem Drittpartei-Hotelier-Account (Multi-Tenant).
Lifecycle: PROVISIONED -> ACTIVE -> SUSPENDED? -> DECOMMISSIONED -> ARCHIVED.

K12 Distillation-Resistenz: canonical_record_hash auf Tenant-State.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class TenantStatus(str, Enum):
    """Tenant-Lifecycle-Status."""
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"
    ARCHIVED = "ARCHIVED"


class PlanTier(str, Enum):
    """Subscription-Plan-Tier."""
    STARTER = "STARTER"      # 1 Hotel, basic features
    PROFESSIONAL = "PROFESSIONAL"  # 3 Hotels, advanced
    ENTERPRISE = "ENTERPRISE"      # unbegrenzt, white-label


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_ts(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Type {type(obj)} not JSON-serializable")


def canonical_record_hash(record_dict: dict[str, Any]) -> str:
    """SHA256-Hash eines Tenant-Records (deterministisch)."""
    if not isinstance(record_dict, dict):
        raise TypeError("record_dict muss dict sein")
    clean = {k: v for k, v in record_dict.items() if k not in ("hash_chain", "record_hash")}
    canonical_json = json.dumps(
        clean, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=_json_default,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass
class Tenant:
    """Tenant-Record (Drittpartei-Hotelier).

    Pre-Conditions:
        - name nicht leer
        - plan_tier in PlanTier
        - status in TenantStatus
    Post-Conditions:
        - id ist UUID4
        - created_at <= activated_at (wenn beide gesetzt)
    """
    name: str
    plan_tier: PlanTier
    id: UUID = field(default_factory=uuid4)
    status: TenantStatus = TenantStatus.PROVISIONED
    created_at: datetime = field(default_factory=_now_utc)
    activated_at: datetime | None = None
    suspended_at: datetime | None = None
    decommissioned_at: datetime | None = None
    archived_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tenant.name muss nicht-leerer String sein")
        if isinstance(self.plan_tier, str):
            self.plan_tier = PlanTier(self.plan_tier)
        if isinstance(self.status, str):
            self.status = TenantStatus(self.status)
        self.created_at = _normalize_ts(self.created_at) or _now_utc()
        self.activated_at = _normalize_ts(self.activated_at)
        self.suspended_at = _normalize_ts(self.suspended_at)
        self.decommissioned_at = _normalize_ts(self.decommissioned_at)
        self.archived_at = _normalize_ts(self.archived_at)
        if self.activated_at and self.activated_at < self.created_at:
            raise ValueError("activated_at darf nicht vor created_at liegen")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = str(self.id)
        d["plan_tier"] = self.plan_tier.value
        d["status"] = self.status.value
        for ts_field in ("created_at", "activated_at", "suspended_at",
                         "decommissioned_at", "archived_at"):
            ts = getattr(self, ts_field)
            d[ts_field] = ts.isoformat() if ts else None
        return d

    def compute_hash(self) -> str:
        return canonical_record_hash(self.to_dict())
