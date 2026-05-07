"""KMO Lease Manager [CRUX-MK].

KMO-Patch P-KMO-A1: Zentraler Mutex/Lease-Manager fuer DF/Port/Token/Drive-Path-Locks.

DF-K16-konform (rules/df-akzeptanz-kriterien.md K16 Concurrent-Spawn-Mutex):
  - Atomic acquire via UNIQUE-Constraint + ON CONFLICT IGNORE
  - TTL-basiert (default 300s) mit Heartbeat-Renewal
  - Stale-Lease-Cleanup via expires_at-Index
  - STOP.flag-Respect (branch-hub/audit/STOP-{id}.flag)

SAE-Isomorphie: Trinity-Slot-Lock auf Resource-Ebene. Atomic-Insert = Optimistic-Lock.

Usage:
    mgr = LeaseManager()
    token = mgr.acquire(ResourceType.DF, "df-86", holder="mac.df-86.engine.pid-12345")
    if token:
        try:
            # ... do work ...
            mgr.heartbeat(token)  # alle 60s aufrufen bei langlaufenden Tasks
        finally:
            mgr.release(token)
"""

from __future__ import annotations

import enum
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


class ResourceType(enum.Enum):
    """Klassifizierte Resource-Typen fuer Lease-Manager."""

    DF = "DF"                            # Dark-Factory engine instance
    PORT = "PORT"                        # TCP-Port
    API_TOKEN = "API_TOKEN"              # OAuth-/API-Token slot (z.B. NLM-Login)
    DRIVE_PATH = "DRIVE_PATH"            # Filesystem-Path / Drive-Mountpoint
    TUNNEL_SUBDOMAIN = "TUNNEL_SUBDOMAIN"  # Cloudflare/ngrok Subdomain


# Default-Pfade. Override via constructor.
_DEFAULT_DB_DIR = Path.home() / "Library" / "Application Support" / "kmo"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "leases.db"
_DEFAULT_STOP_FLAG_DIR = Path.home() / "branch-hub" / "audit"

DEFAULT_TTL_SEC = 300
HEARTBEAT_INTERVAL_SEC = 60


