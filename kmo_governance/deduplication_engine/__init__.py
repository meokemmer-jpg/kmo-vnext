# [CRUX-MK]
"""Deduplication-Engine (Welle-20 Phase-13.2 KMO-vNext, Modul 3/3).

Bio-Aequivalent: B-Zell-Memory (Immunsystem-Gedaechtnis).

Wie B-Zellen einen Antigen-Hash mit definierter Halbwertszeit speichern, um
bereits-gesehene Pathogene als bekannt zu klassifizieren (waehrend nach TTL
eine Re-Exposition wieder als neu eingestuft wird), speichert die Engine
Cross-DF-Event-Hashes mit konfigurierbarer TTL. Gleicher Event innerhalb
TTL = Duplikat (skip). Gleicher Event nach TTL-Ablauf = neu (re-process).

Klassen:
  - DedupResult (Frozen): is_duplicate, event_hash, original_seen_at,
                          ttl_remaining_s, reason, timestamp
  - EventRecord (Frozen, intern): event_hash, first_seen_at, hit_count, ttl_s
  - DeduplicationEngine: check, force_expire, cleanup_expired,
                         get_stats, list_active

Default-Hash: SHA256 ueber sorted-json-dump (ordnungsunabhaengig).
LRU-Eviction wenn max_entries erreicht (eldest by first_seen_at).
"""
from .deduplication_engine import (
    DedupResult,
    DeduplicationEngine,
    EventRecord,
)

__all__ = [
    "DedupResult",
    "DeduplicationEngine",
    "EventRecord",
]

# CRUX-MK
