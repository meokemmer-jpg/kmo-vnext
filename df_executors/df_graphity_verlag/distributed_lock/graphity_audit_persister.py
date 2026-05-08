"""Graphity Audit-Persister (Domain-Adapter ueber Synaptic-Plasticity) [CRUX-MK]

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

Domain-Adapter ueber `synaptic_plasticity` (Hash-Chain Pattern-Modul).
Behaelt Graphity-spezifische Field-Names (project_id/section_id/author)
durch Mapping zu Pattern-Modul-Names (container_key/resource_key/actor_id).

Bio-Pattern-Korrespondenz:
- Hash-Chain     = Synaptic-Long-Term-Memory (jeder Edit verlinkt zum vorherigen)
- Edit-Entry     = Single-Memory-Trace
- Genesis-Hash   = Initial-Synaptic-State
- Verify-Chain   = Memory-Consolidation-Check

CRUX-Bindung:
- Q_0: Edit-History ist tamper-evident (Hash-Chain)
- I_min: append-only Hash-Chain
- W_0: Pattern-Reuse aus synaptic_plasticity (separates Pattern-Modul)

Wichtig (V14 P-W31-1 Konsens):
    Hash-Chain ist Tamper-Evidence, NICHT Tamper-Proof. Externer
    Anker-Mechanismus (RFC3161 / GitHub-Daily-Push / S3-Object-Lock)
    ist Pflicht pro `~/.claude/rules/external-anchor-requirement-audit-logs.md`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from synaptic_plasticity import (
    GENESIS_HASH,
    append_entry,
    hash_content_string,
    stream_entries,
    verify_chain as core_verify_chain,
)

# Constants with units
DEFAULT_HISTORY_PATH: Path = (
    Path.home() / ".graphity" / "edit_history.jsonl"
)

EditAction = str  # "lock_acquire" | "lock_release" | "edit_commit" |
# "merge_resolve" | "force_release"


@dataclass(frozen=True)
class EditHistoryEntry:
    """Domain-Adapter shape: Graphity-spezifische Field-Names.

    Backwards-compat: tests + downstream consumers expect (project_id,
    section_id, author). Pattern-Modul nutzt (container_key, resource_key,
    actor_id).
    """

    block_index: int
    timestamp: int
    project_id: str
    section_id: str
    author: str
    action: EditAction
    content_hash: str
    metadata: str
    prev_hash: str
    block_hash: str

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "block_index": self.block_index,
                "timestamp": self.timestamp,
                "project_id": self.project_id,
                "section_id": self.section_id,
                "author": self.author,
                "action": self.action,
                "content_hash": self.content_hash,
                "metadata": self.metadata,
                "prev_hash": self.prev_hash,
                "block_hash": self.block_hash,
            },
            sort_keys=True, separators=(",", ":"),
        )


def _core_to_domain_entry(core_entry) -> EditHistoryEntry:
    """Map Pattern-Modul-Entry -> Domain-Adapter-Entry."""
    return EditHistoryEntry(
        block_index=core_entry.block_index,
        timestamp=core_entry.timestamp,
        project_id=core_entry.container_key,
        section_id=core_entry.resource_key,
        author=core_entry.actor_id,
        action=core_entry.action,
        content_hash=core_entry.content_hash,
        metadata=core_entry.metadata,
        prev_hash=core_entry.prev_hash,
        block_hash=core_entry.block_hash,
    )


class GraphityAuditPersister:
    """Domain-Adapter Append-only Edit-History mit Hash-Chain-Integrity.

    Pattern-Modul: synaptic_plasticity (Bio: LTP).
    Domain-Spezifisch: emit JSONL-Lines im Graphity-Schema (project_id/
    section_id/author) statt Pattern-Schema (container_key/resource_key/
    actor_id).

    Pre: history_path parent dir exists or creatable.
    Post: alle Eintraege Hash-verlinkt, verify_chain() erkennt Tampering.
    """

    def __init__(self, history_path: Path = DEFAULT_HISTORY_PATH):
        self.history_path = history_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            self.history_path.touch()

    @staticmethod
    def _hash_content(text: str) -> str:
        return hash_content_string(text)

    def append_lock_acquire(
        self,
        project_id: str,
        section_id: str,
        author: str,
        nonce: str,
    ) -> EditHistoryEntry:
        """Audit Lock-Acquire (Synaptic-Vesikel-Release-Event)."""
        return self._append(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="lock_acquire",
            content_hash=hash_content_string(nonce),
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
        return self._append(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="lock_release",
            content_hash=hash_content_string(nonce),
            metadata=json.dumps(
                {"nonce_prefix": nonce[:16], "release_type": release_type}
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
        return self._append(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="edit_commit",
            content_hash=hash_content_string(edit_content),
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
            {"resolution": resolution_strategy, "conflict_count": conflict_count}
        )
        return self._append(
            project_id=project_id,
            section_id=section_id,
            author=author,
            action="merge_resolve",
            content_hash=hash_content_string(merged_content),
            metadata=meta,
        )

    def _append(
        self,
        project_id: str,
        section_id: str,
        author: str,
        action: EditAction,
        content_hash: str,
        metadata: str,
    ) -> EditHistoryEntry:
        """Domain-Adapter: write JSONL with Graphity-shape (project_id/
        section_id/author) but compute hash-chain in Pattern-Modul-shape.

        We keep the JSONL emit-format Domain-shaped (project_id...) for
        backwards-compat. The chain-hash is computed deterministically over
        Domain-shaped content by re-using compute_chain_hash with the same
        canonical-content algorithm via a tiny fork below.
        """
        # Read prev-entry (Domain-shaped) by streaming JSONL tail
        prev = self._last_domain_entry()
        prev_hash = prev.block_hash if prev else GENESIS_HASH
        block_index = (prev.block_index + 1) if prev else 0
        timestamp = int(time.time())

        content = {
            "block_index": block_index,
            "timestamp": timestamp,
            "project_id": project_id,
            "section_id": section_id,
            "author": author,
            "action": action,
            "content_hash": content_hash,
            "metadata": metadata,
        }
        # Use Pattern-Modul hashing primitive for consistency
        from synaptic_plasticity import compute_chain_hash
        block_hash = compute_chain_hash(prev_hash, content)

        entry = EditHistoryEntry(
            block_index=block_index,
            timestamp=timestamp,
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

    def _last_domain_entry(self) -> Optional[EditHistoryEntry]:
        """Stream-read last entry in Domain-shape."""
        try:
            with self.history_path.open("rb") as fp:
                fp.seek(0, 2)
                size = fp.tell()
                if size == 0:
                    return None
                fp.seek(max(0, size - 4096))
                tail = fp.read().decode("utf-8")
                lines = [ln for ln in tail.splitlines() if ln.strip()]
                if not lines:
                    return None
                data = json.loads(lines[-1])
                return EditHistoryEntry(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    # Backwards-compat alias (used by w31 tests)
    def _last_entry(self) -> Optional[EditHistoryEntry]:
        return self._last_domain_entry()

    @staticmethod
    def _compute_hash(prev_hash: str, content: dict) -> str:
        """Backwards-compat: delegate to Pattern-Modul."""
        from synaptic_plasticity import compute_chain_hash
        return compute_chain_hash(prev_hash, content)

    def verify_chain(self) -> bool:
        """Verify entire chain integrity (Domain-shape JSONL)."""
        from synaptic_plasticity import compute_chain_hash
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
                    if compute_chain_hash(prev_hash, content) != entry.block_hash:
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
