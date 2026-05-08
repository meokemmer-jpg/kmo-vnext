# [CRUX-MK]
"""Graphity-Distributed-Edit-Lock (Welle-30 Phase-23 Bio-Pattern-Lift, Wild-Code-Blindtest 3/3).

Bio-Aequivalent: Synaptische-Verbindung (Pre/Post-Synapse + TTL-Decay + Kompetition).
Pattern-Quelle: kmo_governance.distributed_lock_manager (Welle-21 Phase-14, Hotel-Domain).
3-Domain-Vergleich: Hotel (Resource-Lock) -> KPM (Position-Lock) -> Graphity (Edit-Lock).

Graphity-Verlag-Domain-Note:
- Graphity-Verlag = Buchprojekt-Plattform mit Multi-Author-Concurrent-Edits.
- Aktive Buchprojekte: Symbiotic Minds, AI Leadership, Mathematik der Macht,
  Die Souveraene Maschine, Welt 2050.
- Synaptic-Pattern angewendet auf Edit-Lock fuer concurrent author-edits.
- Lock-Schluessel = (book_id, chapter_id, scope); lange TTL (Default 600s = 10min Editor-Window).
- Verhindert Edit-Konflikte ohne globale-Sperre (verschiedene Scopes/Chapters parallel).
- VG-Wort-Tracking + METIS-Compliance setzen Edit-Atomicity voraus.

Demonstriert Bio-Pattern-Architektur als domain-unabhaengig:
3 Domains (Hotel/Trading/Verlag) - gleicher Architekturkern, nur Vokabular adaptiert.
Lift 12 von 12 (Wild-Code-Blindtest 3/3, externe Verlags-Domain).
Siehe BIO-PATTERN-LIFT-DEMO.md fuer 3-Domain-Isomorphie-Tabelle.

Public API:
    from kmo_governance.graphity_distributed_lock import (
        GraphityDistributedEditLock,
        EditLease,
        EditLockResult,
        EditLockState,
        EditScope,
    )
"""

from .graphity_distributed_lock import (
    EditLease,
    EditLockResult,
    EditLockState,
    EditScope,
    GraphityDistributedEditLock,
)

__all__ = [
    "EditLease",
    "EditLockResult",
    "EditLockState",
    "EditScope",
    "GraphityDistributedEditLock",
]

# CRUX-MK
