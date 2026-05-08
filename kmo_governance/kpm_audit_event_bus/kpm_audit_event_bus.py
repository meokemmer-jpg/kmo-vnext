# [CRUX-MK]
"""KPM-Audit-Event-Bus (Welle-26 Phase-19 Bio-Pattern-Lift).

Lymphatic-System-Pattern auf Trade-Audit-Trail: peripher gesammelte
TradeAuditEvents zentral aggregiert mit Compliance-Tag-Filterung +
MiFID-RTS-25 Retention-Policy.

Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
KPM-Domain-Lift: AuditEvent -> TradeAuditEvent, AuditEventLevel -> ComplianceTag,
                  source -> strategy_id, payload -> (instrument/qty/price/metadata).

Pre-Conditions: strategy_id non-empty, event_type valid TradeEventType,
                instrument_id non-empty, quantity > 0, price > 0.
Post-Conditions: event_id unique (uuid4), thread-safe (RLock),
                 retention_window_h >= 168h fuer MiFID-RTS-25 Default.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TradeEventType(str, Enum):
    """Trade-Event-Typen entsprechend FIX-Protokoll-Subset.

    BUY            : Kauf-Order
    SELL           : Verkauf-Order
    CANCEL         : Order-Stornierung
    PARTIAL_FILL   : Teil-Ausfuehrung
    REJECT         : Order abgelehnt
    ADJUSTMENT     : Manuelle Korrektur (Audit-relevant)
    """

    BUY = "buy"
    SELL = "sell"
    CANCEL = "cancel"
    PARTIAL_FILL = "partial_fill"
    REJECT = "reject"
    ADJUSTMENT = "adjustment"


class ComplianceTag(str, Enum):
    """Regulatorische Compliance-Tags pro Trade-Event.

    KYC               : Know-Your-Customer-Pflicht-Pruefung
    AML               : Anti-Money-Laundering-Verifikation
    MIFID_BEST_EXEC   : MiFID-II Best-Execution-Nachweis
    POSITION_LIMIT    : Positions-Limit-Konformitaet (Variante-D Kelly-Frac)
    RISK_BUDGET       : Risk-Budget-Allokation eingehalten
    LATE_TRADING      : Late-Trading-Detection-Marker
    """

    KYC = "kyc"
    AML = "aml"
    MIFID_BEST_EXEC = "mifid_best_exec"
    POSITION_LIMIT = "position_limit"
    RISK_BUDGET = "risk_budget"
    LATE_TRADING = "late_trading"


@dataclass(frozen=True)
class TradeAuditEvent:
    """Immutable Trade-Audit-Event.

    Pre: strategy_id non-empty, event_type valid TradeEventType,
         instrument_id non-empty, quantity > 0, price > 0,
         compliance_tags ist frozenset[ComplianceTag],
         metadata ist tuple-of-tuples (key, value).
    Post: event_id ist unique uuid4-string.
    """

    event_id: str
    strategy_id: str
    event_type: TradeEventType
    instrument_id: str
    quantity: float
    price: float
    timestamp: float
    compliance_tags: frozenset = field(default_factory=frozenset)
    metadata: tuple = ()  # tuple of (key, value) pairs (frozen-dict equivalent)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id required")
        if not self.strategy_id:
            raise ValueError("strategy_id required")
        if not isinstance(self.event_type, TradeEventType):
            raise TypeError("event_type must be TradeEventType")
        if not self.instrument_id:
            raise ValueError("instrument_id required")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.price <= 0:
            raise ValueError("price must be > 0")
        if not isinstance(self.compliance_tags, frozenset):
            raise TypeError("compliance_tags must be frozenset")
        for tag in self.compliance_tags:
            if not isinstance(tag, ComplianceTag):
                raise TypeError("each compliance_tag must be ComplianceTag")

    def get_metadata_dict(self) -> dict:
        """Materialisiert Metadata-Tuple zu dict (read-only-Anschauung)."""
        return dict(self.metadata)


class KPMAuditEventBus:
    """Zentraler Trade-Audit-Event-Bus mit MiFID-RTS-25 Retention.

    Pre: retention_window_h > 0, compliance_required ist set[ComplianceTag] oder None.
    Post: thread-safe via RLock; events aelter als retention_window_h via cleanup_old() entfernbar;
          publish ist idempotent durch uuid4 event_id;
          validate_event prueft compliance_required als Subset von event.compliance_tags.

    MiFID-RTS-25 Default: retention_window_h=168.0 (7 Tage = 168h).
    """

    DEFAULT_RETENTION_HOURS = 168.0  # MiFID-RTS-25 Mindest-Window
    DEFAULT_MAX_SIZE = 100_000  # Hardcap gegen unbegrenztes Wachstum

    def __init__(
        self,
        retention_window_h: float = 168.0,
        compliance_required: Optional[set] = None,
        max_metadata_bytes: int = 4096,
    ) -> None:
        """Constructor with V13-Patch P-V13-4 (Metadata-Cap + Silent-Drops-Counter).

        Pre-Conditions:
            retention_window_h > 0.
            compliance_required ist set[ComplianceTag] oder None.
            max_metadata_bytes >= 1 (V13-4: Anti-Memory-Bloat via metadata size cap).

        Post-Conditions:
            self._silent_drops_count tracks Anzahl Events die durch deque-maxlen
            eviction ueberschrieben wurden. Erscheint in get_stats() als
            "silent_drops_count".
        """
        if retention_window_h <= 0:
            raise ValueError("retention_window_h must be > 0")
        if compliance_required is not None:
            for tag in compliance_required:
                if not isinstance(tag, ComplianceTag):
                    raise TypeError(
                        "compliance_required entries must be ComplianceTag"
                    )
        if max_metadata_bytes < 1:
            raise ValueError(
                f"max_metadata_bytes must be >= 1: {max_metadata_bytes}"
            )
        self.retention_window_h = retention_window_h
        self.compliance_required: frozenset = (
            frozenset(compliance_required) if compliance_required else frozenset()
        )
        self.max_metadata_bytes = int(max_metadata_bytes)
        self._events: deque = deque(maxlen=self.DEFAULT_MAX_SIZE)
        self._stats: dict = {
            "total_published": 0,
            "total_purged": 0,
            "by_event_type": {t.value: 0 for t in TradeEventType},
            "by_compliance_tag": {t.value: 0 for t in ComplianceTag},
        }
        # V13-4: silent-drops counter (deque-maxlen evictions waehrend publish)
        self._silent_drops_count: int = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ publish
    def publish(
        self,
        strategy_id: str,
        event_type: TradeEventType,
        instrument_id: str,
        quantity: float,
        price: float,
        compliance_tags: frozenset = frozenset(),
        metadata: tuple = (),
    ) -> TradeAuditEvent:
        """Publish neues Trade-Audit-Event. Auto-generated event_id (uuid4) + timestamp.

        Pre: strategy_id non-empty, event_type ist TradeEventType,
             instrument_id non-empty, quantity > 0, price > 0.
        Post: Event wird in Bus aufgenommen, Stats inkrementiert,
              gibt unveraenderliches TradeAuditEvent zurueck.
        """
        if not strategy_id:
            raise ValueError("strategy_id required")
        if not isinstance(event_type, TradeEventType):
            raise TypeError("event_type must be TradeEventType")
        if not instrument_id:
            raise ValueError("instrument_id required")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if price <= 0:
            raise ValueError("price must be > 0")

        # Normalize compliance_tags + metadata
        normalized_tags = frozenset(compliance_tags) if compliance_tags else frozenset()
        normalized_metadata = (
            tuple(metadata) if metadata else ()
        )

        # V13-4: Metadata-Size-Cap (Anti-Memory-Bloat)
        meta_size = len(repr(normalized_metadata))
        if meta_size > self.max_metadata_bytes:
            raise ValueError(
                f"metadata size {meta_size} exceeds max_metadata_bytes "
                f"{self.max_metadata_bytes} (V13-4 cap)"
            )

        event = TradeAuditEvent(
            event_id=str(uuid.uuid4()),
            strategy_id=strategy_id,
            event_type=event_type,
            instrument_id=instrument_id,
            quantity=quantity,
            price=price,
            timestamp=time.time(),
            compliance_tags=normalized_tags,
            metadata=normalized_metadata,
        )

        with self._lock:
            # V13-4: Silent-Drop-Detection — wenn deque schon voll ist, fuehrt
            # append zu eviction des aeltesten Events (FIFO). Counter inkrementieren.
            if len(self._events) == self._events.maxlen:
                self._silent_drops_count += 1
            self._events.append(event)
            self._stats["total_published"] += 1
            self._stats["by_event_type"][event_type.value] += 1
            for tag in normalized_tags:
                self._stats["by_compliance_tag"][tag.value] += 1

        return event

    # -------------------------------------------------------------------- query
    def query(
        self,
        strategy_id: Optional[str] = None,
        event_type: Optional[TradeEventType] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        compliance_tag: Optional[ComplianceTag] = None,
    ) -> tuple:
        """Filter-Query ueber gespeicherte Events.

        Pre: alle Filter-Argumente optional; falls gesetzt, Typ-konform.
        Post: gibt unveraenderliches Tuple aller passenden Events
              (chronologisch nach Insertion-Order, snapshot zum Query-Zeitpunkt).
        """
        if event_type is not None and not isinstance(event_type, TradeEventType):
            raise TypeError("event_type must be TradeEventType")
        if compliance_tag is not None and not isinstance(compliance_tag, ComplianceTag):
            raise TypeError("compliance_tag must be ComplianceTag")

        with self._lock:
            results = []
            for ev in self._events:
                if strategy_id is not None and ev.strategy_id != strategy_id:
                    continue
                if event_type is not None and ev.event_type != event_type:
                    continue
                if since is not None and ev.timestamp < since:
                    continue
                if until is not None and ev.timestamp > until:
                    continue
                if compliance_tag is not None and compliance_tag not in ev.compliance_tags:
                    continue
                results.append(ev)
            return tuple(results)

    # ----------------------------------------------------------------- validate
    def validate_event(self, event: TradeAuditEvent) -> tuple:
        """Prueft Event gegen compliance_required-Set.

        Pre: event ist TradeAuditEvent.
        Post: gibt (is_valid: bool, missing_tags: list[str]) zurueck.
              is_valid=True wenn compliance_required leer ODER vollstaendig in event.compliance_tags.
        """
        if not isinstance(event, TradeAuditEvent):
            raise TypeError("event must be TradeAuditEvent")

        if not self.compliance_required:
            return True, []

        missing = self.compliance_required - event.compliance_tags
        if not missing:
            return True, []
        return False, sorted(t.value for t in missing)

    # ---------------------------------------------------------------- get_stats
    def get_stats(self) -> dict:
        """Snapshot der laufenden Statistik (deep-copy).

        V13-4: dict enthaelt silent_drops_count (Anzahl deque-maxlen Evictions).

        Post: gibt dict mit total_published, total_purged, by_event_type, by_compliance_tag,
              current_count, silent_drops_count zurueck. Aenderungen am Rueckgabe-dict
              beeinflussen nicht den Bus.
        """
        with self._lock:
            return {
                "total_published": self._stats["total_published"],
                "total_purged": self._stats["total_purged"],
                "by_event_type": dict(self._stats["by_event_type"]),
                "by_compliance_tag": dict(self._stats["by_compliance_tag"]),
                "current_count": len(self._events),
                "retention_window_h": self.retention_window_h,
                "silent_drops_count": self._silent_drops_count,
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
