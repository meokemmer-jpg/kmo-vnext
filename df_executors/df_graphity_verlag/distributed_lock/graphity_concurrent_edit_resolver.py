"""Graphity Concurrent-Edit-Resolver [CRUX-MK]

Three-Way-Merge fuer concurrent Edits (wenn 2 Authoren parallel arbeiten
und Lock-Coordination versagt -> Fallback-Resolution).

Bio-Pattern-Korrespondenz:
- Three-Way-Merge = Synaptic-Long-Term-Potentiation (mehrere Inputs konsolidiert)
- Base-Version    = Initial-State (Pre-Spike)
- Author-A-Version = Edit-Path-A
- Author-B-Version = Edit-Path-B
- Merged-Version  = Konsolidiertes Output (Post-Spike-Plasticity)

CRUX-Bindung:
- Q_0: kein Lost-Update bei Race-Condition
- I_min: deterministische Merge-Regel
- W_0: Pattern-Reuse aus Three-Way-Merge-Tradition (Git, Mercurial)
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ConflictResolution(Enum):
    """Resolution-Strategien fuer Edit-Konflikte."""

    AUTO_MERGE = "auto_merge"  # No overlapping changes -> auto-merge
    AUTHOR_A_WINS = "author_a_wins"  # Manual override
    AUTHOR_B_WINS = "author_b_wins"  # Manual override
    MANUAL_REQUIRED = "manual_required"  # Conflict -> Editor-Brief
    REJECTED = "rejected"  # Both versions invalid


@dataclass(frozen=True)
class EditResult:
    """Resultat eines Three-Way-Merge."""

    merged_text: str
    resolution: ConflictResolution
    conflict_count: int
    conflicts: tuple[tuple[int, str, str], ...]  # (line_no, a_text, b_text)


class GraphityConcurrentEditResolver:
    """Three-Way-Merge fuer Buchprojekt-Section-Edits.

    Pre: alle 3 Versionen sind Strings (Section-Content).
    Post: deterministisches EditResult mit Resolution-Strategie.
    """

    def __init__(self, conflict_marker_a: str = "<<< AUTHOR-A",
                 conflict_marker_b: str = ">>> AUTHOR-B",
                 conflict_separator: str = "===") -> None:
        self.marker_a = conflict_marker_a
        self.marker_b = conflict_marker_b
        self.separator = conflict_separator

    def merge(
        self,
        base: str,
        author_a: str,
        author_b: str,
        author_a_name: str = "author_a",
        author_b_name: str = "author_b",
    ) -> EditResult:
        """Three-Way-Merge: base + author_a + author_b -> merged.

        Pre: base != None (kann leer sein), author_a + author_b nicht beide
        identisch zu base.

        Post: EditResult mit:
        - AUTO_MERGE: disjunkte Aenderungen, automatisch konsolidiert
        - MANUAL_REQUIRED: ueberlappende Aenderungen, Konflikt-Marker
        - REJECTED: invalid input
        """
        if base is None or author_a is None or author_b is None:
            return EditResult(
                merged_text="",
                resolution=ConflictResolution.REJECTED,
                conflict_count=0,
                conflicts=(),
            )

        # Trivial cases
        if author_a == base and author_b == base:
            # Niemand hat geaendert
            return EditResult(
                merged_text=base,
                resolution=ConflictResolution.AUTO_MERGE,
                conflict_count=0,
                conflicts=(),
            )
        if author_a == base:
            # Nur B hat geaendert
            return EditResult(
                merged_text=author_b,
                resolution=ConflictResolution.AUTO_MERGE,
                conflict_count=0,
                conflicts=(),
            )
        if author_b == base:
            # Nur A hat geaendert
            return EditResult(
                merged_text=author_a,
                resolution=ConflictResolution.AUTO_MERGE,
                conflict_count=0,
                conflicts=(),
            )
        if author_a == author_b:
            # Beide identisch geaendert -> trivial Merge
            return EditResult(
                merged_text=author_a,
                resolution=ConflictResolution.AUTO_MERGE,
                conflict_count=0,
                conflicts=(),
            )

        # Three-Way-Merge auf Zeilen-Ebene (analog Git)
        return self._merge_lines(
            base,
            author_a,
            author_b,
            author_a_name,
            author_b_name,
        )

    def _merge_lines(
        self,
        base: str,
        author_a: str,
        author_b: str,
        author_a_name: str,
        author_b_name: str,
    ) -> EditResult:
        """Diff-basierter 3-Way-Merge auf Zeilen-Ebene."""
        base_lines = base.splitlines(keepends=True)
        a_lines = author_a.splitlines(keepends=True)
        b_lines = author_b.splitlines(keepends=True)

        # Diff base -> A and base -> B
        a_diff = list(
            difflib.ndiff(base_lines, a_lines)
        )
        b_diff = list(
            difflib.ndiff(base_lines, b_lines)
        )

        # Sammle Block-Aenderungen pro Diff
        a_changes = self._extract_changes(base_lines, a_lines)
        b_changes = self._extract_changes(base_lines, b_lines)

        # Pruefe Overlap der base-Indizes
        overlap = self._has_overlap(a_changes, b_changes)

        if not overlap:
            # Auto-Merge: disjunkte Aenderungen
            merged = self._apply_disjoint_merges(
                base_lines, a_changes, b_changes
            )
            return EditResult(
                merged_text="".join(merged),
                resolution=ConflictResolution.AUTO_MERGE,
                conflict_count=0,
                conflicts=(),
            )

        # Konflikt: ueberlappende Aenderungen -> Marker einfuegen
        merged_text, conflicts = self._produce_conflict_markers(
            base_lines,
            a_lines,
            b_lines,
            author_a_name,
            author_b_name,
        )
        return EditResult(
            merged_text=merged_text,
            resolution=ConflictResolution.MANUAL_REQUIRED,
            conflict_count=len(conflicts),
            conflicts=tuple(conflicts),
        )

    def _extract_changes(
        self, base_lines: list[str], target_lines: list[str]
    ) -> list[tuple[int, int, list[str]]]:
        """Extrahiere Aenderungs-Bloecke (start_idx_in_base, end_idx_in_base, replacement)."""
        matcher = difflib.SequenceMatcher(None, base_lines, target_lines)
        changes: list[tuple[int, int, list[str]]] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert", "delete"):
                replacement = target_lines[j1:j2]
                changes.append((i1, i2, replacement))
        return changes

    def _has_overlap(
        self,
        a_changes: list[tuple[int, int, list[str]]],
        b_changes: list[tuple[int, int, list[str]]],
    ) -> bool:
        """Pruefe ob A-Aenderungen und B-Aenderungen denselben base-Bereich treffen."""
        for a_start, a_end, _ in a_changes:
            for b_start, b_end, _ in b_changes:
                # Overlap-Logik: max(start) < min(end)
                if max(a_start, b_start) < min(a_end, b_end):
                    return True
                # Insert-at-same-point Konflikt
                if a_start == a_end == b_start == b_end:
                    return True
        return False

    def _apply_disjoint_merges(
        self,
        base_lines: list[str],
        a_changes: list[tuple[int, int, list[str]]],
        b_changes: list[tuple[int, int, list[str]]],
    ) -> list[str]:
        """Wende disjunkte Aenderungen aus A und B auf base an."""
        # Vereinige + sortiere alle Aenderungen, base-Index ascending
        all_changes = sorted(
            a_changes + b_changes, key=lambda c: c[0]
        )

        result: list[str] = []
        cursor = 0
        for start, end, replacement in all_changes:
            # Kopiere unveraenderten Bereich
            result.extend(base_lines[cursor:start])
            # Wende Replacement
            result.extend(replacement)
            cursor = end
        # Rest
        result.extend(base_lines[cursor:])
        return result

    def _produce_conflict_markers(
        self,
        base_lines: list[str],
        a_lines: list[str],
        b_lines: list[str],
        author_a_name: str,
        author_b_name: str,
    ) -> tuple[str, list[tuple[int, str, str]]]:
        """Erzeuge merged Text mit Conflict-Markern (Git-Style)."""
        # Vereinfachung: ganze Datei als 1 Konflikt-Block markieren wenn
        # Overlap gefunden wurde.
        marker_open = f"{self.marker_a} ({author_a_name})\n"
        marker_close = f"{self.marker_b} ({author_b_name})\n"
        sep = f"{self.separator}\n"

        merged = (
            marker_open
            + "".join(a_lines)
            + (
                ""
                if a_lines and a_lines[-1].endswith("\n")
                else "\n"
            )
            + sep
            + "".join(b_lines)
            + (
                ""
                if b_lines and b_lines[-1].endswith("\n")
                else "\n"
            )
            + marker_close
        )

        conflicts: list[tuple[int, str, str]] = [
            (1, "".join(a_lines), "".join(b_lines))
        ]
        return merged, conflicts

    def force_resolve(
        self,
        edit_result: EditResult,
        winner: ConflictResolution,
        author_a_text: str,
        author_b_text: str,
    ) -> Optional[str]:
        """Manual-Override fuer MANUAL_REQUIRED: pick A or B.

        Pre: edit_result.resolution == MANUAL_REQUIRED.
        Post: returns winner text or None on invalid input.
        """
        if edit_result.resolution != ConflictResolution.MANUAL_REQUIRED:
            return None
        if winner == ConflictResolution.AUTHOR_A_WINS:
            return author_a_text
        if winner == ConflictResolution.AUTHOR_B_WINS:
            return author_b_text
        return None
