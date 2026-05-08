"""Familien-Audit-Bus (Lymphatic-Pattern Core) [CRUX-MK]

Bio-Pattern: Lymphatic-Knoten -> Familien-Mitglied. Antigen -> Familien-Decision.
Filter-Kriterium -> Mitglied-spezifisch. Verteilte Filterung + Audit-Trail-Sammlung.
Pattern-Reuse aus kmo_governance/outbox-pattern: atomic_write_json, EventEnvelope-Style.

Spec: Welle-30 W-30-1 (Hotel/Trading -> Cape-Coral-Vault Familien-Verwaltung).
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from familien_decision_filter import FamilienDecisionFilter, FilterDecision
    from familien_audit_persister import FamilienAuditPersister


# Familien-Decision-Domains (CLAUDE.md Cape-Coral-Relocation Q_0/K_0-Naehe)
DOMAIN_RELOCATION = "relocation"  # Cape-Coral-Move, Wegzugssteuer, E-2 Visa
DOMAIN_HEALTH = "health"          # Gesundheits-Decision
DOMAIN_EDUCATION = "education"    # Schule, Ausbildung
DOMAIN_FINANCE = "finance"        # Familien-Kapital (K_0)
DOMAIN_RELATIONS = "relations"    # Brueder/Eltern (Q_0)

VALID_DOMAINS = frozenset({
    DOMAIN_RELOCATION, DOMAIN_HEALTH, DOMAIN_EDUCATION,
    DOMAIN_FINANCE, DOMAIN_RELATIONS,
})


@dataclass
class FamilienDecisionEnvelope:
    """Envelope fuer Familien-Decision (Antigen-Aequivalent).

    Pre: decision_id UUID4-str, domain in VALID_DOMAINS, proposer_member_id non-empty.
    Post: filename() deterministisch fuer (domain, seq).
    """

    decision_id: str
    proposer_member_id: str
    domain: str
    seq: int
    timestamp: float
    title: str
    payload: dict
    requires_consent: list = field(default_factory=list)
    info_only: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FamilienDecisionEnvelope":
        return cls(**d)

    def filename(self) -> str:
        short_id = self.decision_id.split("-")[0]
        return f"{self.domain}-{self.seq:08d}-{short_id}.json"


def atomic_write_json(target: Path, data: dict) -> None:
    """Atomic-Write: tempfile + os.replace. Reuse aus outbox-pattern."""
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


class FamilienAuditBus:
    """Lymphatic-Bus fuer Familien-Decisions.

    Verteilt eingehende Decisions an alle registrierten Filter-Nodes (Familien-
    Mitglieder), sammelt deren Filter-Resultate, persistiert Audit-Trail.

    Pre: bus_dir + audit_dir schreibbar.
    Post: Decisions durchlaufen alle Filter, Audit-Trail atomar.
    """

    def __init__(
        self,
        bus_dir: Path,
        audit_dir: Path,
        state_db: Path | None = None,
    ):
        self.bus_dir = Path(bus_dir)
        self.audit_dir = Path(audit_dir)
        self.bus_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        if state_db is None:
            state_db = (
                Path.home() / "Library" / "Application Support"
                / "kmo-cape-coral" / "familien-audit-bus.db"
            )
        self.state_db = Path(state_db)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        self._filters: dict = {}
        self._persister = None

    def _init_db(self) -> None:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS seq_counter (
                    domain TEXT NOT NULL PRIMARY KEY,
                    last_seq INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS processed_decisions (
                    decision_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    finalized_at REAL NOT NULL,
                    final_state TEXT NOT NULL,
                    filter_count INTEGER NOT NULL,
                    veto_count INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain ON processed_decisions(domain)"
            )
            conn.commit()

    def _next_seq(self, domain: str) -> int:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seq_counter (domain, last_seq) VALUES (?, 0)",
                (domain,),
            )
            conn.execute(
                "UPDATE seq_counter SET last_seq = last_seq + 1 WHERE domain = ?",
                (domain,),
            )
            cur = conn.execute(
                "SELECT last_seq FROM seq_counter WHERE domain = ?", (domain,)
            )
            row = cur.fetchone()
            conn.commit()
            return int(row[0])

    def register_filter(self, member_filter) -> None:
        """Registriert Lymphatic-Knoten (Filter pro Familien-Mitglied)."""
        if not member_filter.member_id:
            raise ValueError("member_filter.member_id must be non-empty")
        self._filters[member_filter.member_id] = member_filter

    def attach_persister(self, persister) -> None:
        """Haengt Audit-Trail-Persister an (JSONL + Markdown)."""
        self._persister = persister

    def submit_decision(
        self,
        proposer_member_id: str,
        domain: str,
        title: str,
        payload: dict,
        requires_consent: list | None = None,
        info_only: list | None = None,
        decision_id: str | None = None,
    ) -> FamilienDecisionEnvelope:
        """Reicht Familien-Decision in Bus ein (atomar persistiert).

        Pre: domain in VALID_DOMAINS, title + proposer_member_id non-empty.
        Post: Envelope existiert in bus_dir, naechster process_pending()-Run finalisiert.
        """
        if domain not in VALID_DOMAINS:
            raise ValueError(f"domain {domain!r} not in {VALID_DOMAINS}")
        if not title:
            raise ValueError("title must be non-empty")
        if not proposer_member_id:
            raise ValueError("proposer_member_id must be non-empty")

        envelope = FamilienDecisionEnvelope(
            decision_id=decision_id or str(uuid.uuid4()),
            proposer_member_id=proposer_member_id,
            domain=domain,
            seq=self._next_seq(domain),
            timestamp=time.time(),
            title=title,
            payload=payload,
            requires_consent=list(requires_consent or []),
            info_only=list(info_only or []),
        )
        atomic_write_json(self.bus_dir / envelope.filename(), envelope.to_dict())
        return envelope

    def _is_finalized(self, decision_id: str) -> bool:
        with sqlite3.connect(self.state_db) as conn:
            cur = conn.execute(
                "SELECT 1 FROM processed_decisions WHERE decision_id = ?",
                (decision_id,),
            )
            return cur.fetchone() is not None

    def _record_finalized(self, envelope, final_state, filter_count, veto_count) -> None:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO processed_decisions
                   (decision_id, domain, seq, finalized_at, final_state, filter_count, veto_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    envelope.decision_id, envelope.domain, envelope.seq,
                    time.time(), final_state, filter_count, veto_count,
                ),
            )
            conn.commit()

    def process_pending(self) -> dict:
        """Laeuft Pending-Decisions durch alle Filter-Nodes + persistiert Audit-Trail.

        Returns: stats dict (polled, processed, skipped_finalized, vetoed_count, ...).
        Idempotent: bereits finalisierte Decisions geskippt.
        """
        stats = {
            "polled": 0, "processed": 0, "skipped_finalized": 0,
            "vetoed_count": 0, "approved_count": 0, "errors": [],
        }
        if not self.bus_dir.exists():
            return stats

        for bus_file in sorted(self.bus_dir.glob("*.json")):
            if bus_file.name.startswith(".tmp-"):
                continue
            stats["polled"] += 1
            try:
                with open(bus_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                envelope = FamilienDecisionEnvelope.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                stats["errors"].append(f"parse-error {bus_file.name}: {e}")
                continue

            if self._is_finalized(envelope.decision_id):
                stats["skipped_finalized"] += 1
                continue

            # Lymphatic-Verteilung: Decision an alle relevanten Filter-Nodes
            filter_results = []
            for member_id, member_filter in self._filters.items():
                relevant = (
                    member_id == envelope.proposer_member_id
                    or member_id in envelope.requires_consent
                    or member_id in envelope.info_only
                )
                if not relevant:
                    continue
                try:
                    filter_results.append(member_filter.evaluate(envelope))
                except Exception as e:
                    stats["errors"].append(
                        f"filter-error {member_id}/{envelope.decision_id}: {e}"
                    )

            # Aggregation: Veto durch Consent-Berechtigte = Block
            veto_results = [
                r for r in filter_results
                if r.member_id in envelope.requires_consent and r.action == "veto"
            ]
            final_state = "vetoed" if veto_results else "approved"
            if veto_results:
                stats["vetoed_count"] += 1
            else:
                stats["approved_count"] += 1

            if self._persister is not None:
                try:
                    self._persister.persist(envelope, filter_results, final_state)
                except Exception as e:
                    stats["errors"].append(f"persist-error {envelope.decision_id}: {e}")

            self._record_finalized(
                envelope, final_state,
                filter_count=len(filter_results),
                veto_count=len(veto_results),
            )
            stats["processed"] += 1

        return stats


# [CRUX-MK]
