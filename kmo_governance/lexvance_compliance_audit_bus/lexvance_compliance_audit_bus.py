# [CRUX-MK]
"""LexVance-Compliance-Audit-Bus Implementation (Welle-40 Phase-33).

8. Domain (Legal-Compliance) Bio-Pattern-Lift. Hash-Chain + Jurisdiction-aware
Retention + RLock-protected. Pattern: Lymphatic-System.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LegalObligationType(str, Enum):
    """LexVance-Legal-Domain Pflicht-Klassen."""

    CONTRACT_REVIEW = "contract_review"
    TAX_FILING = "tax_filing"
    PATENT_FILING = "patent_filing"
    GDPR_AUDIT = "gdpr_audit"
    LITIGATION = "litigation"
    REGULATORY_REPORT = "regulatory_report"
    DUE_DILIGENCE = "due_diligence"


class Jurisdiction(str, Enum):
    """Rechtsordnung (Retention + Compliance unterschiedlich pro)."""

    DE = "DE"
    US = "US"
    UK = "UK"
    EU = "EU"
    INTERNATIONAL = "INTERNATIONAL"


# Retention pro Jurisdiction (in Stunden, Default basierend auf 10J-GDPR)
JURISDICTION_RETENTION_H: dict[str, float] = {
    "DE": 87600.0,             # 10 Jahre HGB+AO
    "US": 61320.0,             # 7 Jahre IRS
    "UK": 52560.0,             # 6 Jahre HMRC
    "EU": 87600.0,             # 10 Jahre GDPR
    "INTERNATIONAL": 87600.0,  # safest default
}


@dataclass(frozen=True)
class LegalAuditEvent:
    """Immutable Legal-Audit-Event mit Hash-Chain.

    Pre:
      - event_id non-empty
      - mandant_id non-empty
      - obligation_type in LegalObligationType
      - jurisdiction in Jurisdiction
      - context non-empty
      - chain_hash non-empty (SHA256 hex)
    """
    event_id: str
    obligation_type: LegalObligationType
    jurisdiction: Jurisdiction
    mandant_id: str
    context: str
    chain_hash: str
    prev_hash: str
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    timestamp: float = 0.0
    audit_due_date: Optional[float] = None  # epoch when next audit due

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must be non-empty")
        if not self.mandant_id:
            raise ValueError("mandant_id must be non-empty")
        if not self.context:
            raise ValueError("context must be non-empty")
        if not self.chain_hash:
            raise ValueError("chain_hash must be non-empty (SHA256)")
        if not isinstance(self.obligation_type, LegalObligationType):
            raise TypeError("obligation_type must be LegalObligationType")
        if not isinstance(self.jurisdiction, Jurisdiction):
            raise TypeError("jurisdiction must be Jurisdiction")


class LexVanceComplianceAuditBus:
    """Legal-Compliance-Audit-Bus mit Hash-Chain + Jurisdiction-aware Retention.

    Pre:
      - max_events >= 1
      - default_jurisdiction in Jurisdiction
    """

    def __init__(
        self,
        max_events: int = 10000,
        default_jurisdiction: Jurisdiction = Jurisdiction.DE,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        if not isinstance(default_jurisdiction, Jurisdiction):
            raise TypeError("default_jurisdiction must be Jurisdiction")
        self._max_events = max_events
        self._default_jurisdiction = default_jurisdiction
        self._lock = threading.RLock()
        # event-store: list (chronological)
        self._events: list[LegalAuditEvent] = []
        self._last_chain_hash: dict[str, str] = {}  # per-mandant chain

    def publish(
        self,
        obligation_type: LegalObligationType,
        mandant_id: str,
        context: str,
        jurisdiction: Optional[Jurisdiction] = None,
        metadata: tuple = (),
        audit_due_in_h: Optional[float] = None,
    ) -> LegalAuditEvent:
        """Publish neues Legal-Audit-Event mit Hash-Chain.

        Pre:
          - obligation_type ist LegalObligationType
          - mandant_id non-empty, context non-empty

        Post:
          - chain_hash = SHA256(prev_hash + obligation + context + ts)
          - prev_hash = vorheriges chain_hash fuer denselben mandant_id
          - retention basiert auf jurisdiction
        """
        if not isinstance(obligation_type, LegalObligationType):
            raise TypeError("obligation_type must be LegalObligationType")
        if not mandant_id:
            raise ValueError("mandant_id must be non-empty")
        if not context:
            raise ValueError("context must be non-empty")
        jur = jurisdiction or self._default_jurisdiction
        ts = time.time()
        with self._lock:
            prev_hash = self._last_chain_hash.get(mandant_id, "")
            chain_input = f"{prev_hash}|{obligation_type.value}|{context}|{ts}".encode("utf-8")
            chain_hash = hashlib.sha256(chain_input).hexdigest()
            event = LegalAuditEvent(
                event_id=str(uuid.uuid4()),
                obligation_type=obligation_type,
                jurisdiction=jur,
                mandant_id=mandant_id,
                context=context,
                chain_hash=chain_hash,
                prev_hash=prev_hash,
                metadata=tuple(metadata),
                timestamp=ts,
                audit_due_date=ts + (audit_due_in_h * 3600.0) if audit_due_in_h else None,
            )
            self._events.append(event)
            self._last_chain_hash[mandant_id] = chain_hash
            # bound by max_events (FIFO eviction)
            if len(self._events) > self._max_events:
                self._events.pop(0)
        return event

    def query(
        self,
        mandant_id: Optional[str] = None,
        obligation_type: Optional[LegalObligationType] = None,
        jurisdiction: Optional[Jurisdiction] = None,
    ) -> tuple[LegalAuditEvent, ...]:
        """Filtered events (immutable copy)."""
        with self._lock:
            events = list(self._events)
        return tuple(
            e for e in events
            if (mandant_id is None or e.mandant_id == mandant_id)
            and (obligation_type is None or e.obligation_type == obligation_type)
            and (jurisdiction is None or e.jurisdiction == jurisdiction)
        )

    def verify_chain(self, mandant_id: str) -> bool:
        """Verify Hash-Chain-Integrity fuer einen mandant_id.

        W47-P1 (V20-F1-Fix): Verify both prev_hash chaining AND SHA256-Recompute
        ueber Event-Inhalt (verhindert chain-forge by tampered context).

        Returns True if chain is intact, False if any prev_hash mismatch
        ODER chain_hash != recomputed-SHA256(prev_hash + obligation + context + ts).
        """
        with self._lock:
            mandant_events = [e for e in self._events if e.mandant_id == mandant_id]
        if not mandant_events:
            return True  # empty chain is trivially valid
        prev = ""
        for e in sorted(mandant_events, key=lambda x: x.timestamp):
            if e.prev_hash != prev:
                return False
            # W47-P1: SHA256-Recompute-Check (anti-tamper)
            chain_input = f"{prev}|{e.obligation_type.value}|{e.context}|{e.timestamp}".encode("utf-8")
            recomputed = hashlib.sha256(chain_input).hexdigest()
            if e.chain_hash != recomputed:
                return False
            prev = e.chain_hash
        return True

    def cleanup_expired(self, current_ts: Optional[float] = None) -> int:
        """Remove events past Jurisdiction-Retention-TTL. Returns count removed."""
        now = current_ts if current_ts is not None else time.time()
        removed = 0
        with self._lock:
            keep: list[LegalAuditEvent] = []
            for e in self._events:
                ttl_s = JURISDICTION_RETENTION_H[e.jurisdiction.value] * 3600.0
                if now - e.timestamp <= ttl_s:
                    keep.append(e)
                else:
                    removed += 1
            self._events = keep
        return removed

    def get_stats(self) -> dict:
        """Aggregate-Stats (total events, per-jurisdiction, per-obligation)."""
        with self._lock:
            events = list(self._events)
        per_jur: dict[str, int] = {}
        per_obl: dict[str, int] = {}
        for e in events:
            per_jur[e.jurisdiction.value] = per_jur.get(e.jurisdiction.value, 0) + 1
            per_obl[e.obligation_type.value] = per_obl.get(e.obligation_type.value, 0) + 1
        return {
            "total": len(events),
            "per_jurisdiction": per_jur,
            "per_obligation": per_obl,
            "mandanten_count": len(self._last_chain_hash),
        }


# CRUX-MK
