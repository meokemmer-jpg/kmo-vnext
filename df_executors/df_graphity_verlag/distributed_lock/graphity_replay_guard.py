"""Graphity Replay-Guard [CRUX-MK].

Welle-31 P-W31-2: Anti-Replay + Vector-Clocks + Sender-Binding fuer
Synaptic-Pattern Distributed-Lock.

Probleme (V14 Codex MODIFY):
    1. HMAC-Token-Replay nach Refractory-Period-Ablauf:
       Token bleibt valide bis ``expires_at``. Wenn Refractory-Period
       (60s) ablaeuft, kann ein altes Token wieder genutzt werden.
    2. Hash-Chain-Truncation:
       Wenn jemand letzte N Eintraege loescht, ist Chain-Truncation
       unentdeckt (verify_chain prueft nur Hashes, nicht "letzte Hash
       muss gegen externen Anker stimmen").
    3. Token-Theft:
       HMAC-Token kann zwischen Authoren weitergereicht werden ohne
       Detection (gleiche Author-ID im Token).
    4. Clock-Skew:
       UNIX-Epoch-Timestamps koennen bei Cross-Node-Zeitdrift
       Reihenfolge falsch klassifizieren.

Loesung:
    1. Replay-Cache (used-nonce-Set) verhindert Re-Use von Tokens
       NACH Release UND nach Refractory-Period-Ablauf.
    2. Chain-Length-Anchor: signiertes Tail-Hash erlaubt
       Truncation-Detection.
    3. Sender-Bound-Token: ip_or_host_fingerprint im Token, Verifikation
       erfordert Match.
    4. Vector-Clock-Layer (Lamport-Timestamp pro Author) ueber UNIX-Zeit
       hinaus.

CRUX-Bindung:
    K_0: indirekt geschuetzt (Replay-Schutz + Token-Theft-Detection)
    Q_0: epistemische Integritaet via Vector-Clock-Causal-Order
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Constants (no magic numbers)
DEFAULT_REPLAY_CACHE_DB: Path = (
    Path.home() / ".graphity" / "replay_cache.db"
)
ENV_REPLAY_SECRET: str = "GRAPHITY_REPLAY_SECRET"
DEFAULT_REPLAY_CACHE_TTL_SEC: int = 24 * 60 * 60  # 24h
SENDER_FINGERPRINT_BYTES: int = 16


@dataclass(frozen=True)
class VectorClock:
    """Lamport-Timestamp + UNIX-Epoch Hybrid pro Author.

    Pre: author non-empty.
    Post: lamport monotonically increasing per author.
    """

    author: str
    lamport: int
    wall_clock_unix: int

    def is_after(self, other: "VectorClock") -> bool:
        """Causal-Order: True iff self happened-after other."""
        if self.author == other.author:
            return self.lamport > other.lamport
        # Different authors: rely on Lamport (no global wall-clock trust).
        return self.lamport > other.lamport

    def serialize(self) -> str:
        return json.dumps(
            {
                "author": self.author,
                "lamport": self.lamport,
                "wall_clock_unix": self.wall_clock_unix,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class ReplayGuard:
    """Replay-Guard fuer Graphity-Lock-Tokens.

    Speichert verbrauchte Nonces in SQLite (TTL-bereinigt). Pruefe vor
    Lock-Acquire ob Token-Nonce bereits konsumiert.

    Plus Lamport-Vector-Clocks pro Author (in-memory + SQLite-persistent
    nach optional flush).

    Pre: db_path parent dir creatable.
    Post: ``mark_used``+``is_used`` race-safe (SQLite-PRIMARY-KEY-Lock).
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_REPLAY_CACHE_DB,
        secret: Optional[str] = None,
    ) -> None:
        self._secret = secret or os.environ.get(ENV_REPLAY_SECRET)
        if not self._secret:
            raise RuntimeError(
                f"Replay secret missing: set ENV "
                f"{ENV_REPLAY_SECRET} or pass secret="
            )
        self.db_path = db_path
        self._lock = threading.RLock()
        self._lamport_clocks: dict[str, int] = {}
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS used_nonces (
                    nonce TEXT NOT NULL PRIMARY KEY,
                    author TEXT NOT NULL,
                    sender_fingerprint TEXT NOT NULL,
                    consumed_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_used_nonces_expires
                    ON used_nonces(expires_at);
                CREATE TABLE IF NOT EXISTS chain_anchors (
                    project_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    last_block_index INTEGER NOT NULL,
                    last_block_hash TEXT NOT NULL,
                    anchor_signature TEXT NOT NULL,
                    anchored_at INTEGER NOT NULL,
                    PRIMARY KEY (project_id, section_id)
                );
                """
            )
            conn.commit()

    @staticmethod
    def compute_sender_fingerprint(
        author: str, ip_or_host: str
    ) -> str:
        """Stable Fingerprint aus author+ip_or_host fuer Sender-Binding."""
        msg = f"{author}|{ip_or_host}".encode("utf-8")
        return hashlib.sha256(msg).hexdigest()[
            : SENDER_FINGERPRINT_BYTES * 2
        ]

    def is_used(self, nonce: str) -> bool:
        """Returns True iff nonce already consumed (replay-attempt)."""
        if not nonce:
            return False
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            # Lazy-GC expired entries.
            conn.execute(
                "DELETE FROM used_nonces WHERE expires_at <= ?",
                (now,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT 1 FROM used_nonces WHERE nonce = ?",
                (nonce,),
            ).fetchone()
            return row is not None

    def mark_used(
        self,
        nonce: str,
        author: str,
        sender_fingerprint: str,
        ttl_sec: int = DEFAULT_REPLAY_CACHE_TTL_SEC,
    ) -> bool:
        """Mark nonce as used. Returns True on success, False on duplicate.

        Pre: nonce + author + sender_fingerprint non-empty.
        Post: future ``is_used(nonce)`` returns True for ttl_sec.
        """
        if not nonce or not author or not sender_fingerprint:
            raise ValueError(
                "nonce, author, sender_fingerprint must be non-empty"
            )
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")

        now = int(time.time())
        expires = now + ttl_sec
        with closing(sqlite3.connect(self.db_path)) as conn:
            try:
                conn.execute(
                    "INSERT INTO used_nonces "
                    "(nonce, author, sender_fingerprint, "
                    "consumed_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (nonce, author, sender_fingerprint, now, expires),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def verify_sender_binding(
        self,
        nonce: str,
        author: str,
        sender_fingerprint: str,
    ) -> bool:
        """Verify that nonce was issued for THIS sender.

        Pre: nonce previously stored via ``mark_used``.
        Post: True iff stored author+fingerprint match.
        """
        if not nonce:
            return False
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT author, sender_fingerprint "
                "FROM used_nonces WHERE nonce = ?",
                (nonce,),
            ).fetchone()
            if row is None:
                return False
            stored_author, stored_fp = row
            if stored_author != author:
                return False
            return hmac.compare_digest(stored_fp, sender_fingerprint)

    # ---------------- Vector-Clock layer ----------------

    def tick_lamport(self, author: str) -> VectorClock:
        """Inkrementiere Lamport-Clock fuer Author. Atomic.

        Pre: author non-empty.
        Post: returned VectorClock.lamport ist strikt monoton steigend.
        """
        if not author:
            raise ValueError("author must be non-empty")
        with self._lock:
            current = self._lamport_clocks.get(author, 0)
            new_lamport = current + 1
            self._lamport_clocks[author] = new_lamport
            return VectorClock(
                author=author,
                lamport=new_lamport,
                wall_clock_unix=int(time.time()),
            )

    def observe_remote_clock(self, remote: VectorClock) -> VectorClock:
        """Lamport-Receive: bump local clock to max(local, remote)+1.

        Pre: remote is VectorClock.
        Post: local lamport for remote.author >= remote.lamport+1.
        """
        with self._lock:
            current = self._lamport_clocks.get(remote.author, 0)
            new_lamport = max(current, remote.lamport) + 1
            self._lamport_clocks[remote.author] = new_lamport
            return VectorClock(
                author=remote.author,
                lamport=new_lamport,
                wall_clock_unix=int(time.time()),
            )

    # ---------------- Chain-Anchor (Truncation-Detection) ----------------

    def _sign_anchor(
        self,
        project_id: str,
        section_id: str,
        block_index: int,
        block_hash: str,
    ) -> str:
        msg = (
            f"{project_id}|{section_id}|{block_index}|{block_hash}"
        ).encode("utf-8")
        return hmac.new(
            self._secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()

    def update_chain_anchor(
        self,
        project_id: str,
        section_id: str,
        block_index: int,
        block_hash: str,
    ) -> str:
        """Speichere signiertes Tail-Anchor.

        Pre: project_id, section_id non-empty.
        Post: Anchor ueberschreibbar nur mit hoeherem block_index.
        """
        if not project_id or not section_id:
            raise ValueError(
                "project_id and section_id must be non-empty"
            )
        if block_index < 0:
            raise ValueError("block_index must be >= 0")

        sig = self._sign_anchor(
            project_id, section_id, block_index, block_hash
        )
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT last_block_index FROM chain_anchors "
                "WHERE project_id = ? AND section_id = ?",
                (project_id, section_id),
            ).fetchone()
            if row is not None and row[0] >= block_index:
                # Anti-Truncation: anchor only forward (reject lower index).
                stored_idx = row[0]
                if stored_idx > block_index:
                    raise ValueError(
                        f"anchor regression refused: stored "
                        f"{stored_idx}, attempted {block_index}"
                    )
            conn.execute(
                "INSERT OR REPLACE INTO chain_anchors "
                "(project_id, section_id, last_block_index, "
                "last_block_hash, anchor_signature, anchored_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    section_id,
                    block_index,
                    block_hash,
                    sig,
                    now,
                ),
            )
            conn.commit()
        return sig

    def verify_chain_against_anchor(
        self,
        project_id: str,
        section_id: str,
        actual_last_block_index: int,
        actual_last_block_hash: str,
    ) -> bool:
        """Detect Truncation: if anchor expects higher index than seen.

        Pre: project_id+section_id non-empty.
        Post:
            True if no anchor (no claim made),
            True if anchor matches exactly,
            False if anchor expects higher index (truncation suspected),
            False if anchor signature invalid.
        """
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT last_block_index, last_block_hash, "
                "anchor_signature FROM chain_anchors "
                "WHERE project_id = ? AND section_id = ?",
                (project_id, section_id),
            ).fetchone()
            if row is None:
                return True  # no anchor -> can't detect truncation
            stored_idx, stored_hash, stored_sig = row

        # Verify signature first (anti-tampering).
        expected_sig = self._sign_anchor(
            project_id, section_id, stored_idx, stored_hash
        )
        if not hmac.compare_digest(expected_sig, stored_sig):
            return False

        # Truncation-Check: actual must match anchor (or be ahead).
        if actual_last_block_index < stored_idx:
            return False  # truncation
        if (
            actual_last_block_index == stored_idx
            and actual_last_block_hash != stored_hash
        ):
            return False  # tampering at anchor point
        return True


# CRUX-MK
