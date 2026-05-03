"""KMO Outbox Consumer [CRUX-MK]

Idempotent Consumer mit SQLite-Backend fuer processed-event-IDs.
Liest Outbox-Files, ruft Handler, schreibt Ack oder bei 3 Fails Dead-Letter-Queue.

Pattern: Consumer-DB im machine-lokalen Application-Support-Ordner.
Cross-Machine-Idempotenz via shared event_id (UUID4).

Spec: branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md §P-KMO-A3
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kmo_outbox_producer import EventEnvelope, atomic_write_json


@dataclass
class ConsumerStats:
    """Stats pro poll_and_process-Run."""

    polled: int = 0
    processed: int = 0
    skipped_idempotent: int = 0
    failed: int = 0
    moved_to_dlq: int = 0
    errors: list[str] = field(default_factory=list)


class OutboxConsumer:
    """Idempotent Consumer mit SQLite-State.

    Pre: outbox_dir + ack_dir + dlq_dir muessen existieren (mkdir wenn nicht).
    Post: processed-events Table verhindert Doppel-Verarbeitung.
    """

    MAX_RETRIES = 3

    def __init__(
        self,
        consumer_id: str,
        outbox_dir: Path,
        ack_dir: Path,
        dlq_dir: Path,
        state_db: Path | None = None,
    ):
        self.consumer_id = consumer_id
        self.outbox_dir = Path(outbox_dir)
        self.ack_dir = Path(ack_dir)
        self.dlq_dir = Path(dlq_dir)
        for d in (self.outbox_dir, self.ack_dir, self.dlq_dir):
            d.mkdir(parents=True, exist_ok=True)

        if state_db is None:
            state_db = (
                Path.home()
                / "Library"
                / "Application Support"
                / "kmo"
                / f"consumer-{consumer_id}.db"
            )
        self.state_db = Path(state_db)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        self._handlers: dict[str, Callable[[EventEnvelope], None]] = {}
        self._subscribed_topics: set[str] = set()

    def _init_db(self) -> None:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS processed_events (
                    event_id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    processed_at REAL NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_topic ON processed_events(topic)"
            )
            conn.commit()

    def subscribe(
        self, topics: list[str], handler_func: Callable[[EventEnvelope], None]
    ) -> None:
        """Registriert Handler fuer Topics.

        Pre: handler_func raises Exception bei Fehler (wird zu retry_count++).
        Post: poll_and_process() ruft handler_func fuer alle Events der Topics.
        """
        for topic in topics:
            self._handlers[topic] = handler_func
            self._subscribed_topics.add(topic)

    def _is_processed(self, event_id: str) -> bool:
        # Only events SUCCESSFULLY processed count as "idempotent-skip" candidates.
        # Failed attempts (last_error IS NOT NULL) are retry-eligible until DLQ.
        with sqlite3.connect(self.state_db) as conn:
            cur = conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id = ? AND last_error IS NULL",
                (event_id,),
            )
            return cur.fetchone() is not None

    def _get_retry_count(self, event_id: str) -> int:
        with sqlite3.connect(self.state_db) as conn:
            cur = conn.execute(
                "SELECT retry_count FROM processed_events WHERE event_id = ?",
                (event_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def _record_attempt(
        self,
        event: EventEnvelope,
        success: bool,
        error: str | None = None,
        retry_count: int = 0,
    ) -> None:
        with sqlite3.connect(self.state_db) as conn:
            if success:
                conn.execute(
                    """INSERT OR REPLACE INTO processed_events
                       (event_id, machine_id, topic, seq, processed_at, retry_count, last_error)
                       VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        event.event_id,
                        event.machine_id,
                        event.topic,
                        event.seq,
                        time.time(),
                        retry_count,
                    ),
                )
            else:
                conn.execute(
                    """INSERT OR REPLACE INTO processed_events
                       (event_id, machine_id, topic, seq, processed_at, retry_count, last_error)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.event_id,
                        event.machine_id,
                        event.topic,
                        event.seq,
                        time.time(),
                        retry_count,
                        error,
                    ),
                )
            conn.commit()

    def acknowledge(self, event_id: str) -> Path:
        """Schreibt Ack-File fuer Event in ack_dir."""
        with sqlite3.connect(self.state_db) as conn:
            cur = conn.execute(
                """SELECT machine_id, topic, seq FROM processed_events
                   WHERE event_id = ?""",
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"event_id {event_id} not in processed_events")
            machine_id, topic, seq = row
        ack_name = f"{machine_id}-{topic}-{seq:08d}.ack.json"
        ack_path = self.ack_dir / ack_name
        ack_data = {
            "event_id": event_id,
            "consumer_id": self.consumer_id,
            "acked_at": time.time(),
        }
        atomic_write_json(ack_path, ack_data)
        return ack_path

    def move_to_dlq(self, event_id: str, reason: str) -> Path | None:
        """Verschiebt Event nach 3 Fails in DLQ.

        Sucht Outbox-File via processed_events-Lookup.
        DLQ-File enthaelt: Original-Envelope + reason + retry_count + final_failed_at.
        """
        with sqlite3.connect(self.state_db) as conn:
            cur = conn.execute(
                """SELECT machine_id, topic, seq, retry_count FROM processed_events
                   WHERE event_id = ?""",
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            machine_id, topic, seq, retry_count = row

        outbox_name = f"{machine_id}-{topic}-{seq:08d}.json"
        outbox_path = self.outbox_dir / outbox_name
        if not outbox_path.exists():
            return None

        with open(outbox_path, "r", encoding="utf-8") as f:
            envelope_data = json.load(f)

        dlq_name = f"{machine_id}-{topic}-{seq:08d}.dlq.json"
        dlq_path = self.dlq_dir / dlq_name
        dlq_data = {
            "envelope": envelope_data,
            "reason": reason,
            "retry_count": retry_count,
            "final_failed_at": time.time(),
            "consumer_id": self.consumer_id,
        }
        atomic_write_json(dlq_path, dlq_data)
        return dlq_path

    def poll_and_process(self) -> ConsumerStats:
        """Pollt Outbox einmal, verarbeitet alle subscribed-Topic-Events.

        Pre: subscribe() wurde mind. 1x aufgerufen.
        Post: ConsumerStats reflektieren Run-Resultat. Idempotent: bereits
              verarbeitete Events werden geskippt (skipped_idempotent counter).
        """
        stats = ConsumerStats()
        if not self.outbox_dir.exists():
            return stats

        for outbox_file in sorted(self.outbox_dir.glob("*.json")):
            if outbox_file.name.startswith(".tmp-"):
                continue
            stats.polled += 1
            try:
                with open(outbox_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                event = EventEnvelope.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                stats.errors.append(f"parse-error {outbox_file.name}: {e}")
                continue

            if event.topic not in self._subscribed_topics:
                continue

            if self._is_processed(event.event_id):
                stats.skipped_idempotent += 1
                continue

            handler = self._handlers.get(event.topic)
            if handler is None:
                continue

            current_retry = self._get_retry_count(event.event_id)
            try:
                handler(event)
                self._record_attempt(event, success=True, retry_count=current_retry)
                self.acknowledge(event.event_id)
                stats.processed += 1
            except Exception as e:
                new_retry = current_retry + 1
                self._record_attempt(
                    event, success=False, error=str(e), retry_count=new_retry
                )
                stats.failed += 1
                stats.errors.append(f"{event.event_id}: {e}")
                if new_retry >= self.MAX_RETRIES:
                    self.move_to_dlq(
                        event.event_id, f"max-retries ({new_retry}): {e}"
                    )
                    stats.moved_to_dlq += 1
        return stats


# [CRUX-MK]
