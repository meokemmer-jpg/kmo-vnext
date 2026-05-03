"""KMO Hotel-Membrane [CRUX-MK].

Welle-9γ Phase-3 Modul 3.2: Multi-Tenancy-Boundary ueber Phase-1 hinaus.

Bio-Aequivalent: Vollstaendige Tissue-Membrane. Endothel-Schicht mit selektiven
Transport-Mechanismen. Blood-Brain-Barrier-Analog.

Anorg-Mapping: A-27 Epitaxie (Substrat-konforme Schicht), A-26 Templated-Crystal-Growth.

Komponenten:
  - HotelMembrane: tag-based Tenancy-Boundary mit Path-Isolation
  - GDPRComplianceLayer: Consent + Right-to-be-Forgotten cascade
  - CrossHotelQueryBlocker: Pre-Query-Hook + Whitelist
"""

from __future__ import annotations

import enum
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


SQL_HOTEL_ID_FILTER_RE = re.compile(
    r"\bhotel_id\s*=\s*[?:]?\w*", re.IGNORECASE
)


class DataCategory(str, enum.Enum):
    """GDPR-Datenkategorien per Hotel."""

    BOOKING = "booking"
    PAYMENT = "payment"
    COMMUNICATION = "communication"
    ANALYTICS = "analytics"
    OPERATIONAL = "operational"


@dataclass
class ConsentRecord:
    """Per-Hotel-Per-Category-Consent-Status."""

    hotel_id: str
    category: DataCategory
    granted: bool
    timestamp: float
    notes: str = ""


@dataclass
class HotelMembrane:
    """Tag-based Tenancy-Boundary mit Path-Isolation.

    Pre: hotel_id non-empty, base_state_dir writable
    Post:
        - hotel_state_dir() returns isolated subtree per hotel
        - validate_payload_tag enforces hotel_id consistency
    """

    hotel_id: str
    base_state_dir: Path
    region: str = "EU"  # default: GDPR-strict region

    def __post_init__(self) -> None:
        if not self.hotel_id or not isinstance(self.hotel_id, str):
            raise ValueError("hotel_id must be non-empty string")
        if not re.match(r"^[A-Za-z0-9._-]+$", self.hotel_id):
            raise ValueError(
                f"hotel_id contains unsafe characters: {self.hotel_id!r}"
            )
        Path(self.base_state_dir).mkdir(parents=True, exist_ok=True)

    def hotel_state_dir(self) -> Path:
        """Isolated state-subtree per hotel (Path-Isolation)."""
        d = Path(self.base_state_dir) / f"hotel-{self.hotel_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def validate_payload_tag(self, payload: Any) -> bool:
        """Verify payload has matching hotel_id (if it's a dict)."""
        if not isinstance(payload, dict):
            return True  # non-dict payloads pass-through
        if "hotel_id" not in payload:
            return True  # untagged passes (caller decides)
        return payload["hotel_id"] == self.hotel_id


class CrossHotelQueryBlocker:
    """Pre-Query-Hook: detektiert SQL-Queries ohne hotel_id-Filter, blockt.

    Whitelist fuer explizite Cross-Hotel-Aggregationen (Organism-Layer-DFs).

    Pre: whitelist is set of caller-IDs allowed to aggregate cross-hotel
    Post: check_query raises PermissionError on missing filter (unless whitelisted)
    """

    def __init__(self, whitelist: Optional[set[str]] = None) -> None:
        self.whitelist = set(whitelist or set())
        self._lock = threading.RLock()

    def check_query(self, sql: str, caller_id: str) -> bool:
        """Returns True if query OK, raises PermissionError otherwise."""
        if not sql:
            raise ValueError("sql required")
        if caller_id in self.whitelist:
            return True
        if not SQL_HOTEL_ID_FILTER_RE.search(sql):
            raise PermissionError(
                f"SQL query missing hotel_id filter (caller={caller_id!r}): "
                f"{sql[:80]}..."
            )
        return True

    def add_to_whitelist(self, caller_id: str) -> None:
        with self._lock:
            self.whitelist.add(caller_id)

    def remove_from_whitelist(self, caller_id: str) -> bool:
        with self._lock:
            if caller_id in self.whitelist:
                self.whitelist.remove(caller_id)
                return True
            return False


class GDPRComplianceLayer:
    """Per-Hotel-GDPR-Boundary mit Consent-Tracking + Right-to-be-Forgotten.

    Pre: audit_path writable
    Post:
        - grant_consent / revoke_consent atomic
        - has_consent fast-path lookup
        - purge_hotel_data cascade-deletes all consent + emits GDPR-event
    """

    def __init__(self, audit_path: Path) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # consent: hotel_id -> category -> ConsentRecord
        self._consent: dict[str, dict[DataCategory, ConsentRecord]] = {}

    def grant_consent(
        self, hotel_id: str, category: DataCategory, notes: str = ""
    ) -> None:
        if not hotel_id:
            raise ValueError("hotel_id required")
        if not isinstance(category, DataCategory):
            raise TypeError("category must be DataCategory")
        with self._lock:
            self._consent.setdefault(hotel_id, {})[category] = ConsentRecord(
                hotel_id=hotel_id,
                category=category,
                granted=True,
                timestamp=time.time(),
                notes=notes,
            )
            self._audit_event("grant_consent", hotel_id, category=category.value)

    def revoke_consent(
        self, hotel_id: str, category: DataCategory
    ) -> bool:
        with self._lock:
            cats = self._consent.get(hotel_id, {})
            if category not in cats:
                return False
            cats[category] = ConsentRecord(
                hotel_id=hotel_id,
                category=category,
                granted=False,
                timestamp=time.time(),
            )
            self._audit_event("revoke_consent", hotel_id, category=category.value)
            return True

    def has_consent(self, hotel_id: str, category: DataCategory) -> bool:
        with self._lock:
            rec = self._consent.get(hotel_id, {}).get(category)
            return bool(rec and rec.granted)

    def purge_hotel_data(self, hotel_id: str) -> dict:
        """GDPR cascade-delete: removes consent + emits forensic event."""
        if not hotel_id:
            raise ValueError("hotel_id required")
        with self._lock:
            existed = hotel_id in self._consent
            cats_count = len(self._consent.get(hotel_id, {}))
            if existed:
                del self._consent[hotel_id]
            self._audit_event("purge_hotel_data", hotel_id, cats_purged=cats_count)
            return {
                "hotel_id": hotel_id,
                "consent_records_purged": cats_count,
                "existed": existed,
            }

    def _audit_event(self, event: str, hotel_id: str, **kwargs: Any) -> None:
        """Append forensic-event to audit-log (1-line JSON)."""
        record = {
            "ts": time.time(),
            "event": event,
            "hotel_id": hotel_id,
            **kwargs,
        }
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


# CRUX-MK
