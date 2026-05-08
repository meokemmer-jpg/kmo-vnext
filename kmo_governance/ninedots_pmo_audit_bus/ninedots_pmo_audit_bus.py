# [CRUX-MK]
"""9dots-PMO-Audit-Bus (Welle-32 Phase-25 KMO-vNext Bio-Pattern-Lift 6/6).

Lymphatic-System-Pattern auf 9dots-PMO-Compliance-Audit-Trail:
peripher gesammelte PMOAuditEvents zentral aggregiert mit Compliance-Tag-Filterung
+ COSMOS/SAE-Governance/MYZ-Layer Retention-Policy.

Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
2. Lift:        kmo_governance.kpm_audit_event_bus (Welle-26 Phase-19, KPM-Trading).
3. Lift:        kmo_governance.cape_familien_audit_bus (Welle-30 Phase-23, Cape-Familien).
4./5. Lifts:    weitere KMO-Lifts (Sub-Layer Governance).
6. Lift (HIER): 9dots-PMO-Compliance-Audit-Trail (agentic Software Platform SAE v8).

9dots-PMO-Domain-Lift:
  AuditEvent              -> PMOAuditEvent
  AuditEventLevel         -> ComplianceTag (Multi-Tag-frozenset)
  source                  -> agent_class + slot_id + governance_tier
  payload                 -> (decision_type / context / metadata)

Pre-Conditions: agent_class non-empty, slot_id non-empty, governance_tier integer,
                decision_type valid PMODecisionType, context non-empty.
Post-Conditions: event_id ist unique uuid4-string; thread-safe (RLock);
                 retention_window_h >= 4380h (6 Monate) Default fuer SAE-Audit-Trail.

Q_0-PFLICHT: KEINE Real-9dots-Production-Daten in Tests
             (alle Test-Daten dummy: "test_agent_x", "test_slot_y", "test_tier_z")
             -- Subagent-Datenschutz-Invariante.

Belegt 6-Domain-Pattern-Universalitaet: gleicher Architekturkern (Lymphatic-System),
6 unterschiedliche Vokabular-Schichten:
Hotel-Operationen, Trading-Strategien, Familien-Decisions, [4./5. Lift], 9dots-PMO-Compliance.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PMODecisionType(str, Enum):
    """9dots-PMO-Decision-Typen entsprechend SAE v8 Governance-Domain.

    SLOT_ALLOCATION         : Slot-Belegung (200-Slot-Architektur)
    AGENT_PROMOTION         : Trinity-Slot-Promotion (Challenger -> Active)
    AGENT_RELEGATION        : Trinity-Slot-Relegation (Active -> Challenger/Out)
    TRINITY_VOTE            : Trinity-Voting-Outcome (3 Varianten Conservative/Aggressive/Contrarian)
    GOVERNANCE_TIER_CHANGE  : q-Norm Governance-Tier-Aenderung [-2, +2]
    HAMILTON_PIVOT          : Hamilton-Optimization-Pivot (H = u + lambda*f)
    BUDGET_ADJUSTMENT       : Token-Budget / OPEX-Allocation-Aenderung
    """

    SLOT_ALLOCATION = "slot_allocation"
    AGENT_PROMOTION = "agent_promotion"
    AGENT_RELEGATION = "agent_relegation"
    TRINITY_VOTE = "trinity_vote"
    GOVERNANCE_TIER_CHANGE = "governance_tier_change"
    HAMILTON_PIVOT = "hamilton_pivot"
    BUDGET_ADJUSTMENT = "budget_adjustment"


class ComplianceTag(str, Enum):
    """Regulatorische / interne Compliance-Tags pro PMO-Decision-Event.

    COSMOS              : COSMOS-Layer-Compliance (Compliance/Oversight/Safeguard/Monitoring/Sovereignty)
    SAE_GOVERNANCE      : SAE v8 Governance-Tier-Invarianten (q-Norm, T_max, F_cum)
    MYZ_LAYER           : Myzel-Layer-Event-Bus-Konsistenz (MYZ-30/MYZ-32)
    CRUX_BINDING        : CRUX-Verfassungs-Bindung (rho * L * T_life)
    K0_RELEVANT         : K_0-relevante PMO-Decision (Kapitalerhaltung)
    Q0_RELEVANT         : Q_0-relevante PMO-Decision (Qualitaetsinvarianz)
    AUDIT_RTS25         : MiFID/SAE-Audit-Pflicht (RTS-25 analog)
    """

    COSMOS = "cosmos"
    SAE_GOVERNANCE = "sae_governance"
    MYZ_LAYER = "myz_layer"
    CRUX_BINDING = "crux_binding"
    K0_RELEVANT = "k0_relevant"
    Q0_RELEVANT = "q0_relevant"
    AUDIT_RTS25 = "audit_rts25"


@dataclass(frozen=True)
class PMOAuditEvent:
    """Immutable 9dots-PMO-Decision-Audit-Event.

    Pre: agent_class non-empty, slot_id non-empty,
         governance_tier integer, decision_type valid PMODecisionType,
         context non-empty,
         compliance_tags ist frozenset[ComplianceTag],
         metadata ist tuple-of-tuples (key, value).
    Post: event_id ist unique uuid4-string.
    """

    event_id: str
    decision_type: PMODecisionType
    agent_class: str
    slot_id: str
    governance_tier: int
    context: str
    timestamp: float
    compliance_tags: frozenset = field(default_factory=frozenset)
    metadata: tuple = ()  # tuple of (key, value) pairs (frozen-dict equivalent)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id required")
        if not isinstance(self.decision_type, PMODecisionType):
            raise TypeError("decision_type must be PMODecisionType")
        if not self.agent_class:
            raise ValueError("agent_class required (non-empty)")
        if not self.slot_id:
            raise ValueError("slot_id required (non-empty)")
        if not isinstance(self.governance_tier, int) or isinstance(
            self.governance_tier, bool
        ):
            raise TypeError("governance_tier must be int")
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


class NineDotsPMOAuditBus:
    """Zentraler 9dots-PMO-Decision-Audit-Event-Bus mit COSMOS-Retention.

    Pre: retention_window_h > 0, compliance_required ist set[ComplianceTag] oder None.
    Post: thread-safe via RLock; events aelter als retention_window_h via cleanup_old() entfernbar;
          publish ist idempotent durch uuid4 event_id;
          validate_event prueft compliance_required als Subset von event.compliance_tags.

    SAE-Audit-Default: retention_window_h=4380.0 (6 Monate fuer PMO-Compliance-Trail).
    Mittel zwischen Hotel (1h Operational) / KPM (168h MiFID) / Cape-Familien (8760h GDPR):
    SAE-Governance braucht 6-Monats-Window fuer Trinity-Voting-Backtrace + Hamilton-Pivot-Audit.
    """

    DEFAULT_RETENTION_HOURS = 4380.0  # 6 Monate SAE-Audit-Default
    DEFAULT_MAX_SIZE = 1_000  # Cap fuer PMO-Volumen (zwischen Hotel/Familien und KPM)

    def __init__(
        self,
        retention_window_h: float = 4380.0,
        compliance_required: Optional[set] = None,
    ) -> None:
        """Constructor.

        Pre-Conditions:
            retention_window_h > 0.
            compliance_required ist set[ComplianceTag] oder None.

        Post-Conditions:
            self._events ist deque(maxlen=DEFAULT_MAX_SIZE).
            self._stats initialisiert mit by_decision_type + by_compliance_tag +
            by_agent_class + by_governance_tier (alle 0 / dynamisch).
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
            "by_decision_type": {t.value: 0 for t in PMODecisionType},
            "by_compliance_tag": {t.value: 0 for t in ComplianceTag},
            "by_agent_class": {},  # dynamisch wachsend
            "by_governance_tier": {},  # dynamisch wachsend
        }
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ publish
    def publish(
        self,
        decision_type: PMODecisionType,
        agent_class: str,
        slot_id: str,
        governance_tier: int,
        context: str,
        compliance_tags: frozenset = frozenset(),
        metadata: tuple = (),
    ) -> PMOAuditEvent:
        """Publish neues PMO-Decision-Audit-Event. Auto-generated event_id (uuid4) + timestamp.

        Pre: decision_type ist PMODecisionType,
             agent_class non-empty, slot_id non-empty,
             governance_tier ist int, context non-empty.
        Post: Event wird in Bus aufgenommen, Stats inkrementiert,
              gibt unveraenderliches PMOAuditEvent zurueck.
        """
        if not isinstance(decision_type, PMODecisionType):
            raise TypeError("decision_type must be PMODecisionType")
        if not agent_class:
            raise ValueError("agent_class required (non-empty)")
        if not slot_id:
            raise ValueError("slot_id required (non-empty)")
        if not isinstance(governance_tier, int) or isinstance(governance_tier, bool):
            raise TypeError("governance_tier must be int")
        if not context:
            raise ValueError("context required (non-empty)")

        # Normalize compliance_tags + metadata
        normalized_tags = frozenset(compliance_tags) if compliance_tags else frozenset()
        normalized_metadata = tuple(metadata) if metadata else ()

        event = PMOAuditEvent(
            event_id=str(uuid.uuid4()),
            decision_type=decision_type,
            agent_class=agent_class,
            slot_id=slot_id,
            governance_tier=governance_tier,
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
            self._stats["by_agent_class"][agent_class] = (
                self._stats["by_agent_class"].get(agent_class, 0) + 1
            )
            self._stats["by_governance_tier"][governance_tier] = (
                self._stats["by_governance_tier"].get(governance_tier, 0) + 1
            )

        return event

    # -------------------------------------------------------------------- query
    def query(
        self,
        decision_type: Optional[PMODecisionType] = None,
        agent_class: Optional[str] = None,
        slot_id: Optional[str] = None,
        governance_tier: Optional[int] = None,
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
            decision_type, PMODecisionType
        ):
            raise TypeError("decision_type must be PMODecisionType")
        if compliance_tag is not None and not isinstance(compliance_tag, ComplianceTag):
            raise TypeError("compliance_tag must be ComplianceTag")
        if governance_tier is not None and (
            not isinstance(governance_tier, int)
            or isinstance(governance_tier, bool)
        ):
            raise TypeError("governance_tier must be int")

        with self._lock:
            results = []
            for ev in self._events:
                if decision_type is not None and ev.decision_type != decision_type:
                    continue
                if agent_class is not None and ev.agent_class != agent_class:
                    continue
                if slot_id is not None and ev.slot_id != slot_id:
                    continue
                if (
                    governance_tier is not None
                    and ev.governance_tier != governance_tier
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
    def validate_event(self, event: PMOAuditEvent) -> tuple:
        """Prueft Event gegen compliance_required-Set.

        Pre: event ist PMOAuditEvent.
        Post: gibt (is_valid: bool, missing_tags: list[str]) zurueck.
              is_valid=True wenn compliance_required leer ODER vollstaendig
              in event.compliance_tags.
        """
        if not isinstance(event, PMOAuditEvent):
            raise TypeError("event must be PMOAuditEvent")

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
              by_compliance_tag, by_agent_class, by_governance_tier, current_count,
              retention_window_h zurueck. Aenderungen am Rueckgabe-dict
              beeinflussen nicht den Bus.
        """
        with self._lock:
            return {
                "total_published": self._stats["total_published"],
                "total_purged": self._stats["total_purged"],
                "by_decision_type": dict(self._stats["by_decision_type"]),
                "by_compliance_tag": dict(self._stats["by_compliance_tag"]),
                "by_agent_class": dict(self._stats["by_agent_class"]),
                "by_governance_tier": dict(self._stats["by_governance_tier"]),
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
