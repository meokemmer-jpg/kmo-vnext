# DPIA-per-Tenant Lifecycle [CRUX-MK]
"""
DPIA (Data Protection Impact Assessment) pro Tenant.

Lifecycle:
- DRAFT -> ACTIVE (Approval)
- ACTIVE -> EXPIRED (nach max_age_days)
- ACTIVE -> SUPERSEDED (durch neue DPIA-Version)

DSGVO Art 35: DPIA-Pflicht wenn high-risk processing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class DPIAStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


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
class DPIAPerTenant:
    """DPIA pro Tenant.

    Pre-Conditions:
        - tenant_id ist UUID/str
        - risk_score in [0.0, 1.0]
        - mitigations is list
    """
    tenant_id: UUID | str
    processing_activity: str
    risk_score: float
    risk_level: RiskLevel
    mitigations: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    status: DPIAStatus = DPIAStatus.DRAFT
    valid_from: datetime = field(default_factory=_now_utc)
    valid_until: datetime | None = None  # Default: +365 days bei activate
    superseded_by: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = DPIAStatus(self.status)
        if isinstance(self.risk_level, str):
            self.risk_level = RiskLevel(self.risk_level)
        if not (0.0 <= self.risk_score <= 1.0):
            raise ValueError("risk_score muss in [0.0, 1.0]")
        if not self.processing_activity.strip():
            raise ValueError("processing_activity nicht leer")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = str(self.id)
        d["tenant_id"] = str(self.tenant_id)
        d["status"] = self.status.value
        d["risk_level"] = self.risk_level.value
        d["valid_from"] = self.valid_from.isoformat()
        d["valid_until"] = self.valid_until.isoformat() if self.valid_until else None
        d["superseded_by"] = str(self.superseded_by) if self.superseded_by else None
        return d

    def compute_hash(self) -> str:
        return canonical_record_hash(self.to_dict())


# === Lifecycle-Funktionen ===

DEFAULT_DPIA_VALIDITY_DAYS = 365


def activate_dpia(dpia: DPIAPerTenant,
                  validity_days: int = DEFAULT_DPIA_VALIDITY_DAYS) -> DPIAPerTenant:
    """DRAFT -> ACTIVE."""
    if dpia.status != DPIAStatus.DRAFT:
        raise ValueError(
            f"activate_dpia nur aus DRAFT, war {dpia.status.value}"
        )
    dpia.status = DPIAStatus.ACTIVE
    dpia.valid_from = _now_utc()
    dpia.valid_until = dpia.valid_from + timedelta(days=validity_days)
    return dpia


def supersede_dpia(old: DPIAPerTenant, new: DPIAPerTenant) -> tuple[DPIAPerTenant, DPIAPerTenant]:
    """Markiert alte DPIA als SUPERSEDED, neue als ACTIVE."""
    if old.status not in (DPIAStatus.ACTIVE, DPIAStatus.EXPIRED):
        raise ValueError(
            f"supersede nur aus ACTIVE/EXPIRED, war {old.status.value}"
        )
    if old.tenant_id != new.tenant_id:
        raise ValueError("supersede nur fuer gleiche tenant_id")
    old.status = DPIAStatus.SUPERSEDED
    old.superseded_by = new.id
    if new.status == DPIAStatus.DRAFT:
        activate_dpia(new)
    return old, new


def expire_if_overdue(dpia: DPIAPerTenant, now: datetime | None = None) -> DPIAPerTenant:
    """Setzt EXPIRED wenn valid_until < now."""
    now = now or _now_utc()
    if dpia.status == DPIAStatus.ACTIVE and dpia.valid_until and dpia.valid_until < now:
        dpia.status = DPIAStatus.EXPIRED
    return dpia


def is_active(dpia: DPIAPerTenant, now: datetime | None = None) -> bool:
    """True wenn DPIA gerade gueltig."""
    now = now or _now_utc()
    return (
        dpia.status == DPIAStatus.ACTIVE
        and dpia.valid_from <= now
        and (dpia.valid_until is None or dpia.valid_until > now)
    )


def derive_risk_level(risk_score: float) -> RiskLevel:
    """Mappt risk_score [0,1] auf RiskLevel."""
    if risk_score >= 0.8:
        return RiskLevel.VERY_HIGH
    if risk_score >= 0.6:
        return RiskLevel.HIGH
    if risk_score >= 0.3:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