@dataclass(frozen=True)
class LeaseInfo:
    """Read-only snapshot of a lease (for is_locked queries)."""

    lease_id: str
    resource_type: str
    resource_id: str
    holder: str
    acquired_at: float
    expires_at: float
    last_heartbeat: float
    metadata: Optional[dict]

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class LeaseManager:
    """Atomic resource-lease manager with SQLite WAL-mode backend.

    Pre-Conditions:
        - SQLite >= 3.7 (WAL support)
        - Write access to db_path parent dir

    Post-Conditions:
        - Acquire is atomic: only one holder per (resource_type, resource_id)
        - Stale-Leases (expires_at < now) can be force-released by any caller
        - STOP.flag presence blocks acquire (DF-K16 compliance)
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        stop_flag_dir: Optional[Path] = None,
        schema_path: Optional[Path] = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.stop_flag_dir = Path(stop_flag_dir) if stop_flag_dir else _DEFAULT_STOP_FLAG_DIR
        self.schema_path = (
            Path(schema_path) if schema_path else Path(__file__).parent / "schema.sql"
        )
        self._lock = threading.RLock()  # connection-level guard
        self._init_db()

    # ----------------------------- DB lifecycle --------------------------------

    def _init_db(self) -> None:
        """Creates DB file + schema if missing. Idempotent."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            if self.schema_path.exists():
                conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            else:
                # Fallback inline schema (for portable single-file deployments)
                conn.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    CREATE TABLE IF NOT EXISTS leases (
                        lease_id TEXT PRIMARY KEY,
                        resource_type TEXT NOT NULL,
                        resource_id TEXT NOT NULL,
                        holder TEXT NOT NULL,
                        acquired_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        last_heartbeat REAL NOT NULL,
                        metadata_json TEXT
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_leases_resource_unique
                        ON leases (resource_type, resource_id);
                    CREATE INDEX IF NOT EXISTS idx_leases_expires_at
                        ON leases (expires_at);
                    CREATE INDEX IF NOT EXISTS idx_leases_holder
                        ON leases (holder);
                    """
                )
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Context-managed SQLite connection with WAL + reasonable timeout."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    # ----------------------------- Public API ----------------------------------

    def respect_stop_flag(self, resource_id: str) -> bool:
        """Returns True if a STOP.flag exists for the resource (acquire is blocked).

        Looks for: {stop_flag_dir}/STOP-{resource_id}.flag
        """
        flag_path = self.stop_flag_dir / f"STOP-{resource_id}.flag"
        return flag_path.exists()

    def acquire(
        self,
        resource_type: ResourceType,
        resource_id: str,
        holder: str,
        ttl_sec: int = DEFAULT_TTL_SEC,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """Atomically acquires a lease. Returns lease_token (UUID) on success, else None.

        Pre:
            - resource_type is ResourceType
            - resource_id, holder are non-empty strings
            - ttl_sec > 0

        Post:
            - On success: a row exists in leases with PRIMARY KEY = lease_token
            - On failure (already locked OR STOP.flag): no row written, returns None
            - Stale leases (expires_at < now) are force-released first, then retried once
        """
        if not isinstance(resource_type, ResourceType):
            raise TypeError(f"resource_type must be ResourceType, got {type(resource_type)}")
        if not resource_id or not holder:
            raise ValueError("resource_id and holder must be non-empty")
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")

        # K16: STOP.flag respect
        if self.respect_stop_flag(resource_id):
            return None

        with self._lock:
            # First attempt
            token = self._try_insert(resource_type, resource_id, holder, ttl_sec, metadata)
            if token is not None:
                return token
            # Maybe stale lease exists -> cleanup and retry once
            released = self.force_release_stale()
            if released:
                token = self._try_insert(resource_type, resource_id, holder, ttl_sec, metadata)
                if token is not None:
                    return token
            return None

    def _try_insert(
        self,
        resource_type: ResourceType,
        resource_id: str,
        holder: str,
        ttl_sec: int,
        metadata: Optional[dict],
    ) -> Optional[str]:
        """Inner atomic-insert helper. Returns token or None on UNIQUE-Conflict."""
        token = str(uuid.uuid4())
        now = time.time()
        expires = now + ttl_sec
        meta_json = json.dumps(metadata) if metadata is not None else None
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO leases
                    (lease_id, resource_type, resource_id, holder,
                     acquired_at, expires_at, last_heartbeat, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        token,
                        resource_type.value,
                        resource_id,
                        holder,
                        now,
                        expires,
                        now,
                        meta_json,
                    ),
                )
                # Check whether OUR token actually got inserted (vs ON CONFLICT IGNORE).
                row = conn.execute(
                    "SELECT lease_id FROM leases WHERE lease_id = ?", (token,)
                ).fetchone()
                conn.commit()
                return token if row is not None else None
            except sqlite3.IntegrityError:
                return None

    def release(self, lease_token: str) -> bool:
        """Releases a lease by token. Returns True iff a row was deleted.

        Pre: lease_token is a non-empty string
        Post: row with lease_id == lease_token no longer exists
        """
        if not lease_token:
            return False
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM leases WHERE lease_id = ?", (lease_token,))
            conn.commit()
            return cur.rowcount > 0

    def heartbeat(self, lease_token: str, ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
        """Refreshes the lease TTL. Returns True iff lease exists and was renewed.

        Pre: lease_token non-empty, ttl_sec > 0
        Post: last_heartbeat = now, expires_at = now + ttl_sec
              (only if lease still exists; expired leases also get renewed if not yet purged)
        """
        if not lease_token or ttl_sec <= 0:
            return False
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE leases
                SET last_heartbeat = ?, expires_at = ?
                WHERE lease_id = ?
                """,
                (now, now + ttl_sec, lease_token),
            )
            conn.commit()
            return cur.rowcount > 0

    def is_locked(
        self, resource_type: ResourceType, resource_id: str
    ) -> Optional[LeaseInfo]:
        """Returns LeaseInfo iff resource is currently locked AND lease not expired.

        Note: an expired-but-not-yet-cleaned lease returns None (treated as released).
        """
        if not isinstance(resource_type, ResourceType):
            raise TypeError("resource_type must be ResourceType")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM leases
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type.value, resource_id),
            ).fetchone()
            if row is None:
                return None
            info = self._row_to_info(row)
            return None if info.is_expired else info

    def force_release_stale(self) -> List[str]:
        """Deletes all expired leases. Returns list of released lease_ids."""
        now = time.time()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT lease_id FROM leases WHERE expires_at < ?", (now,)
            ).fetchall()
            ids = [r["lease_id"] for r in rows]
            if ids:
                conn.execute(
                    f"DELETE FROM leases WHERE lease_id IN ({','.join('?' * len(ids))})",
                    ids,
                )
                conn.commit()
            return ids

    # ----------------------------- Diagnostics --------------------------------

    def list_active(self) -> List[LeaseInfo]:
        """Returns snapshot of all currently active (not-expired) leases."""
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM leases WHERE expires_at >= ? ORDER BY acquired_at",
                (now,),
            ).fetchall()
            return [self._row_to_info(r) for r in rows]

    def get_by_token(self, lease_token: str) -> Optional[LeaseInfo]:
        """Returns LeaseInfo by lease_token (or None)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_token,)
            ).fetchone()
            return self._row_to_info(row) if row else None

    @staticmethod
    def _row_to_info(row: sqlite3.Row) -> LeaseInfo:
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else None
        return LeaseInfo(
            lease_id=row["lease_id"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            holder=row["holder"],
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
            last_heartbeat=row["last_heartbeat"],
            metadata=meta,
        )


# CRUX-MK
