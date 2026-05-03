"""KMO Cell-Boundary Audit Trail [CRUX-MK].

Append-only Cross-Cell I/O-Audit-Logger. Loggt alle Cell-Boundary-Events
(consume, validate, apoptose) in eine SQLite-WAL-DB pro Hotel.

K12 Distillation-Resistenz: Provenance-Pflicht in Outputs.
K13 Independent-Ground-Truth: Audit-Trail extern persistent.
K14 Human-Override-Decay: Komplette Forensik via SQL-Query.

SAE-Isomorphie: AuditEntry frozen dataclass + atomic append (analog action-log.jsonl).

Schema:
    boundary_events (
        event_id TEXT PRIMARY KEY,        -- UUID4
        cell_id TEXT NOT NULL,
        hotel_id TEXT NOT NULL,           -- ROW-LEVEL-SECURITY-Filter
        event_type TEXT NOT NULL,         -- consume/validate/apoptose
        event_subtype TEXT,               -- e.g. tokens/cpu/input/output
        timestamp REAL NOT NULL,
        payload_hash TEXT,                -- SHA256 fuer payload-Provenance
        details_json TEXT,
        machine_id TEXT NOT NULL          -- multi-machine deduplication
    )
"""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional


_DEFAULT_DB_DIR = Path.home() / "Library" / "Application Support" / "kmo"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "boundary_audit.db"


@dataclass(frozen=True)
class BoundaryEvent:
    """Immutable read-only Audit-Event snapshot."""

    event_id: str
    cell_id: str
    hotel_id: str
    event_type: str  # "consume" | "validate" | "apoptose" | "io_call"
    event_subtype: Optional[str]
    timestamp: float
    payload_hash: Optional[str]
    details: Optional[dict]
    machine_id: str


def _hash_payload(payload: Any) -> str:
    """Compute SHA256 of JSON-serialized payload (provenance fingerprint)."""
    try:
        text = json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        text = repr(payload)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BoundaryAuditLog:
    """Append-only audit log for Cell-Boundary events. SQLite-WAL backed.

    Pre-Conditions:
        - SQLite >= 3.7 (WAL support)
        - Write-access to db_path parent dir

    Post-Conditions:
        - All append operations are atomic
        - hotel_id Row-Level-Security: queries enforce hotel_id filter
        - Audit-trail is append-only (no UPDATE, no DELETE outside purge_hotel)
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        machine_id: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.machine_id = machine_id or socket.gethostname()
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS boundary_events (
                    event_id TEXT PRIMARY KEY,
                    cell_id TEXT NOT NULL,
                    hotel_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_subtype TEXT,
                    timestamp REAL NOT NULL,
                    payload_hash TEXT,
                    details_json TEXT,
                    machine_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_boundary_events_hotel
                    ON boundary_events (hotel_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_boundary_events_cell
                    ON boundary_events (cell_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_boundary_events_type
                    ON boundary_events (event_type, timestamp);
                """
            )
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    # ---------------- Public API ----------------

    def append(
        self,
        cell_id: str,
        hotel_id: str,
        event_type: str,
        event_subtype: Optional[str] = None,
        payload: Any = None,
        details: Optional[dict] = None,
        timestamp: Optional[float] = None,
    ) -> str:
        """Append a single boundary-event. Returns event_id (UUID).

        Pre:
            - cell_id, hotel_id, event_type non-empty
        Post:
            - exactly one row inserted with PRIMARY KEY = event_id
        """
        if not cell_id or not hotel_id or not event_type:
            raise ValueError("cell_id, hotel_id, event_type are required")
        event_id = str(uuid.uuid4())
        ts = timestamp if timestamp is not None else time.time()
        payload_hash = _hash_payload(payload) if payload is not None else None
        details_json = json.dumps(details, default=str) if details is not None else None
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO boundary_events
                (event_id, cell_id, hotel_id, event_type, event_subtype,
                 timestamp, payload_hash, details_json, machine_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    cell_id,
                    hotel_id,
                    event_type,
                    event_subtype,
                    ts,
                    payload_hash,
                    details_json,
                    self.machine_id,
                ),
            )
            conn.commit()
        return event_id

    def read_for_cell(
        self, cell_id: str, hotel_id: str, limit: int = 1000
    ) -> List[BoundaryEvent]:
        """Read events for a specific cell. Hotel-ID-Filter Pflicht (Multi-Tenancy)."""
        if not cell_id or not hotel_id:
            raise ValueError("cell_id and hotel_id required")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM boundary_events
                WHERE cell_id = ? AND hotel_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (cell_id, hotel_id, int(limit)),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]

    def read_for_hotel(
        self,
        hotel_id: str,
        event_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List[BoundaryEvent]:
        """Read events for a hotel (Multi-Tenancy-Aggregate). Optional event_type filter."""
        if not hotel_id:
            raise ValueError("hotel_id required")
        sql = "SELECT * FROM boundary_events WHERE hotel_id = ?"
        params: list[Any] = [hotel_id]
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        sql += " ORDER BY timestamp ASC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_event(r) for r in rows]

    def count_for_cell(self, cell_id: str, hotel_id: str) -> int:
        """Count events for a specific cell."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM boundary_events
                WHERE cell_id = ? AND hotel_id = ?
                """,
                (cell_id, hotel_id),
            ).fetchone()
            return int(row["n"]) if row else 0

    def purge_hotel(self, hotel_id: str) -> int:
        """GDPR right-to-be-forgotten: cascade-delete all events for a hotel.

        Returns number of deleted rows. K13 GDPR-Compliance.
        """
        if not hotel_id:
            raise ValueError("hotel_id required")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM boundary_events WHERE hotel_id = ?", (hotel_id,)
            )
            conn.commit()
            return int(cur.rowcount)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> BoundaryEvent:
        details = json.loads(row["details_json"]) if row["details_json"] else None
        return BoundaryEvent(
            event_id=row["event_id"],
            cell_id=row["cell_id"],
            hotel_id=row["hotel_id"],
            event_type=row["event_type"],
            event_subtype=row["event_subtype"],
            timestamp=row["timestamp"],
            payload_hash=row["payload_hash"],
            details=details,
            machine_id=row["machine_id"],
        )


# CRUX-MK
