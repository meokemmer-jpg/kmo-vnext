# [CRUX-MK]
"""KPM-Deduplication-Engine — Trade-Order-Idempotency.

Welle-26 Phase-19 Round-2 KMO-vNext, Bio-Pattern-Lift 5/5 von
kmo_governance/deduplication_engine (Welle-20 + W20-P2 LRU).

Bio-Aequivalent: B-Cell-Memory auf Trade-Idempotency.
- client_order_id-Hash + TTL = Body erinnert sich an gesehene Order.
- True LRU eviction (last_access_at) schuetzt Hot-Orders.
- MiFID-RTS-25 retention via Audit-Trail (Stats + Strategy-Index).

Domain-Adjustments vs Hotel-Vorlage:
- Default TTL 300s (5min) statt 3600s (1h) — engerer Network-Retry-Window.
- Primary-Key = client_order_id (broker-stable) — order_hash ist secondary
  check fuer Audit-Trail (gleiche client_order_id + abweichender payload =
  Strategy-Bug-Signal, NICHT Re-Submission).
- strategy_id als Pflicht-Feld fuer Multi-Strategy-Routing-Audit.

CRUX-MK
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class TradeDedupResult:
    """Frozen-Result einer Trade-Dedup-Pruefung.

    Pre: client_order_id non-empty, order_hash non-empty,
         ttl_remaining_s >= 0.
    Post: immutable.

    Felder:
      - is_duplicate: bool — True wenn Order bereits aktiv (innerhalb TTL).
      - client_order_id: str — Broker-stable Order-Identifier (primary key).
      - order_hash: str — SHA256 ueber order_payload (secondary check fuer
                          Audit / Bug-Detection).
      - original_seen_at: Optional[float] — first_seen_at falls Duplikat,
                                            sonst None.
      - ttl_remaining_s: float — verbleibende TTL in Sekunden (0.0 wenn neu).
      - reason: str — kurze Begruendung ("first_seen" / "duplicate_active" /
                       "duplicate_expired_renewed").
      - timestamp: float — Zeitpunkt der Pruefung.
    """

    is_duplicate: bool
    client_order_id: str
    order_hash: str
    original_seen_at: Optional[float]
    ttl_remaining_s: float
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.client_order_id:
            raise ValueError("client_order_id required")
        if not self.order_hash:
            raise ValueError("order_hash required")
        if self.ttl_remaining_s < 0:
            raise ValueError("ttl_remaining_s must be >= 0")


@dataclass(frozen=True)
class OrderRecord:
    """Frozen interner Datensatz pro getrackt'er Order.

    Pre: client_order_id non-empty, order_hash non-empty, strategy_id
         non-empty, first_seen_at > 0, ttl_s > 0, hit_count >= 0.
         last_access_at default = first_seen_at, must be >= first_seen_at.
    Post: immutable. Updates erzeugen neuen OrderRecord.

    Felder:
      - client_order_id: Broker-stable Order-Identifier (primary key).
      - order_hash: SHA256-Hash des order_payload (secondary, audit-trail).
      - first_seen_at: Erstmaliges Auftreten (TTL-Anker, unveraendert).
      - hit_count: Anzahl bisheriger Duplikat-Hits.
      - ttl_s: TTL-Dauer in Sekunden (Anker fuer Expiry).
      - strategy_id: Strategy-Owner der Order (Multi-Strategy-Audit).
      - last_access_at: Zeitpunkt des letzten Zugriffs (Hit oder first_seen).
                        Wird bei jedem Hit aktualisiert. Steuert True-LRU-
                        Eviction (eldest-by-last_access). Default =
                        first_seen_at.
    """

    client_order_id: str
    order_hash: str
    first_seen_at: float
    hit_count: int
    ttl_s: float
    strategy_id: str
    last_access_at: float = field(default=-1.0)

    def __post_init__(self) -> None:
        if not self.client_order_id:
            raise ValueError("client_order_id required")
        if not self.order_hash:
            raise ValueError("order_hash required")
        if not self.strategy_id:
            raise ValueError("strategy_id required")
        if self.first_seen_at <= 0:
            raise ValueError("first_seen_at must be > 0")
        if self.ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        if self.hit_count < 0:
            raise ValueError("hit_count must be >= 0")
        # Backward-compatible default: if last_access_at not provided
        # (-1.0 sentinel), set it to first_seen_at via object.__setattr__
        # (frozen dataclass workaround).
        if self.last_access_at == -1.0:
            object.__setattr__(self, "last_access_at", self.first_seen_at)
        elif self.last_access_at < self.first_seen_at:
            raise ValueError("last_access_at must be >= first_seen_at")

    def is_expired(self, now: float) -> bool:
        return (now - self.first_seen_at) >= self.ttl_s

    def remaining_s(self, now: float) -> float:
        return max(0.0, self.ttl_s - (now - self.first_seen_at))


def _default_hash(payload: Any) -> str:
    """Default-Hash: SHA256 ueber sorted-json-dump des order_payload.

    Ordnungsunabhaengig fuer dict-payloads (z.B. {symbol, side, qty, price}
    egal in welcher Reihenfolge). Fallback auf repr() bei nicht-JSON-
    serialisierbaren Inputs (z.B. Decimal — wird via default=repr abgefangen).
    """
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            default=repr,
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        canonical = repr(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class KPMDeduplicationEngine:
    """Trade-Order-Idempotency-Engine mit client_order_id + Hash + TTL.

    Pre: default_ttl_s > 0, max_entries >= 1.
    Post: thread-safe (RLock); True-LRU-Eviction (last_access_at) wenn
          max_entries erreicht; first_seen_at unveraendert bei hit (nur
          hit_count + last_access_at steigen); nach TTL-Ablauf wird Eintrag
          bei naechstem check() verworfen und als neu (first_seen)
          klassifiziert.

    Bio-Aequivalent: B-Cell-Memory mit Halbwertszeit (TTL) +
                     Recall-Frequency-Selection (LRU).
    """

    def __init__(
        self,
        default_ttl_s: float = 300.0,
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
        # Index by client_order_id (primary key, broker-stable).
        self._records: dict[str, OrderRecord] = {}
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
        client_order_id: str,
        order_payload: dict,
        strategy_id: str,
        ttl_s: Optional[float] = None,
    ) -> TradeDedupResult:
        """Pruefe ob Trade-Order Duplikat. Markiere als gesehen bei first-time
        / nach Ablauf.

        Pre: client_order_id non-empty, strategy_id non-empty,
             ttl_s None oder > 0.
        Post: bei is_duplicate=False wurde ein neuer OrderRecord persistiert
              (oder ein expired'er ueberschrieben); bei is_duplicate=True
              wurde hit_count um 1 erhoeht und last_access_at aktualisiert
              (True-LRU).

        Domain-Note: client_order_id ist primary key. order_payload-Hash
        dient als Audit-Sekundaer-Check — wird in TradeDedupResult.order_hash
        zurueckgegeben fuer MiFID-RTS-25 retention. Wenn dieselbe
        client_order_id mit divergentem payload-Hash erscheint, ist das
        Strategy-Bug-Signal (Caller sollte order_hash gegen
        original_record vergleichen, falls noetig).
        """
        if not client_order_id:
            raise ValueError("client_order_id required")
        if not strategy_id:
            raise ValueError("strategy_id required")
        if ttl_s is not None and ttl_s <= 0:
            raise ValueError("ttl_s must be > 0 when provided")
        effective_ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        order_hash = self._compute_hash(order_payload)
        now = time.time()

        with self._lock:
            existing = self._records.get(client_order_id)
            if existing is not None:
                if not existing.is_expired(now):
                    # Active duplicate: bump hit_count, keep first_seen_at,
                    # keep order_hash + strategy_id of original (audit-trail),
                    # update last_access_at for True-LRU.
                    updated = OrderRecord(
                        client_order_id=existing.client_order_id,
                        order_hash=existing.order_hash,
                        first_seen_at=existing.first_seen_at,
                        hit_count=existing.hit_count + 1,
                        ttl_s=existing.ttl_s,
                        strategy_id=existing.strategy_id,
                        last_access_at=now,
                    )
                    self._records[client_order_id] = updated
                    self._hits += 1
                    return TradeDedupResult(
                        is_duplicate=True,
                        client_order_id=client_order_id,
                        order_hash=existing.order_hash,
                        original_seen_at=existing.first_seen_at,
                        ttl_remaining_s=updated.remaining_s(now),
                        reason="duplicate_active",
                        timestamp=now,
                    )
                # Expired: drop and treat as new.
                del self._records[client_order_id]
                self._expired_purges += 1
                self._evict_if_needed()
                self._records[client_order_id] = OrderRecord(
                    client_order_id=client_order_id,
                    order_hash=order_hash,
                    first_seen_at=now,
                    hit_count=0,
                    ttl_s=effective_ttl,
                    strategy_id=strategy_id,
                    last_access_at=now,
                )
                self._misses += 1
                return TradeDedupResult(
                    is_duplicate=False,
                    client_order_id=client_order_id,
                    order_hash=order_hash,
                    original_seen_at=None,
                    ttl_remaining_s=effective_ttl,
                    reason="duplicate_expired_renewed",
                    timestamp=now,
                )

            # First time seen.
            self._evict_if_needed()
            self._records[client_order_id] = OrderRecord(
                client_order_id=client_order_id,
                order_hash=order_hash,
                first_seen_at=now,
                hit_count=0,
                ttl_s=effective_ttl,
                strategy_id=strategy_id,
                last_access_at=now,
            )
            self._misses += 1
            return TradeDedupResult(
                is_duplicate=False,
                client_order_id=client_order_id,
                order_hash=order_hash,
                original_seen_at=None,
                ttl_remaining_s=effective_ttl,
                reason="first_seen",
                timestamp=now,
            )

    def _evict_if_needed(self) -> None:
        """True-LRU-Eviction by last_access_at (eldest-by-last_access first).

        Pre: lock held by caller.
        Post: hot duplicate records (recently accessed via retries) are
              protected from eviction; truly idle records are evicted first.

        W20-P2 Baseline (post-FIFO-Fix): True-LRU-by-last_access. Schuetzt
        Hot-Orders die gerade re-tried werden vor Eviction durch idle-
        Background-Orders.
        """
        while len(self._records) >= self.max_entries:
            eldest_key = min(
                self._records,
                key=lambda k: self._records[k].last_access_at,
            )
            del self._records[eldest_key]
            self._evictions += 1

    def force_expire(self, client_order_id: str) -> bool:
        """Manueller Override: erzwinge Expiry eines Records.

        Returns True wenn Record existierte und entfernt wurde, sonst False.
        Use-case: Order-Cancel via Broker — TTL-Window soll nicht weiter
        blocken.
        """
        if not client_order_id:
            raise ValueError("client_order_id required")
        with self._lock:
            if client_order_id in self._records:
                del self._records[client_order_id]
                return True
            return False

    def cleanup_expired(self) -> int:
        """Purge alle Records mit (now - first_seen_at) >= ttl_s.

        Returns Anzahl entfernter Records. Kann periodisch aufgerufen werden
        (z.B. aus Background-Janitor) um Stale-Records vor max_entries-
        Eviction zu purgen.
        """
        now = time.time()
        with self._lock:
            expired_keys = [
                k for k, rec in self._records.items() if rec.is_expired(now)
            ]
            for k in expired_keys:
                del self._records[k]
            self._expired_purges += len(expired_keys)
            return len(expired_keys)

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

    def query_by_strategy(self, strategy_id: str) -> tuple[OrderRecord, ...]:
        """Snapshot aller Records einer Strategy (Multi-Strategy-Audit).

        Pre: strategy_id non-empty.
        Post: tuple (immutable) — kein Live-View. Enthaelt potenziell
              expired Records (cleanup_expired() davor aufrufen wenn noetig).
        """
        if not strategy_id:
            raise ValueError("strategy_id required")
        with self._lock:
            return tuple(
                r for r in self._records.values()
                if r.strategy_id == strategy_id
            )

    def list_active(self) -> tuple[OrderRecord, ...]:
        """Snapshot aller aktiven (nicht-expired) Records.

        Post: tuple (immutable). Cleanup ist nicht implizit; expired Records
              koennen im internen Dict enthalten sein bis cleanup_expired()
              oder check() sie entfernt. Diese Methode filtert sie aus.
        """
        now = time.time()
        with self._lock:
            return tuple(
                r for r in self._records.values()
                if not r.is_expired(now)
            )


# CRUX-MK
