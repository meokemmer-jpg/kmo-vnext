"""KMO Cytochrome-c Snapshotter [CRUX-MK].

Pre-Death-State-Persistierung der Apoptose-Engine. Schreibt forensische
Snapshots VOR dem Effector-Cascade, damit nach dem Cell-Tod analysiert
werden kann WAS und WARUM gestorben ist.

Bio-Aequivalent: Cytochrome-c-Release aus Mitochondrien (Initiator-Signal
des intrinsischen Apoptose-Pathways). Im Software-Aequivalent: forensischer
State-Dump vor State-Cleanup.

Atomic-Write-Pattern: tempfile + os.replace + fsync (analog saga-engine).

K12 Distillation-Resistenz: Snapshots sind Provenance-Quelle.
K13 Pre-Action-Verification: Snapshot wird VOR Effector-Cascade geschrieben.

Snapshot-Datei-Layout:
    {snapshot_dir}/{hotel_id}/{cell_id}-{ISO-timestamp}.json
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any


def _sanitize_path_component(s: str) -> str:
    """Replace path-unsafe characters with underscores."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


class CytochromeCSnapshotter:
    """Atomic file-based pre-death snapshot writer.

    Pre-Conditions:
        - snapshot_root: writable directory
    Post-Conditions:
        - snapshot() returns absolute path of written file
        - Write is atomic via tempfile + os.replace + fsync
        - One file per cell apoptose-event (no overwrites if same timestamp)
    """

    def __init__(self, snapshot_root: Path) -> None:
        self.snapshot_root = Path(snapshot_root)
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def snapshot(
        self,
        cell_id: str,
        hotel_id: str,
        apoptose_reason: str,
        triggered_at: float,
        accumulated_score: float,
        cell_state: dict,
        signals: list[dict],
    ) -> Path:
        """Write a pre-death snapshot atomically. Returns the written path.

        Pre:
            - cell_id, hotel_id, apoptose_reason non-empty strings
            - triggered_at: UNIX-epoch float
            - cell_state: JSON-serializable dict (use {} if no state-provider)
            - signals: list of JSON-serializable dicts (audit-log of triggers)
        Post:
            - File at {root}/{hotel_id}/{cell_id}-{ISO}.json exists with payload
        """
        if not cell_id or not hotel_id or not apoptose_reason:
            raise ValueError("cell_id, hotel_id, apoptose_reason required")
        hotel_dir = self.snapshot_root / _sanitize_path_component(hotel_id)
        hotel_dir.mkdir(parents=True, exist_ok=True)

        iso = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(triggered_at))
        # add microseconds for uniqueness within same-second cells
        micro = int((triggered_at - int(triggered_at)) * 1_000_000)
        fname = f"{_sanitize_path_component(cell_id)}-{iso}-{micro:06d}.json"
        target = hotel_dir / fname

        payload = {
            "schema_version": "1.0",
            "cell_id": cell_id,
            "hotel_id": hotel_id,
            "apoptose_reason": apoptose_reason,
            "triggered_at_unix": triggered_at,
            "triggered_at_iso": iso,
            "accumulated_score": accumulated_score,
            "cell_state": cell_state,
            "signals": signals,
        }
        self._atomic_write_json(target, payload)
        return target

    @staticmethod
    def _atomic_write_json(target: Path, payload: dict) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}-",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def list_for_hotel(self, hotel_id: str) -> list[Path]:
        """List all snapshot files for a hotel (forensics + GDPR-purge target)."""
        hotel_dir = self.snapshot_root / _sanitize_path_component(hotel_id)
        if not hotel_dir.exists():
            return []
        return sorted(hotel_dir.glob("*.json"))

    def purge_hotel(self, hotel_id: str) -> int:
        """GDPR cascade-delete: remove all snapshots for a hotel.

        Returns number of files deleted.
        """
        files = self.list_for_hotel(hotel_id)
        for f in files:
            try:
                f.unlink()
            except FileNotFoundError:
                pass
        # Also remove empty directory
        hotel_dir = self.snapshot_root / _sanitize_path_component(hotel_id)
        try:
            hotel_dir.rmdir()
        except OSError:
            pass
        return len(files)

    def load(self, path: Path) -> dict:
        """Load a snapshot JSON for inspection."""
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)


# CRUX-MK
