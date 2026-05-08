"""Graphity Audit-Persister [CRUX-MK]

Edit-History per Section per Author mit Hash-Chain-Integrity (analog
kmo_audit_log.py Synaptic-LTP-Pattern).

Bio-Pattern-Korrespondenz:
- Hash-Chain     = Synaptic-Long-Term-Memory (jeder Edit verlinkt zum vorherigen)
- Edit-Entry     = Single-Memory-Trace
- Genesis-Hash   = Initial-Synaptic-State
- Verify-Chain   = Memory-Consolidation-Check

CRUX-Bindung:
- Q_0: Edit-History ist tamper-evident
- I_min: append-only Hash-Chain
- W_0: SHA256-Pattern wiederverwendet aus kmo_audit_log
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

# Constants with units
DEFAULT_HISTORY_PATH: Path = (
    Path.home() / ".graphity" / "edit_history.jsonl"
)
GENESIS_HASH: str = "0" * 64  # SHA256 length

EditAction = str  # "lock_acquire" | "lock_release" | "edit_commit" |
# "merge_resolve" | "force_release"


@dataclass(frozen=True)
class EditHistoryEntry:
    """Immutable Edit-History-Entry mit Hash-Chain.

    Pre: alle Felder non-empty (ausser content_hash).
    Post: block_hash = SHA256(prev_hash + canonical-content).
    """

    block_index: int
    timestamp: int  # UNIX epoch
    project_id: str
    section_id: str
    author: str
    action: EditAction
    content_hash: str  # SHA256 of edit-content (oder Lock-Token-Nonce)
    metadata: str  # JSON-string with extra info (z.B. Resolution-Strategy)
    prev_hash: str
    block_hash: str

    def to_json_line(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":")
        )


class GraphityAuditPersister:
    """Append-only Edit-History mit Hash-Chain-Integrity.

    Pre: history_path parent dir exists or creatable.
    Post: alle Eintraege Hash-verlinkt, verify_chain() erkennt Tampering.
    """

    def __init__(self, history_path: Path = DEFAULT_HISTORY_PATH):
        self.history_path = history_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            self.history_path.touch()

    @staticmethod
    def _compute_hash(prev_hash: str, content: dict) -> str:
        canonical = json.dumps(
            content, sort_keys=True, separators=(",", ":")
        )
        msg = (prev_hash + canonical).encode("utf-8")
        return hashlib.sha256(msg).hexdigest()

    @staticmethod
    def _hash_content(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _last_entry(self) -> Optional[EditHistoryEntry]:
        """Read last entry by streaming from end (efficient for large logs)."""
        try:
            with self.history_path.open("rb") as fp:
                fp.seek(0, 2)
                size = fp.tell()
                if size == 0:
                    return None
                # Read tail
                fp.seek(max(0, size - 4096))
                tail = fp.read().decode("utf-8")
                lines = [ln for ln in tail.splitlines() if ln.strip()]
                if not lines:
                    return None
                data = json.loads(lines[-1])
                return EditHistoryEntry(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def append_lock_acquire(
        self,
        project_id: str,
        section_id: str,
        author: str,
        nonce: str,
    ) -> EditHistoryEntry:
        """Audit Lock-Acquire (Synaptic-Vesikel-Release-Event)."""
        return self._append_entry(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="lock_acquire",
            content_hash=self._hash_content(nonce),
            metadata=json.dumps({"nonce_prefix": nonce[:16]}),
        )

    def append_lock_release(
        self,
        project_id: str,
        section_id: str,
        author: str,
        nonce: str,
        release_type: str = "normal",
    ) -> EditHistoryEntry:
        """Audit Lock-Release (Neurotransmitter-Reuptake-Event)."""
        return self._append_entry(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="lock_release",
            content_hash=self._hash_content(nonce),
            metadata=json.dumps(
                {
                    "nonce_prefix": nonce[:16],
                    "release_type": release_type,
                }
            ),
        )

    def append_edit_commit(
        self,
        project_id: str,
        section_id: str,
        author: str,
        edit_content: str,
        word_count: Optional[int] = None,
    ) -> EditHistoryEntry:
        """Audit erfolgreichen Edit-Commit."""
        meta: dict = {}
        if word_count is not None:
            meta["word_count"] = word_count
        return self._append_entry(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="edit_commit",
            content_hash=self._hash_content(edit_content),
            metadata=json.dumps(meta),
        )

    def append_merge_resolve(
        self,
        project_id: str,
        section_id: str,
        author: str,
        merged_content: str,
        resolution_strategy: str,
        conflict_count: int = 0,
    ) -> EditHistoryEntry:
        """Audit Merge-Resolution (post-Three-Way-Merge)."""
        meta = json.dumps(
            {
                "resolution": resolution_strategy,
                "conflict_count": conflict_count,
            }
        )
        return self._append_entry(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="merge_resolve",
            content_hash=self._hash_content(merged_content),
            metadata=meta,
        )

    def _append_entry(
        self,
        project_id: str,
        section_id: str,
        author: str,
        action: EditAction,
        content_hash: str,
        metadata: str,
    ) -> EditHistoryEntry:
        """Generic append with hash-chain link."""
        if not all([project_id, section_id, author, action]):
            raise ValueError(
                "project_id, section_id, author, action must be non-empty"
            )

        prev = self._last_entry()
        prev_hash = prev.block_hash if prev else GENESIS_HASH
        block_index = (prev.block_index + 1) if prev else 0

        content = {
            "block_index": block_index,
            "timestamp": int(time.time()),
            "project_id": project_id,
            "section_id": section_id,
            "author": author,
            "action": action,
            "content_hash": content_hash,
            "metadata": metadata,
        }
        block_hash = self._compute_hash(prev_hash, content)

        entry = EditHistoryEntry(
            block_index=block_index,
            timestamp=content["timestamp"],
            project_id=project_id,
            section_id=section_id,
            author=author,
            action=action,
            content_hash=content_hash,
            metadata=metadata,
            prev_hash=prev_hash,
            block_hash=block_hash,
        )

        with self.history_path.open("a", encoding="utf-8") as fp:
            fp.write(entry.to_json_line() + "\n")
        return entry

    def verify_chain(self) -> bool:
        """Verify entire chain integrity. Pre: log readable. Post: True iff untampered."""
        prev_hash = GENESIS_HASH
        expected_index = 0
        try:
            with self.history_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    entry = EditHistoryEntry(**data)

                    if entry.block_index != expected_index:
                        return False
                    if entry.prev_hash != prev_hash:
                        return False

                    content = {
                        "block_index": entry.block_index,
                        "timestamp": entry.timestamp,
                        "project_id": entry.project_id,
                        "section_id": entry.section_id,
                        "author": entry.author,
                        "action": entry.action,
                        "content_hash": entry.content_hash,
                        "metadata": entry.metadata,
                    }
                    if (
                        self._compute_hash(prev_hash, content)
                        != entry.block_hash
                    ):
                        return False

                    prev_hash = entry.block_hash
                    expected_index += 1
        except (OSError, json.JSONDecodeError, TypeError):
            return False
        return True

    def history_for_section(
        self, project_id: str, section_id: str
    ) -> Iterator[EditHistoryEntry]:
        """Stream history-entries for a specific section."""
        try:
            with self.history_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    entry = EditHistoryEntry(**data)
                    if (
                        entry.project_id == project_id
                        and entry.section_id == section_id
                    ):
                        yield entry
        except (OSError, json.JSONDecodeError, TypeError):
            return

    def history_for_author(
        self, author: str
    ) -> Iterator[EditHistoryEntry]:
        """Stream history-entries by author."""
        try:
            with self.history_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    entry = EditHistoryEntry(**data)
                    if entry.author == author:
                        yield entry
        except (OSError, json.JSONDecodeError, TypeError):
            return
