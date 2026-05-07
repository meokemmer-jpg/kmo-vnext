# [CRUX-MK]
"""Deduplication-Engine (Welle-20 Phase-13.2 KMO-vNext, Modul 3/3).

Cross-DF-Event-Dedup via Hash + TTL.

Bio-Aequivalent: B-Zell-Memory (Antigen-Hash-Memory mit Halbwertszeit).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class DedupResult:
    """Frozen-Result einer Dedup-Pruefung.

    Pre: event_hash non-empty, ttl_remaining_s >= 0.
    Post: immutable.

    Felder:
      - is_duplicate: bool — True wenn Event bereits aktiv (innerhalb TTL).
      - event_hash: str — der berechnete Hash.
      - original_seen_at: Optional[float] — first_seen_at falls Duplikat, sonst None.
      - ttl_remaining_s: float — verbleibende TTL in Sekunden (0.0 wenn neu).
      - reason: str — kurze Begruendung ("first_seen" / "duplicate_active" /
                       "duplicate_expired_renewed").
      - timestamp: float — Zeitpunkt der Pruefung.
    """

    is_duplicate: bool
    event_hash: str
    original_seen_at: Optional[float]
    ttl_remaining_s: float
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.event_hash:
            raise ValueError("event_hash required")
        if self.ttl_remaining_s < 0:
            raise ValueError("ttl_remaining_s must be >= 0")


@dataclass(frozen=True)
class EventRecord:
    """Frozen interner Datensatz pro getrackt'em Event.

    Pre: event_hash non-empty, first_seen_at > 0, ttl_s > 0, hit_count >= 0.
    Post: immutable. Updates erzeugen neuen EventRecord.
    """

    event_hash: str
    first_seen_at: float
    hit_count: int
    ttl_s: float

    def __post_init__(self) -> None:
        if not self.event_hash:
            raise ValueError("event_hash required")
        if self.first_seen_at <= 0:
            raise ValueError("first_seen_at must be > 0")
        if self.ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        if self.hit_count < 0:
            raise ValueError("hit_count must be >= 0")

    def is_expired(self, now: float) -> bool:
        return (now - self.first_seen_at) >= self.ttl_s

    def remaining_s(self, now: float) -> float:
        return max(0.0, self.ttl_s - (now - self.first_seen_at))


def _default_hash(payload: Any) -> str:
    """Default-Hash: SHA256 ueber sorted-json-dump.

    Ordnungsunabhaengig fuer dict-payloads. Fallback auf repr() bei
    nicht-JSON-serialisierbaren Inputs.
    """
    try:
        canonical = json.dumps(payload, sort_keys=True, default=repr, ensure_ascii=False)
    except (TypeError, ValueError):
        canonical = repr(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DeduplicationEngine:
    """Cross-DF-Event-Dedup-Engine mit Hash + TTL.

    Pre: default_ttl_s > 0, max_entries >= 1.
    Post: thread-safe (RLock); LRU-Eviction wenn max_entries erreicht;
          first_seen_at unveraendert bei hit (nur hit_count steigt);
          nach TTL-Ablauf wird Eintrag bei naechstem check() verworfen
          und als neu (first_seen) klassifiziert.
    """

    def __init__(
        self,
        default_ttl_s: float = 3600.0,
        max_entries: int = 100_000,
        hash_fn: Optional[Callable[[Any], str]] = None,
    ) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.default_ttl_s = default_ttl_s
        self.max_entries = max_entries
        self._hash_fn = hash_fn or _default_hash
        self._records: dict[str, EventRecord] = {}
        self._hits: int = 0
        self._misses: int = 0
        self._expired_purges: int = 0
        self._evictions: int = 0
        self._lock = threading.RLock()

    def _compute_hash(self, payload: Any) -> str:
        h = self._hash_fn(payload)
        if not isinstance(h, str) or not h:
            raise ValueError("hash_fn must return non-empty str")
        return h

    def check(
        self,
        event_payload: Any,
        ttl_s: Optional[float] = None,
    ) -> DedupResult:
        """Pruefe ob Event Duplikat. Markiere als gesehen bei first-time / nach Ablauf.

        Pre: ttl_s None oder > 0.
        Post: bei is_duplicate=False wurde ein neuer EventRecord persistiert
              (oder ein expired'er ueberschrieben); bei is_duplicate=True wurde
              hit_count um 1 erhoeht.
        """
        if ttl_s is not None and ttl_s <= 0:
            raise ValueError("ttl_s must be > 0 when provided")
        effective_ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        event_hash = self._compute_hash(event_payload)
        now = time.time()

        with self._lock:
            existing = self._records.get(event_hash)
            if existing is not None:
                if not existing.is_expired(now):
                    # Active duplicate: bump hit_count, keep first_seen_at.
                    updated = EventRecord(
                        event_hash=existing.event_hash,
                        first_seen_at=existing.first_seen_at,
                        hit_count=existing.hit_count + 1,
                        ttl_s=existing.ttl_s,
                    )
                    self._records[event_hash] = updated
                    self._hits += 1
                    return DedupResult(
                        is_duplicate=True,
                        event_hash=event_hash,
                        original_seen_at=existing.first_seen_at,
                        ttl_remaining_s=updated.remaining_s(now),
                        reason="duplicate_active",
                        timestamp=now,
                    )
                # Expired: drop and treat as new.
                del self._records[event_hash]
                self._expired_purges += 1
                self._evict_if_needed()
                self._records[event_hash] = EventRecord(
                    event_hash=event_hash,
                    first_seen_at=now,
                    hit_count=0,
                    ttl_s=effective_ttl,
                )
                self._misses += 1
                return DedupResult(
                    is_duplicate=False,
                    event_hash=event_hash,
                    original_seen_at=None,
                    ttl_remaining_s=effective_ttl,
                    reason="duplicate_expired_renewed",
                    timestamp=now,
                )

            # First time seen.
            self._evict_if_needed()
            self._records[event_hash] = EventRecord(
                event_hash=event_hash,
                first_seen_at=now,
                hit_count=0,
                ttl_s=effective_ttl,
            )
            self._misses += 1
            return DedupResult(
                is_duplicate=False,
                event_hash=event_hash,
                original_seen_at=None,
                ttl_remaining_s=effective_ttl,
                reason="first_seen",
                timestamp=now,
            )

    def _evict_if_needed(self) -> None:
        """LRU-Eviction by first_seen_at (eldest first). Lock held by caller."""
        while len(self._records) >= self.max_entries:
            eldest_hash = min(
                self._records,
                key=lambda h: self._records[h].first_seen_at,
            )
            del self._records[eldest_hash]
            self._evictions += 1

    def force_expire(self, event_hash: str) -> bool:
        """Manueller Override: erzwinge Expiry eines Records.

        Returns True wenn Record existierte und entfernt wurde, sonst False.
        """
        if not event_hash:
            raise ValueError("event_hash required")
        with self._lock:
            if event_hash in self._records:
                del self._records[event_hash]
                return True
            return False

    def cleanup_expired(self) -> int:
        """Purge alle Records mit (now - first_seen_at) >= ttl_s.

        Returns Anzahl entfernter Records.
        """
        now = time.time()
        with self._lock:
            expired_hashes = [
                h for h, rec in self._records.items() if rec.is_expired(now)
            ]
            for h in expired_hashes:
                del self._records[h]
            self._expired_purges += len(expired_hashes)
            return len(expired_hashes)

    def get_stats(self) -> dict:
        """Snapshot der Engine-Stats.

        Felder: active_entries, hits, misses, expired_purges, evictions,
                total_checks, max_entries, default_ttl_s.
        """
        with self._lock:
            return {
                "active_entries": len(self._records),
                "hits": self._hits,
                "misses": self._misses,
                "expired_purges": self._expired_purges,
                "evictions": self._evictions,
                "total_checks": self._hits + self._misses,
                "max_entries": self.max_entries,
                "default_ttl_s": self.default_ttl_s,
            }

    def list_active(self) -> list[EventRecord]:
        """Snapshot aller aktiven (nicht-expired) Records.

        Post: cleanup ist nicht implizit; expired Records koennen enthalten
              sein bis cleanup_expired() oder check() sie entfernt. Diese
              Methode filtert sie aus.
        """
        now = time.time()
        with self._lock:
            return [r for r in self._records.values() if not r.is_expired(now)]


# CRUX-MK
