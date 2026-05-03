"""KMO Stigmergic Blackboard Store [CRUX-MK].

Welle-9β Phase-2 Modul 2.2: Append-Only Cross-DF Event-Store + Stigmergy-Writer.

Bio-Aequivalent: Stigmergie (Pierre-Paul Grassé 1959). Termiten-Bauten via lokale
Bauzustand-Modifikationen ohne zentrale Koordination. Pheromone-Trails als
persistente Umwelt-Modifikation. Reinforcement bei erfolgreicher Nutzung.

Anorg-Mapping (Welle-9.1b): A-23 Blackboard-Architecture (Hayes-Roth 1985).

Schema:
    blackboard_events (
        event_id TEXT PRIMARY KEY,         -- UUID4
        tissue_id TEXT NOT NULL,           -- Row-Level-Security
        topic TEXT NOT NULL,               -- subscription channel
        written_by_df TEXT NOT NULL,
        payload_json TEXT,
        created_at REAL NOT NULL,
        ttl_until REAL,                    -- NULL = no expiry
        machine_id TEXT NOT NULL,
        monotonic_seq INTEGER NOT NULL     -- per-tissue monotonic
    )

K12 Distillation-Resistenz: payload_json + machine_id Provenance.
K13 Independent-Ground-Truth: SQLite-WAL extern + tissue-RLS.
LC4 Failure-Isolation: append-only + UUID-idempotent.

Stigmergy-Strength formula:
    S(path) = Σ_i exp(-λ * (now - t_i)) * reinforcement_i
"""

from __future__ import annotations

import json
import math
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
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "blackboard.db"
DEFAULT_DECAY_LAMBDA: float = 0.01  # 1/sec slower than quorum (longer-lived trails)


@dataclass(frozen=True)
class BlackboardEvent:
    event_id: str
    tissue_id: str
    topic: str
    written_by_df: str
    payload: Any
    created_at: float
    ttl_until: Optional[float]
    machine_id: str
    monotonic_seq: int


