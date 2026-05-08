# [CRUX-MK]
"""Cape-Familien-Audit-Bus (Welle-30 Phase-23 KMO-vNext Wild-Code-Blindtest 1/3).

Lymphatic-System-Pattern auf Familien-Decision-Audit-Trail: peripher gesammelte
FamilienAuditEvents zentral aggregiert mit Compliance-Tag-Filterung +
GDPR/US-Relocation Retention-Policy.

Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
2. Lift:        kmo_governance.kpm_audit_event_bus (Welle-26 Phase-19, KPM-Trading).
3. Lift (HIER): Cape-Coral-Vault Familien-Decision-Verwaltung (EXTERNE Domain).

Cape-Coral-Domain-Lift:
  AuditEvent              -> FamilienAuditEvent
  AuditEventLevel         -> ComplianceTag
  source                  -> family_member_role
  payload                 -> (decision_type / context / metadata)

Pre-Conditions: family_member_role non-empty, decision_type valid FamilienDecisionType,
                context non-empty.
Post-Conditions: event_id unique (uuid4), thread-safe (RLock),
                 retention_window_h >= 8760h (1 Jahr) Default fuer GDPR-Familien-Daten.

Q_0-PFLICHT: KEINE Real-Familien-Daten verarbeiten -- Subagent-Datenschutz-Invariante.
Tests verwenden ausschliesslich dummy-Daten ("test_member_x", "test_decision_y").
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FamilienDecisionType(str, Enum):
    """Familien-Decision-Typen entsprechend Cape-Coral-Vault-Domain.

    DECISION_FAMILIAL    : Beziehungs-/Erziehungs-Entscheidung (Brueder, Schule)
    DECISION_VISA        : E-2-Visa / Aufenthalts-Entscheidung
    DECISION_TAX         : Steuer-Entscheidung (Wegzugsteuer, US-Tax)
    DECISION_MEDICAL     : Gesundheits-Entscheidung (Q_0-naehe)
    DECISION_FINANCIAL   : Finanz-Entscheidung (Vermoegen, K_0-naehe)
    DECISION_PROCEDURAL  : Prozessuale Entscheidung (Ablauf, Routine)
    """

    DECISION_FAMILIAL = "decision_familial"
    DECISION_VISA = "decision_visa"
    DECISION_TAX = "decision_tax"
    DECISION_MEDICAL = "decision_medical"
    DECISION_FINANCIAL = "decision_financial"
    DECISION_PROCEDURAL = "decision_procedural"


class ComplianceTag(str, Enum):
    """Regulatorische Compliance-Tags pro Familien-Decision-Event.

    PERSONAL_DATA      : Personenbezogene Daten betroffen
    FAMILIAL           : Familien-internes (Brueder, Eltern, Kinder, Partner)
    LEGAL              : Rechtliche Auslegung relevant (Anwalt-Pflicht ggf.)
    FINANCIAL_K0       : K_0-relevante Vermoegens-Decision
    MEDICAL_PRIVACY    : Gesundheits-Datenschutz-Pflicht
    GDPR               : EU-Datenschutz-Grundverordnung (Pre-Wegzug)
    US_RELOCATION      : US-Relocation-spezifische Regulatorik (E-2, IRS)
    """

    PERSONAL_DATA = "personal_data"
    FAMILIAL = "familial"
    LEGAL = "legal"
    FINANCIAL_K0 = "financial_k0"
    MEDICAL_PRIVACY = "medical_privacy"
    GDPR = "gdpr"
    US_RELOCATION = "us_relocation"


@dataclass(frozen=True)
class FamilienAuditEvent:
    """Immutable Familien-Decision-Audit-Event.

    Pre: family_member_role non-empty, decision_type valid FamilienDecisionType,
         context non-empty,
         compliance_tags ist frozenset[ComplianceTag],
         metadata ist tuple-of-tuples (key, value).
    Post: event_id ist unique uuid4-string.
    """

    event_id: str
    decision_type: FamilienDecisionType
    family_member_role: str
    context: str
    timestamp: float
    compliance_tags: frozenset = field(default_factory=frozenset)
    metadata: tuple = ()  # tuple of (key, value) pairs (frozen-dict equivalent)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id required")
        if not isinstance(self.decision_type, FamilienDecisionType):
            raise TypeError("decision_type must be FamilienDecisionType")
        if not self.family_member_role:
            raise ValueError("family_member_role required (non-empty)")
        if not self.context:
            raise ValueError("context required (non-empty)")
        if not isinstance(self.compliance_tags, frozenset):
            raise TypeError("compliance_tags must be frozenset")
        for tag in self.compliance_tags:
            if not isinstance(tag, ComplianceTag):
                raise TypeError("each compliance_tag must be ComplianceTag")
        if not isinstance(self.metadata, tuple):
            raise TypeError("metadata must be tuple-of-tuples")
        for entry in self.metadata:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("metadata entries must be 2-tuples (key, value)")

    def get_metadata_dict(self) -> dict:
        """Materialisiert Metadata-Tuple zu dict (read-only-Anschauung)."""
        return dict(self.metadata)


class CapeFamilienAuditBus:
    """Zentraler Familien-Decision-Audit-Event-Bus mit GDPR-Retention.

    Pre: retention_window_h > 0, compliance_required ist set[ComplianceTag] oder None.
    Post: thread-safe via RLock; events aelter als retention_window_h via cleanup_old() entfernbar;
          publish ist idempotent durch uuid4 event_id;
          validate_event prueft compliance_required als Subset von event.compliance_tags.

    GDPR-Default: retention_window_h=8760.0 (1 Jahr fuer Familien-Vault-Daten).
    Signifikant laenger als Hotel (168h) / KPM (168h) wegen langfristiger
    Familien-Decision-Nachvollziehbarkeit (z.B. Wegzugsteuer-Frist 7-Jahre-Dokumentation).
    """

    DEFAULT_RETENTION_HOURS = 8760.0  # 1 Jahr GDPR-Familien-Default
    DEFAULT_MAX_SIZE = 1_000  # Tighter cap fuer Familien (kleineres Volumen vs Trading)

    def __init__(
        self,
        retention_window_h: float = 8760.0,
        compliance_required: Optional[set] = None,
    ) -> None:
        """Constructor.

        Pre-Conditions:
            retention_window_h > 0.
            compliance_required ist set[ComplianceTag] oder None.

        Post-Conditions:
            self._events ist deque(maxlen=DEFAULT_MAX_SIZE).
            self._stats initialisiert mit by_decision_type + by_compliance_tag (alle 0).
            self._lock ist RLock (thread-safe).
        """
        if retention_window_h <= 0:
            raise ValueError("retention_window_h must be > 0")
        if compliance_required is not None:
            for tag in compliance_required:
                if not isinstance(tag, ComplianceTag):
                    raise TypeError(
                        "compliance_required entries must be ComplianceTag"
                    )
        self.retention_window_h = retention_window_h
        self.compliance_required: frozenset = (
            frozenset(compliance_required) if compliance_required else frozenset()
        )
        self._events: deque = deque(maxlen=self.DEFAULT_MAX_SIZE)
        self._stats: dict = {
            "total_published": 0,
            "total_purged": 0,
            "by_decision_type": {t.value: 0 for t in FamilienDecisionType},
            "by_compliance_tag": {t.value: 0 for t in ComplianceTag},
            "by_family_member_role": {},  # dynamisch wachsend
        }
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ publish
    def publish(
        self,
        decision_type: FamilienDecisionType,
        family_member_role: str,
        context: str,
        compliance_tags: frozenset = frozenset(),
        metadata: tuple = (),
    ) -> FamilienAuditEvent:
        """Publish neues Familien-Decision-Audit-Event. Auto-generated event_id (uuid4) + timestamp.

        Pre: decision_type ist FamilienDecisionType,
             family_member_role non-empty, context non-empty.
        Post: Event wird in Bus aufgenommen, Stats inkrementiert,
              gibt unveraenderliches FamilienAuditEvent zurueck.
        """
        if not isinstance(decision_type, FamilienDecisionType):
            raise TypeError("decision_type must be FamilienDecisionType")
        if not family_member_role:
            raise ValueError("family_member_role required (non-empty)")
        if not context:
            raise ValueError("context required (non-empty)")

        # Normalize compliance_tags + metadata
        normalized_tags = frozenset(compliance_tags) if compliance_tags else frozenset()
        normalized_metadata = tuple(metadata) if metadata else ()

        event = FamilienAuditEvent(
            event_id=str(uuid.uuid4()),
            decision_type=decision_type,
            family_member_role=family_member_role,
            context=context,
            timestamp=time.time(),
            compliance_tags=normalized_tags,
            metadata=normalized_metadata,
        )

        with self._lock:
            self._events.append(event)
            self._stats["total_published"] += 1
            self._stats["by_decision_type"][decision_type.value] += 1
            for tag in normalized_tags:
                self._stats["by_compliance_tag"][tag.value] += 1
            self._stats["by_family_member_role"][family_member_role] = (
                self._stats["by_family_member_role"].get(family_member_role, 0) + 1
            )

        return event

    # -------------------------------------------------------------------- query
    def query(
        self,
        decision_type: Optional[FamilienDecisionType] = None,
        family_member_role: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        compliance_tag: Optional[ComplianceTag] = None,
    ) -> tuple:
        """Filter-Query ueber gespeicherte Events.

        Pre: alle Filter-Argumente optional; falls gesetzt, Typ-konform.
        Post: gibt unveraenderliches Tuple aller passenden Events
              (chronologisch nach Insertion-Order, snapshot zum Query-Zeitpunkt).
        """
        if decision_type is not None and not isinstance(
            decision_type, FamilienDecisionType
        ):
            raise TypeError("decision_type must be FamilienDecisionType")
        if compliance_tag is not None and not isinstance(compliance_tag, ComplianceTag):
            raise TypeError("compliance_tag must be ComplianceTag")

        with self._lock:
            results = []
            for ev in self._events:
                if decision_type is not None and ev.decision_type != decision_type:
                    continue
                if (
                    family_member_role is not None
                    and ev.family_member_role != family_member_role
                ):
                    continue
                if since is not None and ev.timestamp < since:
                    continue
                if until is not None and ev.timestamp > until:
                    continue
                if (
                    compliance_tag is not None
                    and compliance_tag not in ev.compliance_tags
                ):
                    continue
                results.append(ev)
            return tuple(results)

    # ----------------------------------------------------------------- validate
    def validate_event(self, event: FamilienAuditEvent) -> tuple:
        """Prueft Event gegen compliance_required-Set.

        Pre: event ist FamilienAuditEvent.
        Post: gibt (is_valid: bool, missing_tags: list[str]) zurueck.
              is_valid=True wenn compliance_required leer ODER vollstaendig
              in event.compliance_tags.
        """
        if not isinstance(event, FamilienAuditEvent):
            raise TypeError("event must be FamilienAuditEvent")

        if not self.compliance_required:
            return True, []

        missing = self.compliance_required - event.compliance_tags
        if not missing:
            return True, []
        return False, sorted(t.value for t in missing)

    # ---------------------------------------------------------------- get_stats
    def get_stats(self) -> dict:
        """Snapshot der laufenden Statistik (deep-copy).

        Post: gibt dict mit total_published, total_purged, by_decision_type,
              by_compliance_tag, by_family_member_role, current_count,
              retention_window_h zurueck. Aenderungen am Rueckgabe-dict
              beeinflussen nicht den Bus.
        """
        with self._lock:
            return {
                "total_published": self._stats["total_published"],
                "total_purged": self._stats["total_purged"],
                "by_decision_type": dict(self._stats["by_decision_type"]),
                "by_compliance_tag": dict(self._stats["by_compliance_tag"]),
                "by_family_member_role": dict(self._stats["by_family_member_role"]),
                "current_count": len(self._events),
                "retention_window_h": self.retention_window_h,
            }

    # ------------------------------------------------------------- cleanup_old
    def cleanup_old(self, now: Optional[float] = None) -> int:
        """Entfernt Events aelter als retention_window_h.

        Pre: now optional (Test-Hook fuer Zeit-Override); sonst time.time().
        Post: gibt Anzahl entfernter Events zurueck.
              Stats.total_purged wird inkrementiert.
        """
        current_time = now if now is not None else time.time()
        cutoff = current_time - (self.retention_window_h * 3600.0)

        with self._lock:
            initial = len(self._events)
            kept = deque(
                (ev for ev in self._events if ev.timestamp >= cutoff),
                maxlen=self.DEFAULT_MAX_SIZE,
            )
            self._events = kept
            removed = initial - len(self._events)
            self._stats["total_purged"] += removed
            return removed


# CRUX-MK
