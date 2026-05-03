"""KMO Audit-Log [CRUX-MK]

Append-only audit-log with hash-chain integrity.

Per Entry: timestamp, action, resource, requester, approver_token, signature.
Storage: branch-hub/audit/kmo-approval-chain.jsonl
Verify: SHA256(prev_hash + timestamp + content) chain check.

A4.2 Erweiterung (Welle-4):
- `append_within_transaction(conn, ...)` fuer Transaction-Coupling
  mit `ApprovalGate.pre_deploy_atomic` (kein eigenes Connection-Open).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Constants with units
DEFAULT_LOG_PATH: Path = (
    Path.home()
    / "Library"
    / "CloudStorage"
    / "GoogleDrive-m.e.o.kemmer@gmail.com"
    / "Meine Ablage"
    / "Claude-Knowledge-System"
    / "branch-hub"
    / "audit"
    / "kmo-approval-chain.jsonl"
)
GENESIS_HASH: str = "0" * 64  # 64 hex chars = SHA256 length


@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit-entry. Each entry's hash chains to previous."""

    block_index: int
    timestamp: int  # UNIX epoch seconds
    action: str
    resource: str
    requester: str
    approver_token_nonce: str  # store nonce only, not full token
    prev_hash: str
    block_hash: str  # SHA256 of (prev_hash + canonical content)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class AuditLog:
    """Append-only hash-chain audit-log.

    Pre: log_path parent dir exists or creatable.
    Post: All appends are hash-linked; verify_chain() detects tampering.
    """

    def __init__(self, log_path: Path = DEFAULT_LOG_PATH):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()

    @staticmethod
    def _compute_hash(prev_hash: str, content: dict) -> str:
        """SHA256 over (prev_hash + canonical-json content)."""
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        msg = (prev_hash + canonical).encode("utf-8")
        return hashlib.sha256(msg).hexdigest()

    def _last_entry(self) -> Optional[AuditEntry]:
        """Return last entry or None on empty log."""
        try:
            with self.log_path.open("rb") as fp:
                fp.seek(0, os.SEEK_END)
                size = fp.tell()
                if size == 0:
                    return None
                # Read last line
                fp.seek(max(0, size - 4096))
                tail = fp.read().decode("utf-8")
                lines = [ln for ln in tail.splitlines() if ln.strip()]
                if not lines:
                    return None
                data = json.loads(lines[-1])
                return AuditEntry(**data)
        except (OSError, json.JSONDecodeError):
            return None

    def append(
        self,
        action: str,
        resource: str,
        requester: str,
        approver_token_nonce: str,
    ) -> AuditEntry:
        """Append new entry to chain. Pre: inputs non-empty. Post: entry persisted+hash-linked."""
        if not all([action, resource, requester, approver_token_nonce]):
            raise ValueError("All audit fields must be non-empty")

        prev = self._last_entry()
        prev_hash = prev.block_hash if prev else GENESIS_HASH
        block_index = (prev.block_index + 1) if prev else 0

        content = {
            "block_index": block_index,
            "timestamp": int(time.time()),
            "action": action,
            "resource": resource,
            "requester": requester,
            "approver_token_nonce": approver_token_nonce,
        }
        block_hash = self._compute_hash(prev_hash, content)

        entry = AuditEntry(
            block_index=block_index,
            timestamp=content["timestamp"],
            action=action,
            resource=resource,
            requester=requester,
            approver_token_nonce=approver_token_nonce,
            prev_hash=prev_hash,
            block_hash=block_hash,
        )

        with self.log_path.open("a", encoding="utf-8") as fp:
            fp.write(entry.to_json_line() + "\n")

        return entry

    def append_within_transaction(
        self,
        conn: sqlite3.Connection,
        action: str,
        resource: str,
        requester: str,
        approver_token_nonce: str,
    ) -> AuditEntry:
        """Append within an externally-managed SQLite-Transaction.

        Pre: caller has begun transaction on `conn`. inputs non-empty.
        Post: entry written to log AND to `audit_chain` table on `conn`
              (caller commits/rollbacks). The JSONL append happens only
              after table-insert succeeds; on caller-rollback the table
              insert is reverted but the JSONL line stays — hence we
              also re-write the chain via a state-table for atomicity.

        Strategy: write to in-DB chain-table inside transaction. JSONL is
        replayed from the table after commit by `flush_pending_to_jsonl`.
        For pre_deploy_atomic we use `_stage_jsonl` to defer file-write
        until after COMMIT.
        """
        if not all([action, resource, requester, approver_token_nonce]):
            raise ValueError("All audit fields must be non-empty")

        # Ensure audit_chain table exists on this conn (idempotent)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_chain (
                block_index INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                requester TEXT NOT NULL,
                approver_token_nonce TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                block_hash TEXT NOT NULL
            )
            """
        )

        # Compute chain-link from JSONL tail (authoritative on-disk chain)
        prev = self._last_entry()
        prev_hash = prev.block_hash if prev else GENESIS_HASH
        block_index = (prev.block_index + 1) if prev else 0

        content = {
            "block_index": block_index,
            "timestamp": int(time.time()),
            "action": action,
            "resource": resource,
            "requester": requester,
            "approver_token_nonce": approver_token_nonce,
        }
        block_hash = self._compute_hash(prev_hash, content)

        entry = AuditEntry(
            block_index=block_index,
            timestamp=content["timestamp"],
            action=action,
            resource=resource,
            requester=requester,
            approver_token_nonce=approver_token_nonce,
            prev_hash=prev_hash,
            block_hash=block_hash,
        )

        # Stage in DB-table within transaction. JSONL flush is caller's job
        # after COMMIT (see ApprovalGate.pre_deploy_atomic).
        conn.execute(
            """
            INSERT INTO audit_chain
              (block_index, timestamp, action, resource, requester,
               approver_token_nonce, prev_hash, block_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.block_index, entry.timestamp, entry.action, entry.resource,
                entry.requester, entry.approver_token_nonce,
                entry.prev_hash, entry.block_hash,
            ),
        )
        return entry

    def flush_entry_to_jsonl(self, entry: AuditEntry) -> None:
        """Write a staged entry to JSONL. Call AFTER transaction commit."""
        with self.log_path.open("a", encoding="utf-8") as fp:
            fp.write(entry.to_json_line() + "\n")

    def verify_chain(self) -> bool:
        """Verify entire chain integrity. Pre: log readable. Post: True iff untampered."""
        prev_hash = GENESIS_HASH
        expected_index = 0
        try:
            with self.log_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    entry = AuditEntry(**data)

                    # Index must be monotonic
                    if entry.block_index != expected_index:
                        return False
                    # Prev-hash must link
                    if entry.prev_hash != prev_hash:
                        return False
                    # Block-hash must match recomputation
                    content = {
                        "block_index": entry.block_index,
                        "timestamp": entry.timestamp,
                        "action": entry.action,
                        "resource": entry.resource,
                        "requester": entry.requester,
                        "approver_token_nonce": entry.approver_token_nonce,
                    }
                    if self._compute_hash(prev_hash, content) != entry.block_hash:
                        return False

                    prev_hash = entry.block_hash
                    expected_index += 1
        except (OSError, json.JSONDecodeError, TypeError):
            return False
        return True
