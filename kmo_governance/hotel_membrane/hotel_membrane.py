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

# Patch P3 (Welle-9-gamma Open-Item #3 Gemini "Security-Theater regex bypassable"):
# AST-based SQL validator detects bypass attempts that the regex misses:
#   - hotel_id filter inside comments (--/* ... */)
#   - hotel_id filter only in subquery (not on outer-table)
#   - hotel_id != ... (negation; technically a filter but allows scan)
#   - OR-clauses that void the filter (WHERE hotel_id='X' OR 1=1)
# This complements (does NOT replace) the regex check.

# SQL Token-Tier Helper
_SQL_COMMENT_LINE = re.compile(r"--[^\n]*", re.IGNORECASE)
_SQL_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_SQL_KEYWORDS_DML = ("SELECT", "UPDATE", "DELETE", "INSERT")


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments (line + block) before AST-analysis."""
    sql = _SQL_COMMENT_LINE.sub("", sql)
    sql = _SQL_COMMENT_BLOCK.sub("", sql)
    return sql


def _strip_subqueries(sql: str) -> str:
    """Remove all parenthesized subqueries (depth > 0).

    Naive but effective: walks chars, drops everything inside (...).
    """
    out = []
    depth = 0
    for ch in sql:
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _extract_outer_where(sql: str) -> str:
    """Extract the outermost WHERE clause (subqueries excluded).

    Naive but effective: finds top-level WHERE by counting parentheses.
    Returns '' if no outer WHERE found.
    """
    sql_upper = sql.upper()
    n = len(sql)
    depth = 0
    where_start = -1
    i = 0
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and sql_upper[i:i + 5] == "WHERE":
            # Check word-boundary
            if i == 0 or not sql_upper[i - 1].isalnum():
                if i + 5 == n or not sql_upper[i + 5].isalnum():
                    where_start = i + 5
                    break
        i += 1
    if where_start < 0:
        return ""
    # Take from after WHERE until end OR next top-level keyword
    rest = sql[where_start:]
    # Split on top-level GROUP BY, ORDER BY, LIMIT, HAVING
    rest_upper = rest.upper()
    n_r = len(rest)
    depth = 0
    cut = n_r
    keywords_after = ("GROUP BY", "ORDER BY", "HAVING", "LIMIT", "UNION")
    j = 0
    while j < n_r:
        ch = rest[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            for kw in keywords_after:
                if rest_upper[j:j + len(kw)] == kw:
                    if j == 0 or not rest_upper[j - 1].isalnum():
                        cut = j
                        break
            if cut < n_r:
                break
        j += 1
    return rest[:cut].strip()


def ast_check_hotel_id_filter(sql: str) -> tuple[bool, str]:
    """Patch P3 AST-Validator (Gemini-Finding "Security-Theater").

    Returns (ok, reason).
    Detects:
      - hotel_id filter only in subquery (not outer-WHERE)
      - hotel_id != / <> / NOT IN (negation; allows table-scan)
      - OR-clauses that void the filter
      - hotel_id filter inside comments only
    """
    if not sql or not isinstance(sql, str):
        return (False, "empty-sql")
    # 1) Strip comments (regex match was vulnerable to comment-injection)
    stripped = _strip_sql_comments(sql)

    # 2) Extract outer-WHERE (filter must be in outer query, not subquery)
    outer_where = _extract_outer_where(stripped)
    if not outer_where:
        return (False, "no-outer-where-clause")

    # 3) Strip subqueries from outer-WHERE — sonst wuerde Subquery-WHERE
    #    den outer-WHERE-Filter-Check kontaminieren.
    outer_where_no_subq = _strip_subqueries(outer_where)

    # 4) hotel_id muss IRGENDWO im outer-where (nach subquery-strip) auftauchen
    if "hotel_id" not in outer_where_no_subq.lower():
        return (False, "hotel_id-filter-only-in-subquery")

    # 5) Negation-Check: hotel_id != / <> / NOT IN erlaubt Table-Scan
    if re.search(
        r"\bhotel_id\s*(!=|<>)", outer_where_no_subq, re.IGNORECASE
    ):
        return (False, "negated-hotel_id-filter-allows-scan")
    if re.search(
        r"\bhotel_id\s+NOT\s+IN\b", outer_where_no_subq, re.IGNORECASE
    ):
        return (False, "negated-hotel_id-filter-allows-scan")

    # 6) Positive-Equality-Check: nach Negation-Filter muss `hotel_id =` existieren
    if not SQL_HOTEL_ID_FILTER_RE.search(outer_where_no_subq):
        return (False, "no-positive-hotel_id-equality")

    # 7) OR-Clause-Check: `hotel_id='X' OR 1=1` voids the filter
    if re.search(r"\bOR\b", outer_where_no_subq, re.IGNORECASE):
        return (False, "or-clause-may-void-hotel_id-filter")
    return (True, "ok")


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

    def __init__(
        self, whitelist: Optional[set[str]] = None, ast_strict: bool = False
    ) -> None:
        """Patch P3: ast_strict=True activates AST-based validation
        (Gemini-Finding "Security-Theater regex bypassable").
        Default False fuer backwards-compat.
        """
        self.whitelist = set(whitelist or set())
        self.ast_strict = ast_strict
        self._lock = threading.RLock()

    def check_query(self, sql: str, caller_id: str) -> bool:
        """Returns True if query OK, raises PermissionError otherwise.

        Patch P3: when ast_strict=True, AST-validator is also run after
        regex passes — catches bypass-attempts the regex misses.
        """
        if not sql:
            raise ValueError("sql required")
        if caller_id in self.whitelist:
            return True
        if not SQL_HOTEL_ID_FILTER_RE.search(sql):
            raise PermissionError(
                f"SQL query missing hotel_id filter (caller={caller_id!r}): "
                f"{sql[:80]}..."
            )
        # Patch P3: AST-strict validation
        if self.ast_strict:
            ok, reason = ast_check_hotel_id_filter(sql)
            if not ok:
                raise PermissionError(
                    f"SQL query failed AST-validation (caller={caller_id!r}, "
                    f"reason={reason}): {sql[:80]}..."
                )
        return True

    def check_query_ast(self, sql: str, caller_id: str) -> tuple[bool, str]:
        """Patch P3: explicit AST-only check (returns ok+reason, does not raise).

        Useful for whitelisted callers + diagnostic-mode.
        """
        if caller_id in self.whitelist:
            return (True, "whitelisted")
        return ast_check_hotel_id_filter(sql)

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
