# Data-Sharing-Policy (PolicyDecisionPoint) [CRUX-MK]
"""
PolicyDecisionPoint fuer Cross-Tenant-Data-Sharing.

Anti-Pattern (verboten):
- Cross-Tenant-Queries ohne Audit
- Tenant-Hardcoding
- Implicit-Sharing (ohne explicit policy)

Default: DENY. Sharing nur bei explicit policy match.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ALLOW_WITH_ANONYMIZATION = "ALLOW_WITH_ANONYMIZATION"


class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    PII = "PII"
    PHI = "PHI"


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
    return hashlib.sha256(
        json.dumps(clean, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, default=_json_default).encode("utf-8")
    ).hexdigest()


@dataclass
class SharingPolicy:
    """Explicit policy fuer Cross-Tenant-Data-Sharing.

    Beispiel: "Tenant A darf aggregierte Booking-Stats von Tenant B sehen,
    aber nur PUBLIC- oder anonymisierte INTERNAL-Daten."
    """
    source_tenant_id: UUID | str
    target_tenant_id: UUID | str
    allowed_data_sensitivities: set[DataSensitivity]
    require_anonymization: bool = True
    policy_id: UUID = field(default_factory=uuid4)
    valid_from: datetime = field(default_factory=_now_utc)
    valid_until: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_data_sensitivities, set):
            self.allowed_data_sensitivities = set(self.allowed_data_sensitivities)
        # Normalisiere String -> Enum
        normalized = set()
        for s in self.allowed_data_sensitivities:
            if isinstance(s, str):
                s = DataSensitivity(s)
            normalized.add(s)
        self.allowed_data_sensitivities = normalized

    def covers(self, source: UUID | str, target: UUID | str,
               sensitivity: DataSensitivity) -> bool:
        return (
            str(self.source_tenant_id) == str(source)
            and str(self.target_tenant_id) == str(target)
            and sensitivity in self.allowed_data_sensitivities
        )


@dataclass
class SharingRequest:
    """Request fuer Cross-Tenant-Data-Sharing."""
    source_tenant_id: UUID | str
    target_tenant_id: UUID | str
    sensitivity: DataSensitivity
    record_count: int
    purpose: str
    request_id: UUID = field(default_factory=uuid4)
    requested_at: datetime = field(default_factory=_now_utc)

    def __post_init__(self) -> None:
        if isinstance(self.sensitivity, str):
            self.sensitivity = DataSensitivity(self.sensitivity)
        if self.record_count < 0:
            raise ValueError("record_count >= 0")
        if not self.purpose.strip():
            raise ValueError("purpose nicht leer")


class PolicyDecisionPoint:
    """Entscheidet ob Cross-Tenant-Sharing erlaubt ist (Default DENY).

    Pre-Conditions:
        - policies sind list[SharingPolicy]
    Post-Conditions:
        - decide() liefert PolicyDecision + reasons
    """

    def __init__(self, policies: list[SharingPolicy] | None = None,
                 anonymization_threshold_k: int = 5) -> None:
        self.policies = policies or []
        self.k_threshold = anonymization_threshold_k

    def add_policy(self, policy: SharingPolicy) -> None:
        self.policies.append(policy)

    def decide(self, request: SharingRequest) -> dict[str, Any]:
        """Entscheidet ueber Sharing-Request.

        Returns:
            {decision: ALLOW|DENY|ALLOW_WITH_ANONYMIZATION,
             reasons: [...], request_id: str}
        """
        reasons: list[str] = []
        # Same-Tenant-Sharing immer erlaubt
        if str(request.source_tenant_id) == str(request.target_tenant_id):
            return {
                "decision": PolicyDecision.ALLOW.value,
                "reasons": ["Same-Tenant-Access (no cross-tenant)"],
                "request_id": str(request.request_id),
            }

        # Suche matching policy
        matching = [
            p for p in self.policies
            if p.covers(request.source_tenant_id, request.target_tenant_id,
                        request.sensitivity)
        ]
        if not matching:
            reasons.append(
                f"DENY: Keine Policy fuer source={request.source_tenant_id} -> "
                f"target={request.target_tenant_id} (sensitivity={request.sensitivity.value})"
            )
            return {
                "decision": PolicyDecision.DENY.value,
                "reasons": reasons,
                "request_id": str(request.request_id),
            }

        policy = matching[0]
        # Nicht-PUBLIC Daten brauchen Anonymisierung wenn require_anonymization
        if (
            policy.require_anonymization
            and request.sensitivity != DataSensitivity.PUBLIC
        ):
            # k-Anonymity-Pflicht (siehe anonymization_layer)
            if request.record_count < self.k_threshold:
                reasons.append(
                    f"DENY: record_count {request.record_count} < k={self.k_threshold} "
                    f"(k-Anonymity-Verletzung)"
                )
                return {
                    "decision": PolicyDecision.DENY.value,
                    "reasons": reasons,
                    "request_id": str(request.request_id),
                }
            reasons.append(
                f"ALLOW_WITH_ANONYMIZATION: Policy match + k>={self.k_threshold}"
            )
            return {
                "decision": PolicyDecision.ALLOW_WITH_ANONYMIZATION.value,
                "reasons": reasons,
                "request_id": str(request.request_id),
            }

        reasons.append("ALLOW: Policy match (no anonymization needed)")
        return {
            "decision": PolicyDecision.ALLOW.value,
            "reasons": reasons,
            "request_id": str(request.request_id),
        }
