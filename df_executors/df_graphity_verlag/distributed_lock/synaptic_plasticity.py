"""Synaptic-Plasticity (Hash-Chain Pattern-Modul, domain-agnostic) [CRUX-MK]

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

Hash-Chain als **separates Pattern-Modul** (Bio-Aequivalent: Synaptic-Long-
Term-Potentiation / LTP). Versteht jeden append-only Audit-Log mit
Hash-verlinkten Eintraegen. Domain-Agnostic: kennt keine "author"/
"section_id"/"project_id" - sondern generic "actor"/"resource"/"container".

Pattern-Zustandsmaschine:
    GENESIS --append--> CHAIN_LINK_1 --append--> ... --append--> CHAIN_LINK_N

Invariants:
    I-SP-1: GENESIS_HASH = "0"*64 (SHA256 length).
    I-SP-2: block_hash[i] = SHA256(prev_hash + canonical_content[i]).
    I-SP-3: prev_hash[i] == block_hash[i-1] (chain integrity).
    I-SP-4: block_index monotonic ascending from 0.
    I-SP-5: append-only, never mutate existing entries.

Failure-Model:
    F-SP-1: tampered entry -> verify_chain returns False.
    F-SP-2: block_index gap -> verify returns False.
    F-SP-3: corrupted JSONL -> verify returns False (fail-closed).

Note (per V14 P-W31-1 Konsens, Codex/Gemini):
    Hash-Chain bietet Tamper-Evidence, NICHT Tamper-Proof. Externer
    Anker (RFC3161 / GitHub-Daily-Push / S3-Object-Lock) ist Pflicht
    pro `~/.claude/rules/external-anchor-requirement-audit-logs.md`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional


GENESIS_HASH: str = "0" * 64


@dataclass(frozen=True)
class CoreChainEntry:
    """Immutable Hash-Chain entry (Pattern-Modul, domain-agnostic).

    Domain-Adapter wraps with typed names (author, section_id) but the
    chain-integrity is a pure function of block_index + canonical-content
    + prev_hash.
    """

    block_index: int
    timestamp: int
    container_key: str  # e.g. project_id
    resource_key: str   # e.g. section_id
    actor_id: str       # e.g. author
    action: str
    content_hash: str
    metadata: str       # JSON-string
    prev_hash: str
    block_hash: str

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def compute_chain_hash(prev_hash: str, content: dict) -> str:
    """Pattern-Modul hash-link: SHA256(prev_hash + canonical_content)."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    msg = (prev_hash + canonical).encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def hash_content_string(text: str) -> str:
    """Pattern-Modul: SHA256 of arbitrary text-content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_last_entry(history_path: Path) -> Optional[CoreChainEntry]:
    """Stream-read the last entry from a JSONL chain (efficient tail-read)."""
    try:
        with history_path.open("rb") as fp:
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
            return CoreChainEntry(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def append_entry(
    history_path: Path,
    container_key: str,
    resource_key: str,
    actor_id: str,
    action: str,
    content_hash: str,
    metadata: str,
    timestamp: int,
) -> CoreChainEntry:
    """Pattern-Modul append: link to prev_hash + write JSONL line."""
    if not all([container_key, resource_key, actor_id, action]):
        raise ValueError(
            "container_key, resource_key, actor_id, action non-empty"
        )

    prev = read_last_entry(history_path)
    prev_hash = prev.block_hash if prev else GENESIS_HASH
    block_index = (prev.block_index + 1) if prev else 0

    content = {
        "block_index": block_index,
        "timestamp": timestamp,
        "container_key": container_key,
        "resource_key": resource_key,
        "actor_id": actor_id,
        "action": action,
        "content_hash": content_hash,
        "metadata": metadata,
    }
    block_hash = compute_chain_hash(prev_hash, content)

    entry = CoreChainEntry(
        block_index=block_index,
        timestamp=timestamp,
        container_key=container_key,
        resource_key=resource_key,
        actor_id=actor_id,
        action=action,
        content_hash=content_hash,
        metadata=metadata,
        prev_hash=prev_hash,
        block_hash=block_hash,
    )

    with history_path.open("a", encoding="utf-8") as fp:
        fp.write(entry.to_json_line() + "\n")
    return entry


def verify_chain(history_path: Path) -> bool:
    """Pattern-Modul: verify chain integrity (I-SP-2, I-SP-3, I-SP-4)."""
    prev_hash = GENESIS_HASH
    expected_index = 0
    try:
        with history_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                data = json.loads(line)
                entry = CoreChainEntry(**data)

                if entry.block_index != expected_index:
                    return False
                if entry.prev_hash != prev_hash:
                    return False

                content = {
                    "block_index": entry.block_index,
                    "timestamp": entry.timestamp,
                    "container_key": entry.container_key,
                    "resource_key": entry.resource_key,
                    "actor_id": entry.actor_id,
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


def stream_entries(history_path: Path) -> Iterator[CoreChainEntry]:
    """Pattern-Modul: iterate all chain entries (read-only)."""
    try:
        with history_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                data = json.loads(line)
                yield CoreChainEntry(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return


# [CRUX-MK]
