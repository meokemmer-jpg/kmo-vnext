"""KMO Outbox Producer [CRUX-MK]

Durable Dispatch-Queue: Producer schreibt Events atomar in branch-hub/outbox/.
Cross-Machine (Mac/Windows/Mobile) via Drive-Sync. Idempotent via event_id (UUID).

Pattern: Outbox-File pro Event, atomic-write (tempfile + os.replace).
Sequenznummer monotonic per (machine_id, topic) via SQLite-Counter.

Spec: branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md §P-KMO-A3
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class EventEnvelope:
    """Event-Envelope fuer Outbox-Pattern.

    Pre-Conditions: machine_id non-empty, topic non-empty, payload JSON-serializable.
    Post-Conditions: event_id ist UUID4-string, seq monotonic per (machine, topic).
    """

    event_id: str
    machine_id: str
    topic: str
    seq: int
    timestamp: float
    payload: dict
    retry_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EventEnvelope":
        return cls(**d)

    def filename(self) -> str:
        """Pflicht-Format: <machine>-<topic>-<seq>.json (zero-padded seq)."""
        return f"{self.machine_id}-{self.topic}-{self.seq:08d}.json"


def atomic_write_json(target: Path, data: dict) -> None:
    """Atomic-Write: tempfile in gleichem dir + os.replace.

    Verhindert partial-writes bei Drive-Sync-Race oder Crash mid-write.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


class OutboxProducer:
    """Producer-Klasse fuer Outbox-Pattern.

    Verwaltet Sequenz-Counter pro (machine_id, topic) via SQLite.
    Schreibt Events atomar in outbox_dir.
    """

    def __init__(
        self,
        outbox_dir: Path,
        ack_dir: Path,
        machine_id: str,
        state_db: Path | None = None,
    ):
        self.outbox_dir = Path(outbox_dir)
        self.ack_dir = Path(ack_dir)
        self.machine_id = machine_id
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.ack_dir.mkdir(parents=True, exist_ok=True)

        if state_db is None:
            state_db = Path.home() / "Library" / "Application Support" / "kmo" / f"producer-{machine_id}.db"
        self.state_db = Path(state_db)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS seq_counter (
                    machine_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (machine_id, topic)
                )"""
            )
            conn.commit()

    def _next_seq(self, topic: str) -> int:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO seq_counter (machine_id, topic, last_seq)
                   VALUES (?, ?, 0)""",
                (self.machine_id, topic),
            )
            conn.execute(
                """UPDATE seq_counter SET last_seq = last_seq + 1
                   WHERE machine_id = ? AND topic = ?""",
                (self.machine_id, topic),
            )
            cur = conn.execute(
                "SELECT last_seq FROM seq_counter WHERE machine_id = ? AND topic = ?",
                (self.machine_id, topic),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row[0])

    def publish(
        self, machine_id: str, topic: str, payload: dict, event_id: str | None = None
    ) -> EventEnvelope:
        """Publiziert Event in Outbox.

        Pre: machine_id == self.machine_id (Producer schreibt nur eigene Events).
        Post: File <machine>-<topic>-<seq>.json existiert in outbox_dir, atomar.
        Idempotenz: gleiche event_id -> gleiche Datei (overwrite), Consumer dedupliziert.
        """
        if machine_id != self.machine_id:
            raise ValueError(
                f"Producer machine_id mismatch: {machine_id} != {self.machine_id}"
            )
        if not topic:
            raise ValueError("topic must be non-empty")

        event = EventEnvelope(
            event_id=event_id or str(uuid.uuid4()),
            machine_id=machine_id,
            topic=topic,
            seq=self._next_seq(topic),
            timestamp=time.time(),
            payload=payload,
            retry_count=0,
        )
        target = self.outbox_dir / event.filename()
        atomic_write_json(target, event.to_dict())
        return event

    def republish_failed_acks(self) -> list[EventEnvelope]:
        """Re-publiziert Events ohne Ack nach TTL (z.B. Sync-Lost).

        Scant outbox_dir gegen ack_dir: was schreibt aber kein Ack hat,
        bekommt retry_count++ und wird neu publiziert (selbe Datei, neuer ts).
        """
        republished: list[EventEnvelope] = []
        if not self.outbox_dir.exists():
            return republished
        for outbox_file in sorted(self.outbox_dir.glob(f"{self.machine_id}-*.json")):
            ack_file = self.ack_dir / outbox_file.name.replace(".json", ".ack.json")
            if ack_file.exists():
                continue
            try:
                with open(outbox_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                event = EventEnvelope.from_dict(data)
                event.retry_count += 1
                event.timestamp = time.time()
                atomic_write_json(outbox_file, event.to_dict())
                republished.append(event)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return republished


# [CRUX-MK]
