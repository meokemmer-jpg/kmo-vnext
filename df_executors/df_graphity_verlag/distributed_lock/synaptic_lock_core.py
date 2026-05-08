"""Synaptic-Lock-Core (Pattern-Core, domain-agnostic) [CRUX-MK].

Welle-31 P-W31-1: Pattern-Core fuer Distributed-Lock mit Refractory-Period.
Field-neutral: holder_id/container_key/resource_key (Domain mappt).

Zustandsmaschine: FREE --acquire--> HELD --release--> REFRACTORY --(t > T_ref)--> FREE.

Invariants:
  I-SLC-1: at most ONE holder per resource at any t.
  I-SLC-2: HMAC tamper-evident (constant-time compare).
  I-SLC-3: TTL-bounded.
  I-SLC-4: Refractory blocks acquire T_ref seconds after release.
  I-SLC-5: history append-only.

Failure-Model:
  F-SLC-1 race: SQLite UNIQUE -> 1 winner.  F-SLC-2 forged: HMAC-mismatch -> False.
  F-SLC-3 expired: now >= expires_at -> False.  F-SLC-4 refractory: raises RuntimeError.

Hash-Chain (Synaptic-Plasticity, LTP) lebt in `synaptic_plasticity.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Pattern-Core Defaults
LOCK_NONCE_BYTES: int = 16
HMAC_DIGEST_HEX_LEN: int = 64


@dataclass(frozen=True)
class CoreLockToken:
    """Immutable Lock-Token (Pattern-Core, field-neutral)."""

    holder_id: str
    container_key: str
    resource_key: str
    acquired_at: int
    expires_at: int
    nonce: str
    signature: str

    def serialize(self) -> str:
        return json.dumps(
            {"holder_id": self.holder_id, "container_key": self.container_key,
             "resource_key": self.resource_key, "acquired_at": self.acquired_at,
             "expires_at": self.expires_at, "nonce": self.nonce,
             "signature": self.signature},
            sort_keys=True, separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, token_str: str) -> "CoreLockToken":
        try:
            return cls(**json.loads(token_str))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError(f"Malformed core lock token: {exc}") from exc


def sign_token(
    secret: str,
    holder_id: str,
    container_key: str,
    resource_key: str,
    acquired_at: int,
    expires_at: int,
    nonce: str,
) -> str:
    """HMAC-SHA256 over canonical message (Pattern-Core)."""
    msg = (
        f"{holder_id}|{container_key}|{resource_key}|"
        f"{acquired_at}|{expires_at}|{nonce}"
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def init_core_db(db_path: Path) -> None:
    """Create Pattern-Core lock + history tables (idempotent)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS resource_locks (
                container_key TEXT NOT NULL,
                resource_key TEXT NOT NULL,
                holder_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                acquired_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (container_key, resource_key)
            );
            CREATE TABLE IF NOT EXISTS lock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_key TEXT NOT NULL,
                resource_key TEXT NOT NULL,
                holder_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                acquired_at INTEGER NOT NULL,
                released_at INTEGER NOT NULL,
                release_type TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_resource
                ON lock_history(container_key, resource_key, released_at DESC);
            """
        )
        conn.commit()


def is_in_refractory(
    conn: sqlite3.Connection,
    container_key: str,
    resource_key: str,
    now: int,
    refractory_period_sec: int,
) -> bool:
    """Pattern-Core Refractory-Check (I-SLC-4)."""
    row = conn.execute(
        "SELECT released_at FROM lock_history "
        "WHERE container_key = ? AND resource_key = ? "
        "ORDER BY released_at DESC LIMIT 1",
        (container_key, resource_key),
    ).fetchone()
    if row is None:
        return False
    last_release = row[0]
    return (now - last_release) < refractory_period_sec


def acquire_core(
    db_path: Path, secret: str, holder_id: str, container_key: str,
    resource_key: str, ttl_seconds: int, refractory_period_sec: int,
    now: Optional[int] = None,
) -> Optional[str]:
    """Pattern-Core acquire (I-SLC-1). Returns serialized token or None on conflict.

    Raises RuntimeError on F-SLC-4 (refractory active).
    """
    if not (holder_id and container_key and resource_key):
        raise ValueError("holder_id, container_key, resource_key non-empty")

    now_int = int(time.time()) if now is None else now
    expires_at = now_int + ttl_seconds
    nonce = secrets.token_hex(LOCK_NONCE_BYTES)

    with closing(sqlite3.connect(db_path)) as conn:
        if is_in_refractory(conn, container_key, resource_key, now_int,
                            refractory_period_sec):
            raise RuntimeError(
                f"Refractory period active for {container_key}/{resource_key}; "
                f"wait {refractory_period_sec}s after last release."
            )
        conn.execute("DELETE FROM resource_locks WHERE expires_at <= ?", (now_int,))
        signature = sign_token(secret, holder_id, container_key, resource_key,
                               now_int, expires_at, nonce)
        try:
            conn.execute(
                "INSERT INTO resource_locks "
                "(container_key, resource_key, holder_id, nonce, "
                "acquired_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (container_key, resource_key, holder_id, nonce, now_int, expires_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return None  # I-SLC-1
    return CoreLockToken(
        holder_id=holder_id, container_key=container_key,
        resource_key=resource_key, acquired_at=now_int,
        expires_at=expires_at, nonce=nonce, signature=signature,
    ).serialize()


def _check_signature(secret: str, token: CoreLockToken) -> bool:
    """Pattern-Core: HMAC verification (I-SLC-2)."""
    expected = sign_token(
        secret, token.holder_id, token.container_key, token.resource_key,
        token.acquired_at, token.expires_at, token.nonce,
    )
    return hmac.compare_digest(expected, token.signature)


def verify_core(db_path: Path, secret: str, token_str: str) -> bool:
    """Pattern-Core verify: signature + expiry + DB-presence (I-SLC-2/3)."""
    try:
        token = CoreLockToken.deserialize(token_str)
    except ValueError:
        return False
    if not _check_signature(secret, token):
        return False
    if int(time.time()) >= token.expires_at:
        return False
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT nonce, expires_at FROM resource_locks "
            "WHERE container_key = ? AND resource_key = ?",
            (token.container_key, token.resource_key),
        ).fetchone()
        if row is None or row[0] != token.nonce or row[1] != token.expires_at:
            return False
    return True


def release_core(db_path: Path, secret: str, token_str: str) -> bool:
    """Pattern-Core release (Reuptake-Event)."""
    try:
        token = CoreLockToken.deserialize(token_str)
    except ValueError:
        return False
    if not _check_signature(secret, token):
        return False
    now = int(time.time())
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "DELETE FROM resource_locks "
            "WHERE container_key = ? AND resource_key = ? "
            "AND holder_id = ? AND nonce = ?",
            (token.container_key, token.resource_key,
             token.holder_id, token.nonce),
        )
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO lock_history "
            "(container_key, resource_key, holder_id, nonce, "
            "acquired_at, released_at, release_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token.container_key, token.resource_key, token.holder_id,
             token.nonce, token.acquired_at, now, "normal"),
        )
        conn.commit()
    return True


# [CRUX-MK]
