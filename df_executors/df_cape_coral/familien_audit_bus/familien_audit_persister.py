"""Familien-Audit-Persister (Cape-Coral-Vault Audit-Trail) [CRUX-MK]

Persistiert Familien-Decisions in zwei Formaten:
1. JSONL atomic-append (rules/audit-trail.md §1) - maschinenlesbar
2. Markdown-Decision-Card pro Decision - Cape-Coral-Vault PARA-konform

Bio: Lymph-Sammelstation -> JSONL-Log. Lymphknoten-Memory -> Markdown-Cards.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from familien_audit_bus import FamilienDecisionEnvelope
    from familien_decision_filter import FilterDecision


def _atomic_write_text(target: Path, text: str) -> None:
    """Atomic-Write fuer Text/Markdown (Reuse outbox-pattern Idiom)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), prefix=".tmp-", suffix=".md"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _atomic_append_jsonl(target: Path, record: dict) -> None:
    """Append-only JSONL mit fsync (rules/audit-trail.md §1).

    O_APPEND fuer atomare Writes auf POSIX (Single-Line < PIPE_BUF).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


class FamilienAuditPersister:
    """Persister fuer Familien-Decision-Audit-Trail.

    Pre: vault_root erstellbar.
    Post: pro Decision: 1 JSONL-Eintrag in audit-log + 1 Markdown-Card in dc/.
    """

    def __init__(
        self,
        vault_root: Path,
        audit_log_relpath: str = "branch-hub/audit/familien-audit-log.jsonl",
        decision_cards_relpath: str = "projects/cape-coral-relocation/decision-cards",
    ):
        self.vault_root = Path(vault_root)
        self.audit_log_path = self.vault_root / audit_log_relpath
        self.decision_cards_dir = self.vault_root / decision_cards_relpath
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.decision_cards_dir.mkdir(parents=True, exist_ok=True)

    def persist(self, envelope, filter_results, final_state) -> dict:
        """Persistiert Decision + Filter-Results in Cape-Coral-Vault.

        Pre: envelope + filter_results valid.
        Post: dict mit jsonl_path + markdown_path (beide existieren atomar).
        """
        # 1. JSONL Audit-Log-Eintrag (rules/audit-trail.md §1 Format)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "branch": "cape-coral-familien-audit-bus",
            "action": "FAMILIEN-DECISION-FINALIZED",
            "target": envelope.filename(),
            "decision_id": envelope.decision_id,
            "domain": envelope.domain,
            "seq": envelope.seq,
            "proposer": envelope.proposer_member_id,
            "title": envelope.title,
            "final_state": final_state,
            "filter_count": len(filter_results),
            "filter_summary": [
                {"member": fr.member_id, "action": fr.action, "rationale": fr.rationale}
                for fr in filter_results
            ],
            "reason": "lymphatic-bus-finalized",
            "source": "df_cape_coral.familien_audit_bus",
        }
        _atomic_append_jsonl(self.audit_log_path, record)

        # 2. Markdown Decision-Card
        md_path = self._render_markdown(envelope, filter_results, final_state)
        return {
            "jsonl_path": str(self.audit_log_path),
            "markdown_path": str(md_path),
            "final_state": final_state,
        }

    def _render_markdown(self, envelope, filter_results, final_state) -> Path:
        """Rendert Markdown-Decision-Card im Cape-Coral-Vault-Stil."""
        date_str = datetime.fromtimestamp(envelope.timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
        safe_title = "".join(
            c if c.isalnum() or c in "-_" else "-" for c in envelope.title.lower()
        )[:60]
        md_filename = (
            f"DC-FAM-{envelope.domain.upper()}-"
            f"{envelope.seq:08d}-{safe_title}-{date_str}.md"
        )
        md_path = self.decision_cards_dir / md_filename

        lines = [
            "---",
            "type: decision",
            "domain: cape-coral",
            f"sub-domain: {envelope.domain}",
            "lifecycle: canonical",
            f"status: {'blocked' if final_state == 'vetoed' else 'active'}",
            f"date: {date_str}",
            f"decision_id: {envelope.decision_id}",
            f"proposer: {envelope.proposer_member_id}",
            "crux-mk: true",
            "---",
            "",
            f"# {envelope.title} [CRUX-MK]",
            "",
            f"**Decision-ID:** `{envelope.decision_id}`  ",
            f"**Domain:** {envelope.domain}  ",
            f"**Proposer:** {envelope.proposer_member_id}  ",
            f"**Sequenz:** {envelope.seq}  ",
            f"**Final-State:** **{final_state.upper()}**",
            "",
            "## Payload",
            "",
            "```json",
            json.dumps(envelope.payload, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Consent-Berechtigte (Veto-Recht)",
            "",
        ]
        if envelope.requires_consent:
            for m in envelope.requires_consent:
                lines.append(f"- {m}")
        else:
            lines.append("_(keine)_")
        lines += ["", "## Info-Only (informiert, kein Veto)", ""]
        if envelope.info_only:
            for m in envelope.info_only:
                lines.append(f"- {m}")
        else:
            lines.append("_(keine)_")
        lines += [
            "",
            "## Filter-Resultate (Lymphatic-Knoten)",
            "",
            "| Mitglied | Action | Begruendung |",
            "|----------|--------|-------------|",
        ]
        for fr in filter_results:
            rationale = (fr.rationale or "").replace("|", "\\|")
            lines.append(f"| {fr.member_id} | **{fr.action}** | {rationale} |")
        lines += [
            "",
            "## CRUX-Bindung",
            "",
            "- **Q_0:** Familien-Audit-Trail-Integritaet (atomic JSONL + Markdown)",
            "- **K_0:** geschuetzt durch Veto-Recht der Consent-Berechtigten",
            "- **I_min:** strukturierte Lymphatic-Verteilung statt ad-hoc Familien-Chat",
            "",
            "[CRUX-MK]",
            "",
        ]
        _atomic_write_text(md_path, "\n".join(lines))
        return md_path


# [CRUX-MK]
