"""CRUX-MK durable knowledge store for DF-89."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any

from .state_schema import KNOWLEDGE_DB_SCHEMA

if TYPE_CHECKING:
    from .monitor import Paper


class KnowledgeStore:
    """SQLite-backed store with WAL mode and idempotent helpers."""

    def __init__(self, db_path: Path, schema_path: Path | None = None) -> None:
        """Pre: db_path parent is writable. Post: schema is initialized."""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema = schema_path.read_text(encoding="utf-8") if schema_path else KNOWLEDGE_DB_SCHEMA
        with self._connect() as conn:
            conn.executescript(schema)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Pre: database path is set. Post: connection commits or rolls back."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_methodik(
        self, name: str, description: str, confidence: float, status: str = "candidate"
    ) -> str:
        """Pre: name is non-empty and confidence is in [0,1]. Post: claim row is upserted."""
        if not name.strip() or not 0.0 <= confidence <= 1.0:
            raise ValueError("invalid methodik input")
        claim_id = hashlib.sha256(_canonical_name(name).encode("utf-8")).hexdigest()
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO methodik_catalog
                (claim_id,name,description,confidence,status,created_at,last_seen_at,decay_score)
                VALUES (?,?,?,?,?,?,?,1.0)
                ON CONFLICT(claim_id) DO UPDATE SET
                  description=excluded.description,
                  confidence=excluded.confidence,
                  status=excluded.status,
                  last_seen_at=excluded.last_seen_at
                """,
                (claim_id, name.strip(), description, confidence, status, now, now),
            )
        return claim_id

    def add_relation(self, source_id: str, target_id: str, rel_type: str) -> str:
        """Pre: ids are non-empty. Post: relation is stored idempotently."""
        if rel_type not in {"supports", "contradicts", "supersedes"}:
            raise ValueError("invalid relation type")
        rel_id = hashlib.sha256(f"{source_id}:{target_id}:{rel_type}".encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO claim_relations
                (rel_id,source_claim_id,target_claim_id,rel_type,created_at,expires_at)
                VALUES (?,?,?,?,?,NULL)
                """,
                (rel_id, source_id, target_id, rel_type, _utc_now()),
            )
        return rel_id

    def find_cycles(self) -> list[list[str]]:
        """Pre: relation graph may be empty. Post: cyclic claims are marked contested."""
        graph: dict[str, list[str]] = {}
        with self._connect() as conn:
            rows = conn.execute("SELECT source_claim_id,target_claim_id FROM claim_relations").fetchall()
        for row in rows:
            graph.setdefault(row["source_claim_id"], []).append(row["target_claim_id"])
            graph.setdefault(row["target_claim_id"], [])
        index = 0
        stack: list[str] = []
        on_stack: set[str] = set()
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        cycles: list[list[str]] = []

        def visit(node: str) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for target in graph.get(node, []):
                if target not in indices:
                    visit(target)
                    lowlinks[node] = min(lowlinks[node], lowlinks[target])
                elif target in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[target])
            if lowlinks[node] == indices[node]:
                component: list[str] = []
                while stack:
                    current = stack.pop()
                    on_stack.remove(current)
                    component.append(current)
                    if current == node:
                        break
                if len(component) > 1 or node in graph.get(node, []):
                    cycles.append(component)

        for node in graph:
            if node not in indices:
                visit(node)
        if cycles:
            with self._connect() as conn:
                conn.executemany(
                    "UPDATE methodik_catalog SET status='contested' WHERE claim_id=?",
                    [(claim_id,) for cycle in cycles for claim_id in cycle],
                )
        return cycles

    def apply_decay(self, decay_lambda: float = 0.95) -> None:
        """Pre: decay_lambda is in [0,1]. Post: decay_score is updated exponentially."""
        if not 0.0 <= decay_lambda <= 1.0:
            raise ValueError("decay_lambda must be between 0 and 1")
        with self._connect() as conn:
            conn.execute("UPDATE methodik_catalog SET decay_score = decay_score * ?", (decay_lambda,))

    def compute_diversity_score(self, paper_ids: list[str]) -> float:
        """Pre: paper_ids may be empty. Post: returns a score in [0,1]."""
        if not paper_ids:
            return 0.0
        placeholders = ",".join("?" for _ in paper_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT venue_cluster, author_cluster, citation_cluster
                FROM source_independence
                WHERE paper_id IN ({placeholders})
                """,
                paper_ids,
            ).fetchall()
        if not rows:
            return 0.0
        unique_venues = len({row["venue_cluster"] for row in rows})
        unique_authors = len({row["author_cluster"] for row in rows})
        unique_citations = len({row["citation_cluster"] for row in rows})
        return min(unique_venues, unique_authors, unique_citations) / len(rows)

    def add_paper(self, paper: "Paper") -> str:
        """Pre: paper is Paper-compatible. Post: paper and independence row are stored."""
        authors = list(paper.authors)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO paper_index
                (paper_id,title,venue,authors_json,citation_count,year,source_type,abstract,fetched_at,source_url,expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
                """,
                (
                    paper.id,
                    paper.title,
                    paper.venue,
                    json.dumps(authors),
                    paper.citations,
                    paper.year,
                    paper.source_type,
                    paper.abstract,
                    paper.fetched_at.isoformat(),
                    paper.source_url,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO source_independence
                (source_id,paper_id,venue_cluster,author_cluster,citation_cluster,expires_at)
                VALUES (?,?,?,?,?,NULL)
                """,
                (
                    hashlib.sha256(f"source:{paper.id}".encode("utf-8")).hexdigest(),
                    paper.id,
                    (paper.venue or "unknown").lower(),
                    (authors[0] if authors else "unknown").lower(),
                    str(paper.citations),
                ),
            )
        return paper.id

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """Pre: paper_id is non-empty. Post: returns a stored paper or None."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM paper_index WHERE paper_id=?", (paper_id,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["authors_json"] = json.loads(payload["authors_json"])
        return payload

    def mark_failure(
        self, tool: str, reason: str, dead_link: bool = False, auth_walled_domain: bool = False
    ) -> str:
        """Pre: tool and reason are non-empty. Post: failure row is stored."""
        if not tool.strip() or not reason.strip():
            raise ValueError("tool and reason must not be blank")
        failure_id = hashlib.sha256(f"{tool}:{reason}".encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO failure_memory
                (failure_id,tool,reason,dead_link,auth_walled_domain,last_attempt_at,expires_at)
                VALUES (?,?,?,?,?,?,NULL)
                """,
                (failure_id, tool, reason, int(dead_link), int(auth_walled_domain), _utc_now()),
            )
        return failure_id

    def has_processed_event(self, event_id: str) -> bool:
        """Pre: event_id is non-empty. Post: returns whether the event exists."""
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM processed_events WHERE event_id=?", (event_id,)).fetchone()
        return row is not None

    def record_processed_event(self, event_id: str, payload: dict[str, Any]) -> None:
        """Pre: event_id is stable. Post: event exists exactly once."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_events(event_id,created_at,payload_json) VALUES (?,?,?)",
                (event_id, _utc_now(), json.dumps(payload, sort_keys=True)),
            )

    def list_canonical(self) -> list[dict[str, Any]]:
        """Pre: store is initialized. Post: returns canonical claims."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT claim_id,name,description,confidence,status FROM methodik_catalog WHERE status='canonical'"
            ).fetchall()
        return [dict(row) for row in rows]

    def dump_snapshot(self) -> dict[str, int]:
        """Pre: store is initialized. Post: returns coarse table counts."""
        tables = ["methodik_catalog", "paper_index", "failure_memory", "processed_events"]
        with self._connect() as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                for table in tables
            }


def _canonical_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
