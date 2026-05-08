"""Graphity Lock Manager [CRUX-MK]

Synaptic-Pattern Distributed-Lock fuer Graphity-Verlag Buchprojekt-Section-Edits.

Bio-Pattern-Korrespondenz (Synaptic-Vesikel-Release-Lock):
- Synaptic-Vesikel       -> Lock-Token (acquired by author)
- Pre-Synaptic-Release   -> acquire_lock (Author-X startet Edit)
- Post-Synaptic-Receptor -> wait_for_lock (Author-Y wartet auf Release)
- Refractory-Period      -> Lock-Cooldown (kein sofortiges Re-Lock)
- Neurotransmitter-Reuptake -> release_lock (Cleanup)

Architecture:
- HMAC-SHA256 signed lock-tokens (analog kmo_approval_gate.py)
- TTL-based auto-expiry (default 30 min, max 4h)
- Single-author single-section enforcement via SQLite
- Refractory-Period (60s) verhindert Lock-Thrashing
- Audit-Trail per Lock-Acquire / Lock-Release

CRUX-Bindung:
- Q_0: Section-Edit-Integritaet (kein Lost-Update)
- I_min: strukturierte Lock-Mechanik
- W_0: Pattern-Reuse aus Hotel-Saga (Synaptic-Pattern wiederverwendet)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Constants with units (no magic numbers)
DEFAULT_LOCK_TTL_SECONDS: int = 30 * 60  # 30 min
MAX_LOCK_TTL_SECONDS: int = 4 * 60 * 60  # 4h
REFRACTORY_PERIOD_SECONDS: int = 60  # 60s Cooldown nach Release
LOCK_NONCE_BYTES: int = 16  # 128-bit nonce
HMAC_DIGEST_HEX_LEN: int = 64  # SHA256 -> 64 hex chars
DEFAULT_DB_PATH: Path = Path.home() / ".graphity" / "lock_manager.db"
ENV_SECRET_KEY: str = "GRAPHITY_LOCK_SECRET"


@dataclass(frozen=True)
class LockToken:
    """Immutable Lock-Token (Synaptic-Vesikel-Aequivalent).

    Pre: author non-empty, section_id non-empty.
    Post: HMAC-SHA256 signed.
    """

    author: str
    project_id: str
    section_id: str
    acquired_at: int  # UNIX epoch
    expires_at: int
    nonce: str  # hex
    signature: str  # hex HMAC-SHA256

    def serialize(self) -> str:
        payload = {
            "author": self.author,
            "project_id": self.project_id,
            "section_id": self.section_id,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "signature": self.signature,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def deserialize(cls, token_str: str) -> "LockToken":
        try:
            data = json.loads(token_str)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError(f"Malformed lock token: {exc}") from exc


class GraphityLockManager:
    """Synaptic-Pattern Distributed Lock Manager fuer Graphity-Verlag.

    Pre-condition: ENV var GRAPHITY_LOCK_SECRET set OR secret passed to ctor.
    Post-condition: All lock-acquire/release auditable via SQLite-DB.

    Bio-Mapping:
    - acquire_lock = Pre-Synaptic-Vesikel-Release (Author-X startet Edit)
    - wait_for_lock = Post-Synaptic-Receptor (Author-Y wartet)
    - check_refractory = Refractory-Period-Check (60s nach Release)
    - release_lock = Neurotransmitter-Reuptake (Cleanup)
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        secret: Optional[str] = None,
    ):
        self._secret = secret or os.environ.get(ENV_SECRET_KEY)
        if not self._secret:
            raise RuntimeError(
                f"Lock secret missing: set ENV {ENV_SECRET_KEY} or pass secret="
            )
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if not exist. Idempotent."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS section_locks (
                    project_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    acquired_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY (project_id, section_id)
                );
                CREATE TABLE IF NOT EXISTS lock_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    acquired_at INTEGER NOT NULL,
                    released_at INTEGER NOT NULL,
                    release_type TEXT NOT NULL  -- 'normal' | 'expired' | 'forced'
                );
                CREATE INDEX IF NOT EXISTS idx_history_section
                    ON lock_history(project_id, section_id, released_at DESC);
                """
            )
            conn.commit()

    def _sign(
        self,
        author: str,
        project_id: str,
        section_id: str,
        acquired_at: int,
        expires_at: int,
        nonce: str,
    ) -> str:
        """HMAC-SHA256 over canonical message."""
        msg = (
            f"{author}|{project_id}|{section_id}|"
            f"{acquired_at}|{expires_at}|{nonce}"
        ).encode("utf-8")
        return hmac.new(
            self._secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()

    def _check_refractory(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        section_id: str,
        now: int,
    ) -> bool:
        """Refractory-Period-Check (Bio: Refractory-Period nach Spike).

        Returns True if section is still in refractory (cannot lock yet).
        """
        row = conn.execute(
            "SELECT released_at FROM lock_history "
            "WHERE project_id = ? AND section_id = ? "
            "ORDER BY released_at DESC LIMIT 1",
            (project_id, section_id),
        ).fetchone()
        if row is None:
            return False
        last_release = row[0]
        return (now - last_release) < REFRACTORY_PERIOD_SECONDS

    def acquire_lock(
        self,
        author: str,
        project_id: str,
        section_id: str,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> Optional[str]:
        """Acquire lock on section (Pre-Synaptic-Vesikel-Release).

        Pre: author/project_id/section_id non-empty, ttl in [60, MAX_LOCK_TTL].
        Post: On success returns serialized LockToken; on conflict returns None.

        Raises:
            ValueError: invalid input
            RuntimeError: refractory period active
        """
        if not author or not project_id or not section_id:
            raise ValueError(
                "author, project_id, section_id must all be non-empty"
            )
        if ttl_seconds < 60 or ttl_seconds > MAX_LOCK_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be in [60, {MAX_LOCK_TTL_SECONDS}]"
            )

        now = int(time.time())
        expires_at = now + ttl_seconds
        nonce = secrets.token_hex(LOCK_NONCE_BYTES)

        with closing(sqlite3.connect(self.db_path)) as conn:
            # Refractory-Period-Check (Bio: 60s post-release cooldown)
            if self._check_refractory(conn, project_id, section_id, now):
                raise RuntimeError(
                    f"Refractory period active for {project_id}/{section_id}; "
                    f"wait {REFRACTORY_PERIOD_SECONDS}s after last release."
                )

            # Cleanup expired locks first (lazy GC)
            conn.execute(
                "DELETE FROM section_locks WHERE expires_at <= ?",
                (now,),
            )

            # Sign token
            signature = self._sign(
                author, project_id, section_id, now, expires_at, nonce
            )

            try:
                conn.execute(
                    "INSERT INTO section_locks "
                    "(project_id, section_id, author, nonce, "
                    "acquired_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, section_id, author, nonce, now, expires_at),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None  # already held by other author

        token = LockToken(
            author=author,
            project_id=project_id,
            section_id=section_id,
            acquired_at=now,
            expires_at=expires_at,
            nonce=nonce,
            signature=signature,
        )
        return token.serialize()

    def verify_lock(self, token_str: str) -> bool:
        """Verify lock-token validity (signature + expiry + DB-presence).

        Pre: token_str is serialized LockToken.
        Post: returns True iff valid+matching+unexpired+not-released.
        """
        try:
            token = LockToken.deserialize(token_str)
        except ValueError:
            return False

        # Signature check (constant-time)
        expected_sig = self._sign(
            token.author,
            token.project_id,
            token.section_id,
            token.acquired_at,
            token.expires_at,
            token.nonce,
        )
        if not hmac.compare_digest(expected_sig, token.signature):
            return False

        # Expiry check
        now = int(time.time())
        if now >= token.expires_at:
            return False

        # DB-presence check
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT nonce, expires_at FROM section_locks "
                "WHERE project_id = ? AND section_id = ?",
                (token.project_id, token.section_id),
            ).fetchone()
            if row is None:
                return False
            db_nonce, db_expires_at = row
            if db_nonce != token.nonce:
                return False
            if db_expires_at != token.expires_at:
                return False

        return True

    def release_lock(self, token_str: str) -> bool:
        """Release lock (Bio: Neurotransmitter-Reuptake).

        Pre: token_str is serialized LockToken.
        Post: lock removed from section_locks, history-entry appended.

        Returns True on successful release, False if token invalid/already
        released.
        """
        try:
            token = LockToken.deserialize(token_str)
        except ValueError:
            return False

        # Signature check before any DB-write
        expected_sig = self._sign(
            token.author,
            token.project_id,
            token.section_id,
            token.acquired_at,
            token.expires_at,
            token.nonce,
        )
        if not hmac.compare_digest(expected_sig, token.signature):
            return False

        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            # Atomic: only release if author + nonce match
            cur = conn.execute(
                "DELETE FROM section_locks "
                "WHERE project_id = ? AND section_id = ? "
                "AND author = ? AND nonce = ?",
                (
                    token.project_id,
                    token.section_id,
                    token.author,
                    token.nonce,
                ),
            )
            if cur.rowcount != 1:
                return False  # not held or already released

            # History-entry (audit trail)
            conn.execute(
                "INSERT INTO lock_history "
                "(project_id, section_id, author, nonce, "
                "acquired_at, released_at, release_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    token.project_id,
                    token.section_id,
                    token.author,
                    token.nonce,
                    token.acquired_at,
                    now,
                    "normal",
                ),
            )
            conn.commit()
        return True

    def get_lock_status(
        self, project_id: str, section_id: str
    ) -> Optional[dict]:
        """Return current lock-holder info or None if free.

        Pre: project_id and section_id non-empty.
        Post: returns dict with author/expires_at or None.
        """
        if not project_id or not section_id:
            raise ValueError("project_id and section_id must be non-empty")

        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            # Lazy-GC expired locks
            conn.execute(
                "DELETE FROM section_locks WHERE expires_at <= ?",
                (now,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT author, acquired_at, expires_at, nonce "
                "FROM section_locks "
                "WHERE project_id = ? AND section_id = ?",
                (project_id, section_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "author": row[0],
                "acquired_at": row[1],
                "expires_at": row[2],
                "nonce": row[3],
            }

    def force_release(
        self, project_id: str, section_id: str, admin: str
    ) -> bool:
        """Admin-Override: force-release stuck lock (e.g. crashed author).

        Pre: admin non-empty.
        Post: lock removed, history-entry with release_type='forced'.
        """
        if not admin:
            raise ValueError("admin must be non-empty")
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT author, nonce, acquired_at FROM section_locks "
                "WHERE project_id = ? AND section_id = ?",
                (project_id, section_id),
            ).fetchone()
            if row is None:
                return False
            author, nonce, acquired_at = row

            conn.execute(
                "DELETE FROM section_locks "
                "WHERE project_id = ? AND section_id = ?",
                (project_id, section_id),
            )
            conn.execute(
                "INSERT INTO lock_history "
                "(project_id, section_id, author, nonce, "
                "acquired_at, released_at, release_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    section_id,
                    author,
                    nonce,
                    acquired_at,
                    now,
                    f"forced_by:{admin}",
                ),
            )
            conn.commit()
        return True
