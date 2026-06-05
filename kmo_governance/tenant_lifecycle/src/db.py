# Tenant-DB SQLite-Adapter [CRUX-MK]
"""
SQLite-State fuer Tenant-Lifecycle.

Append-only-Disziplin: jede Status-Transition erzeugt neuen Audit-Eintrag.
Idempotenz via record_hash + UNIQUE-Constraint.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from .tenant import Tenant, TenantStatus, PlanTier, canonical_record_hash


SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plan_tier TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    suspended_at TEXT,
    decommissioned_at TEXT,
    archived_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    record_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenant_status ON tenants(status);
CREATE INDEX IF NOT EXISTS idx_tenant_plan ON tenants(plan_tier);

CREATE TABLE IF NOT EXISTS tenant_lifecycle_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    transitioned_at TEXT NOT NULL,
    reason TEXT,
    record_hash TEXT NOT NULL,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id)
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_tenant ON tenant_lifecycle_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_lifecycle_time ON tenant_lifecycle_events(transitioned_at);
"""

DB_DEFAULT = Path.home() / ".kmo-governance" / "tenant-lifecycle.db"
JSONL_BACKUP_DEFAULT = Path.home() / ".kmo-governance" / "tenant-events.jsonl"


class TenantDB:
    """SQLite-Adapter fuer Tenant-Lifecycle (LC4 state-externalization)."""

    def __init__(self, db_path: Path | str | None = None,
                 jsonl_backup: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DB_DEFAULT
        self.jsonl_backup = Path(jsonl_backup) if jsonl_backup else JSONL_BACKUP_DEFAULT
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_backup.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(SCHEMA_DDL)
            conn.commit()

    def _append_jsonl(self, record: dict[str, Any]) -> None:
        """LC2 Direct-Mode: jsonl-Backup pro Write."""
        with open(self.jsonl_backup, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def upsert_tenant(self, tenant: Tenant) -> str:
        """Idempotenter Upsert. Gibt record_hash zurueck."""
        record = tenant.to_dict()
        record_hash = canonical_record_hash(record)
        record["record_hash"] = record_hash

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """INSERT INTO tenants
                (id, name, plan_tier, status, created_at, activated_at,
                 suspended_at, decommissioned_at, archived_at, metadata,
                 record_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    activated_at=excluded.activated_at,
                    suspended_at=excluded.suspended_at,
                    decommissioned_at=excluded.decommissioned_at,
                    archived_at=excluded.archived_at,
                    metadata=excluded.metadata,
                    record_hash=excluded.record_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    str(tenant.id), tenant.name, tenant.plan_tier.value,
                    tenant.status.value, record["created_at"], record["activated_at"],
                    record["suspended_at"], record["decommissioned_at"],
                    record["archived_at"], json.dumps(tenant.metadata),
                    record_hash, datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        self._append_jsonl({"event": "upsert", **record})
        return record_hash

    def log_transition(self, tenant_id: UUID | str, from_status: TenantStatus | str,
                       to_status: TenantStatus | str, reason: str = "") -> int:
        """Append-only-Lifecycle-Event."""
        if isinstance(tenant_id, UUID):
            tenant_id = str(tenant_id)
        if isinstance(from_status, TenantStatus):
            from_status = from_status.value
        if isinstance(to_status, TenantStatus):
            to_status = to_status.value
        ts = datetime.now(timezone.utc).isoformat()
        event = {
            "tenant_id": tenant_id, "from_status": from_status,
            "to_status": to_status, "transitioned_at": ts, "reason": reason,
        }
        record_hash = canonical_record_hash(event)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                """INSERT INTO tenant_lifecycle_events
                (tenant_id, from_status, to_status, transitioned_at, reason, record_hash)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (tenant_id, from_status, to_status, ts, reason, record_hash),
            )
            conn.commit()
            event_id = cur.lastrowid or 0
        self._append_jsonl({"event": "transition", "event_id": event_id, **event,
                            "record_hash": record_hash})
        return event_id

    def get_tenant(self, tenant_id: UUID | str) -> dict[str, Any] | None:
        if isinstance(tenant_id, UUID):
            tenant_id = str(tenant_id)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_tenants(self, status: TenantStatus | str | None = None) -> list[dict[str, Any]]:
        if isinstance(status, TenantStatus):
            status = status.value
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM tenants WHERE status = ? ORDER BY created_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tenants ORDER BY created_at"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_lifecycle_events(self, tenant_id: UUID | str) -> list[dict[str, Any]]:
        if isinstance(tenant_id, UUID):
            tenant_id = str(tenant_id)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM tenant_lifecycle_events
                WHERE tenant_id = ? ORDER BY transitioned_at""",
                (tenant_id,),
            ).fetchall()
            return [dict(r) for r in rows]