class BlackboardStore:
    """Append-Only SQLite-WAL Event-Store with stigmergy + cross-machine consistency.

    Pre-Conditions:
        - SQLite >= 3.7 (WAL)
        - Write access to db_path parent
        - No UPDATE/DELETE on events outside purge_tissue + gc_expired
    Post-Conditions:
        - append() is atomic + idempotent (UUID PRIMARY KEY)
        - read_since() returns events newer than monotonic_seq
        - reinforce() appends a *new* event (no in-place edit), making strength compound
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        machine_id: Optional[str] = None,
        decay_lambda: float = DEFAULT_DECAY_LAMBDA,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.machine_id = machine_id or socket.gethostname()
        self.decay_lambda = float(decay_lambda)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS blackboard_events (
                    event_id TEXT PRIMARY KEY,
                    tissue_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    written_by_df TEXT NOT NULL,
                    payload_json TEXT,
                    created_at REAL NOT NULL,
                    ttl_until REAL,
                    machine_id TEXT NOT NULL,
                    monotonic_seq INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_bb_tissue_seq_unique
                    ON blackboard_events (tissue_id, monotonic_seq);
                CREATE INDEX IF NOT EXISTS idx_bb_topic
                    ON blackboard_events (tissue_id, topic, monotonic_seq);
                CREATE INDEX IF NOT EXISTS idx_bb_ttl
                    ON blackboard_events (ttl_until);
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
        tissue_id: str,
        topic: str,
        written_by_df: str,
        payload: Any = None,
        ttl_sec: Optional[float] = None,
    ) -> str:
        """Atomically append an event. Returns event_id (UUID). Append-only: no UPDATE."""
        if not tissue_id or not topic or not written_by_df:
            raise ValueError("tissue_id, topic, written_by_df required")
        event_id = str(uuid.uuid4())
        now = time.time()
        ttl_until = (now + float(ttl_sec)) if ttl_sec is not None else None
        payload_json = json.dumps(payload, default=str) if payload is not None else None
        # Patch C2 (Copilot-Finding): BEGIN IMMEDIATE for atomic SELECT MAX + INSERT.
        # Without this: race-condition where two processes get same monotonic_seq.
        # UNIQUE-Index on (tissue_id, monotonic_seq) is safety-net (raises IntegrityError on conflict).
        with self._lock, self._connect() as conn:
            for attempt in range(3):  # retry up to 3 times on UNIQUE-Conflict
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    seq = self._next_seq(conn, tissue_id)
                    conn.execute(
                        """
                        INSERT INTO blackboard_events
                        (event_id, tissue_id, topic, written_by_df, payload_json,
                         created_at, ttl_until, machine_id, monotonic_seq)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (event_id, tissue_id, topic, written_by_df, payload_json,
                         now, ttl_until, self.machine_id, seq),
                    )
                    conn.execute("COMMIT")
                    return event_id
                except sqlite3.IntegrityError:
                    # Concurrent writer claimed this seq; rollback and retry
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.OperationalError:
                        pass
                    if attempt == 2:
                        raise
                    continue
        # Unreachable, but mypy
        return event_id

    def reinforce(
        self,
        tissue_id: str,
        topic: str,
        written_by_df: str,
        original_event_id: str,
    ) -> str:
        """Reinforce a previous trail by appending a new 'reinforcement' event.

        Stigmergy: strength compounds via additional events (no in-place edit).
        Returns new event_id of the reinforcement record.
        """
        return self.append(
            tissue_id=tissue_id,
            topic=topic,
            written_by_df=written_by_df,
            payload={"reinforcement_of": original_event_id},
        )

    def read_since(
        self,
        tissue_id: str,
        since_seq: int = 0,
        topic: Optional[str] = None,
        limit: int = 1000,
    ) -> List[BlackboardEvent]:
        """Read events for tissue with monotonic_seq > since_seq. Optional topic filter."""
        if not tissue_id:
            raise ValueError("tissue_id required")
        sql = (
            "SELECT * FROM blackboard_events "
            "WHERE tissue_id = ? AND monotonic_seq > ?"
        )
        params: list[Any] = [tissue_id, int(since_seq)]
        if topic is not None:
            sql += " AND topic = ?"
            params.append(topic)
        sql += " ORDER BY monotonic_seq ASC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_event(r) for r in rows]

    def stigmergy_strength(
        self,
        tissue_id: str,
        topic: str,
        now: Optional[float] = None,
    ) -> float:
        """S(path) = Σ_i exp(-λ * (now - t_i)) over all events on (tissue, topic).

        Reinforcement events count as additional contributions, so trails strengthen
        with successful reuse and decay over time when not reinforced.
        """
        t_now = now if now is not None else time.time()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at FROM blackboard_events
                WHERE tissue_id = ? AND topic = ?
                """,
                (tissue_id, topic),
            ).fetchall()
            return sum(
                math.exp(-self.decay_lambda * max(0.0, t_now - r["created_at"]))
                for r in rows
            )

    def gc_expired(self, now: Optional[float] = None) -> int:
        """Garbage-collect events whose ttl_until is in the past."""
        t_now = now if now is not None else time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM blackboard_events WHERE ttl_until IS NOT NULL AND ttl_until < ?",
                (t_now,),
            )
            conn.commit()
            return int(cur.rowcount)

    def purge_tissue(self, tissue_id: str) -> int:
        """GDPR cascade-delete all events for a tissue."""
        if not tissue_id:
            raise ValueError("tissue_id required")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM blackboard_events WHERE tissue_id = ?",
                (tissue_id,),
            )
            conn.commit()
            return int(cur.rowcount)

    def count_for_tissue(self, tissue_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM blackboard_events WHERE tissue_id = ?",
                (tissue_id,),
            ).fetchone()
            return int(row["n"]) if row else 0

    # ---------------- Internals ----------------

    def _next_seq(self, conn: sqlite3.Connection, tissue_id: str) -> int:
        row = conn.execute(
            "SELECT MAX(monotonic_seq) AS m FROM blackboard_events WHERE tissue_id = ?",
            (tissue_id,),
        ).fetchone()
        m = row["m"] if row and row["m"] is not None else 0
        return int(m) + 1

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> BlackboardEvent:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else None
        return BlackboardEvent(
            event_id=row["event_id"],
            tissue_id=row["tissue_id"],
            topic=row["topic"],
            written_by_df=row["written_by_df"],
            payload=payload,
            created_at=row["created_at"],
            ttl_until=row["ttl_until"],
            machine_id=row["machine_id"],
            monotonic_seq=int(row["monotonic_seq"]),
        )


# CRUX-MK
