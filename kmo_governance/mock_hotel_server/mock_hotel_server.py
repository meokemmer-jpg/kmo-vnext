"""KMO Mock-Hotel-Server Core [CRUX-MK].

Welle-9zeta E2E Pre-Production-Modul. Simuliert REAL-Apaleo-PMS-API in-Process
fuer Apaleo-Auth-Adapter-Tests (Subagent-A laeuft parallel).

Architektur:
  - 4 unabhaengige Komponenten (StateMachine, Storage, OAuth2, RateLimiter)
  - Alle race-safe via threading.Lock
  - Hotel-ID-Isolation (Multi-Tenancy) wird in Storage durchgesetzt
  - Token-Bucket-Algorithmus (10 tokens/s, max 100, deterministic refill)

Pre-Conditions (modul-weit):
  - hotel_id: non-empty string, ASCII-safe
  - booking_id: UUID4-string

Post-Conditions (modul-weit):
  - Idempotenz: Concurrent create_booking erzeugt distinct booking_ids
  - Path-Isolation: hotel-A sieht keine hotel-B-Bookings
  - Token-Lifecycle: generate -> validate -> refresh -> revoke (404 nach revoke)
  - Rate-Limit: Bei erschoepftem Bucket -> 429-Response (success=False, retry_after_ms>0)

Bio-Aequivalent: Phantom-Tissue-Probe (In-Vitro-Modell). Anorg: A-19 Test-Wafer.
"""

from __future__ import annotations

import copy
import enum
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Booking-States + State-Machine
# ---------------------------------------------------------------------------


class BookingState(str, enum.Enum):
    """Booking-Lifecycle-States.

    Terminal-States: CHECKED_OUT, CANCELLED, NO_SHOW.
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# Valid-Transitions-Tabelle (from -> set of allowed to-states).
# Terminal-States haben leere Sets (keine ausgehenden Transitions).
_VALID_TRANSITIONS: dict[BookingState, frozenset[BookingState]] = {
    BookingState.PENDING: frozenset(
        {BookingState.CONFIRMED, BookingState.CANCELLED}
    ),
    BookingState.CONFIRMED: frozenset(
        {
            BookingState.CHECKED_IN,
            BookingState.CANCELLED,
            BookingState.NO_SHOW,
        }
    ),
    BookingState.CHECKED_IN: frozenset({BookingState.CHECKED_OUT}),
    BookingState.CHECKED_OUT: frozenset(),  # terminal
    BookingState.CANCELLED: frozenset(),  # terminal
    BookingState.NO_SHOW: frozenset(),  # terminal
}


class InvalidStateTransitionError(Exception):
    """Raised wenn versucht wird ungueltige Booking-State-Transition auszufuehren."""

    def __init__(
        self,
        from_state: BookingState,
        to_state: BookingState,
        booking_id: Optional[str] = None,
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.booking_id = booking_id
        msg = (
            f"Invalid booking-state transition: {from_state.value} -> "
            f"{to_state.value}"
        )
        if booking_id:
            msg += f" (booking_id={booking_id!r})"
        super().__init__(msg)


@dataclass
class MockHotelStateMachine:
    """Booking-State-Machine mit Validate + Apply.

    Pre-Conditions:
        - booking dict has key "state" with valid BookingState (or string thereof)

    Post-Conditions:
        - validate_transition: True wenn transition in _VALID_TRANSITIONS, sonst False
        - apply_transition: returns updated-booking-dict oder raised InvalidStateTransitionError

    Threadsafe: Stateless-Modell (keine Instance-State, nur Klassen-Konstanten).
    """

    def validate_transition(
        self,
        from_state: BookingState | str,
        to_state: BookingState | str,
    ) -> bool:
        """Returns True wenn transition zulaessig.

        Pre: from_state, to_state sind BookingState-Members oder gueltige string-keys.
        Post: True/False (raised nichts).
        """
        from_s = self._coerce(from_state)
        to_s = self._coerce(to_state)
        if from_s is None or to_s is None:
            return False
        return to_s in _VALID_TRANSITIONS[from_s]

    def apply_transition(
        self,
        booking: dict,
        to_state: BookingState | str,
    ) -> dict:
        """Wendet Transition an. Raised InvalidStateTransitionError bei ungueltig.

        Pre: booking ist dict mit "state" key + "booking_id" key (optional).
        Post: returns deepcopy mit aktualisiertem state + state_changed_at-timestamp.
        """
        if not isinstance(booking, dict):
            raise TypeError("booking must be dict")
        if "state" not in booking:
            raise ValueError("booking must have 'state' key")
        from_s = self._coerce(booking["state"])
        to_s = self._coerce(to_state)
        if from_s is None:
            raise ValueError(
                f"booking state is invalid: {booking['state']!r}"
            )
        if to_s is None:
            raise ValueError(f"to_state is invalid: {to_state!r}")
        if to_s not in _VALID_TRANSITIONS[from_s]:
            raise InvalidStateTransitionError(
                from_state=from_s,
                to_state=to_s,
                booking_id=booking.get("booking_id"),
            )
        updated = copy.deepcopy(booking)
        updated["state"] = to_s.value
        updated["state_changed_at"] = time.time()
        return updated

    @staticmethod
    def _coerce(value: BookingState | str) -> Optional[BookingState]:
        """BookingState oder string -> BookingState. None bei ungueltig."""
        if isinstance(value, BookingState):
            return value
        if isinstance(value, str):
            try:
                return BookingState(value)
            except ValueError:
                return None
        return None


# ---------------------------------------------------------------------------
# Storage (Multi-Tenant, Path-Isoliert via hotel_id-Scoping)
# ---------------------------------------------------------------------------


class MockHotelStorage:
    """In-Memory-Storage mit hotel_id-Isolation (Multi-Tenancy).

    Pre-Conditions:
        - hotel_id: non-empty string fuer alle Operations
        - booking_data: dict (wird tief-kopiert beim Speichern)

    Post-Conditions:
        - create_booking: erzeugt UUID4-booking_id, schreibt nach hotel_id-scope
        - get_booking: returns deepcopy oder None
        - hotel-ID-Isolation: get/list/update/delete sehen nur eigenes hotel_id
        - Concurrent create_booking erzeugt distinct booking_ids (race-safe via Lock)
    """

    def __init__(self) -> None:
        # Struktur: hotel_id -> booking_id -> booking_dict
        self._store: dict[str, dict[str, dict]] = {}
        self._lock = threading.RLock()

    def create_booking(self, hotel_id: str, booking_data: dict) -> str:
        """Erzeugt neue Booking. Returns booking_id (UUID4-string).

        Pre: hotel_id non-empty, booking_data is dict.
        Post: booking_id ist neu (Lock-protected gegen Race).
        """
        if not hotel_id or not isinstance(hotel_id, str):
            raise ValueError("hotel_id must be non-empty string")
        if not isinstance(booking_data, dict):
            raise TypeError("booking_data must be dict")
        booking_id = str(uuid.uuid4())
        now = time.time()
        record = copy.deepcopy(booking_data)
        record["booking_id"] = booking_id
        record["hotel_id"] = hotel_id
        record.setdefault("state", BookingState.PENDING.value)
        record["created_at"] = now
        record["updated_at"] = now
        with self._lock:
            self._store.setdefault(hotel_id, {})[booking_id] = record
        return booking_id

    def get_booking(
        self, hotel_id: str, booking_id: str
    ) -> Optional[dict]:
        """Returns deepcopy der Booking oder None wenn nicht vorhanden.

        Pre: hotel_id, booking_id non-empty.
        Post: None wenn hotel_id-scope leer ODER booking_id nicht in scope.
              hotel-Isolation enforced (kein Cross-Tenant-Leak).
        """
        if not hotel_id or not booking_id:
            return None
        with self._lock:
            scope = self._store.get(hotel_id)
            if scope is None:
                return None
            booking = scope.get(booking_id)
            if booking is None:
                return None
            return copy.deepcopy(booking)

    def update_booking(
        self, hotel_id: str, booking_id: str, updates: dict
    ) -> bool:
        """Patcht booking. Returns True wenn aktualisiert, False wenn nicht gefunden.

        Pre: updates ist dict (wird in record gemerged, hotel_id+booking_id immutable).
        Post: updated_at wird gesetzt. Mutation ist atomar via Lock.
        """
        if not isinstance(updates, dict):
            raise TypeError("updates must be dict")
        with self._lock:
            scope = self._store.get(hotel_id)
            if scope is None or booking_id not in scope:
                return False
            record = scope[booking_id]
            for key, value in updates.items():
                # Immutable: hotel_id, booking_id, created_at
                if key in ("hotel_id", "booking_id", "created_at"):
                    continue
                record[key] = value
            record["updated_at"] = time.time()
            return True

    def list_bookings(
        self,
        hotel_id: str,
        page: int = 0,
        page_size: int = 50,
    ) -> dict:
        """Returns paginiertes Listing fuer hotel_id.

        Pre: page >= 0, page_size > 0.
        Post: dict mit keys total, page, page_size, items (list of deepcopies).
              hotel-Isolation enforced.
        """
        if page < 0:
            raise ValueError("page must be >= 0")
        if page_size <= 0:
            raise ValueError("page_size must be > 0")
        with self._lock:
            scope = self._store.get(hotel_id, {})
            # Sortier-Stabilitaet: by created_at, then booking_id
            all_items = sorted(
                scope.values(),
                key=lambda b: (b.get("created_at", 0.0), b.get("booking_id", "")),
            )
            total = len(all_items)
            start = page * page_size
            end = start + page_size
            page_items = [copy.deepcopy(b) for b in all_items[start:end]]
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": page_items,
            }

    def delete_booking(self, hotel_id: str, booking_id: str) -> bool:
        """Loescht booking. Returns True wenn entfernt, False wenn nicht gefunden.

        Pre: hotel_id, booking_id non-empty.
        Post: hotel-Isolation enforced.
        """
        with self._lock:
            scope = self._store.get(hotel_id)
            if scope is None or booking_id not in scope:
                return False
            del scope[booking_id]
            return True

    def get_storage_stats(self) -> dict[str, int]:
        """Returns booking-counts pro hotel_id. Read-only-Snapshot."""
        with self._lock:
            return {
                hotel_id: len(scope)
                for hotel_id, scope in self._store.items()
            }


# ---------------------------------------------------------------------------
# OAuth2-Provider
# ---------------------------------------------------------------------------


class TokenInvalidError(Exception):
    """Raised wenn Token nicht existiert, expired oder revoked ist."""


@dataclass
class _StoredToken:
    """Internal Token-Record."""

    access_token: str
    refresh_token: str
    client_id: str
    issued_at: float
    expires_at: float
    revoked: bool = False


class MockOAuth2Provider:
    """OAuth2 Token-Lifecycle (generate/validate/refresh/revoke).

    Pre-Conditions:
        - client_id, client_secret: non-empty strings (Mock akzeptiert beliebige Werte)
        - default_ttl_s: > 0

    Post-Conditions:
        - generate_token: liefert dict {access_token, refresh_token, expires_in, token_type}
        - validate_token: True wenn nicht revoked + nicht expired
        - revoke_token: True wenn revoked, False wenn unbekannt
        - refresh: liefert neues Token-Set, invalidiert refresh_token (one-shot)
    """

    TOKEN_TYPE = "Bearer"

    def __init__(self, default_ttl_s: int = 3600) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        self.default_ttl_s = default_ttl_s
        # access_token -> _StoredToken
        self._tokens: dict[str, _StoredToken] = {}
        # refresh_token -> access_token (fuer schnelles Refresh-Lookup)
        self._refresh_index: dict[str, str] = {}
        self._lock = threading.RLock()

    def generate_token(
        self,
        client_id: str,
        client_secret: str,
        ttl_s: Optional[int] = None,
    ) -> dict:
        """Erzeugt neues Token-Paar. client_secret wird Mock-haft akzeptiert (kein Hash).

        Pre: client_id non-empty.
        Post: Token-Record im Store, refresh-Index aktualisiert.
        """
        if not client_id or not isinstance(client_id, str):
            raise ValueError("client_id must be non-empty string")
        if not isinstance(client_secret, str) or not client_secret:
            raise ValueError("client_secret must be non-empty string")
        ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = time.time()
        record = _StoredToken(
            access_token=access,
            refresh_token=refresh,
            client_id=client_id,
            issued_at=now,
            expires_at=now + ttl,
        )
        with self._lock:
            self._tokens[access] = record
            self._refresh_index[refresh] = access
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": ttl,
            "token_type": self.TOKEN_TYPE,
        }

    def validate_token(self, access_token: str) -> bool:
        """Returns True wenn Token-existiert + not-revoked + not-expired.

        Pre: access_token string (None/empty -> False).
        Post: deterministisch.
        """
        if not access_token or not isinstance(access_token, str):
            return False
        with self._lock:
            record = self._tokens.get(access_token)
            if record is None:
                return False
            if record.revoked:
                return False
            if time.time() >= record.expires_at:
                return False
            return True

    def revoke_token(self, access_token: str) -> bool:
        """Markiert Token als revoked. Returns True wenn aktion ausgefuehrt.

        Pre: access_token string.
        Post: validate_token() liefert False fuer dieses Token.
              refresh_token bleibt invalid (refresh schlaegt fehl).
        """
        if not access_token:
            return False
        with self._lock:
            record = self._tokens.get(access_token)
            if record is None:
                return False
            if record.revoked:
                return False
            record.revoked = True
            return True

    def refresh(
        self,
        refresh_token: str,
        ttl_s: Optional[int] = None,
    ) -> dict:
        """Erzeugt neues Token-Paar via refresh_token (one-shot, alter wird invalidiert).

        Pre: refresh_token non-empty.
        Post: alter access+refresh werden revoked, neues Paar zurueckgegeben.
        Raised TokenInvalidError wenn refresh_token unbekannt oder gehoert zu revoked-token.
        """
        if not refresh_token or not isinstance(refresh_token, str):
            raise TokenInvalidError("refresh_token required")
        with self._lock:
            old_access = self._refresh_index.get(refresh_token)
            if old_access is None:
                raise TokenInvalidError("refresh_token unknown or already used")
            old_record = self._tokens.get(old_access)
            if old_record is None or old_record.revoked:
                # Cleanup orphaned index
                self._refresh_index.pop(refresh_token, None)
                raise TokenInvalidError("refresh_token attached to revoked token")
            # Invalidate alter Token + refresh-Index
            old_record.revoked = True
            self._refresh_index.pop(refresh_token, None)
            client_id = old_record.client_id
        return self.generate_token(
            client_id=client_id,
            client_secret="<refreshed>",  # Mock akzeptiert
            ttl_s=ttl_s,
        )

    def lookup_status(self, access_token: str) -> str:
        """Diagnostik: liefert string-Status fuer Logging.

        Returns: "valid" | "expired" | "revoked" | "unknown".
        """
        if not access_token:
            return "unknown"
        with self._lock:
            record = self._tokens.get(access_token)
            if record is None:
                return "unknown"
            if record.revoked:
                return "revoked"
            if time.time() >= record.expires_at:
                return "expired"
            return "valid"


# ---------------------------------------------------------------------------
# Rate-Limiter (Token-Bucket pro hotel_id)
# ---------------------------------------------------------------------------


class RateLimitExceededError(Exception):
    """Raised wenn try_consume() exhaustively scheitert (selten genutzt; meist Boolean-API)."""


@dataclass
class _Bucket:
    """Token-Bucket pro hotel_id."""

    tokens: float
    max_tokens: float
    refill_per_s: float
    last_refill: float


class MockRateLimiter:
    """Token-Bucket-Algorithmus mit Bucket pro hotel_id.

    Pre-Conditions:
        - tokens_per_second: > 0 (default 10)
        - max_tokens: > 0 (default 100)

    Post-Conditions:
        - try_consume: liefert (success: bool, retry_after_ms: int)
        - get_remaining: liefert int (rounded-down)
        - Race-safe via threading.Lock
        - Refill ist deterministisch (lazy, beim try_consume)
    """

    def __init__(
        self,
        tokens_per_second: float = 10.0,
        max_tokens: float = 100.0,
    ) -> None:
        if tokens_per_second <= 0:
            raise ValueError("tokens_per_second must be > 0")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be > 0")
        self.tokens_per_second = float(tokens_per_second)
        self.max_tokens = float(max_tokens)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, hotel_id: str) -> _Bucket:
        """Lazy bucket-creation. NICHT lock-protected (Caller haelt Lock)."""
        bucket = self._buckets.get(hotel_id)
        if bucket is None:
            bucket = _Bucket(
                tokens=self.max_tokens,
                max_tokens=self.max_tokens,
                refill_per_s=self.tokens_per_second,
                last_refill=time.monotonic(),
            )
            self._buckets[hotel_id] = bucket
        return bucket

    def _refill(self, bucket: _Bucket, now: float) -> None:
        """Lazy-refill basierend auf elapsed-time. Nicht-lock-protected."""
        elapsed = now - bucket.last_refill
        if elapsed <= 0:
            return
        added = elapsed * bucket.refill_per_s
        if added <= 0:
            return
        bucket.tokens = min(bucket.max_tokens, bucket.tokens + added)
        bucket.last_refill = now

    def try_consume(
        self,
        hotel_id: str,
        n_tokens: int = 1,
    ) -> tuple[bool, int]:
        """Versucht n_tokens zu konsumieren.

        Pre: hotel_id non-empty, n_tokens > 0.
        Post: (True, 0) wenn erfolgreich.
              (False, retry_after_ms) wenn Bucket leer (retry_after_ms > 0).
        """
        if not hotel_id or not isinstance(hotel_id, str):
            raise ValueError("hotel_id must be non-empty string")
        if n_tokens <= 0:
            raise ValueError("n_tokens must be > 0")
        if n_tokens > self.max_tokens:
            # Niemals erfuellbar (Bucket ist immer kleiner als Anfrage)
            return (False, int((n_tokens / self.tokens_per_second) * 1000))
        with self._lock:
            now = time.monotonic()
            bucket = self._get_or_create(hotel_id)
            self._refill(bucket, now)
            if bucket.tokens >= n_tokens:
                bucket.tokens -= n_tokens
                return (True, 0)
            # Berechne, wie lange bis genug tokens zur Verfuegung stehen
            deficit = n_tokens - bucket.tokens
            retry_after_s = deficit / bucket.refill_per_s
            retry_after_ms = max(1, int(retry_after_s * 1000))
            return (False, retry_after_ms)

    def get_remaining(self, hotel_id: str) -> int:
        """Returns aktuell verfuegbare tokens (rounded-down).

        Pre: hotel_id non-empty.
        Post: 0..max_tokens.
        """
        if not hotel_id:
            return 0
        with self._lock:
            now = time.monotonic()
            bucket = self._get_or_create(hotel_id)
            self._refill(bucket, now)
            return int(bucket.tokens)

    def reset(self, hotel_id: str) -> None:
        """Reset bucket fuer hotel_id auf max_tokens. Test-helper."""
        with self._lock:
            bucket = self._get_or_create(hotel_id)
            bucket.tokens = bucket.max_tokens
            bucket.last_refill = time.monotonic()


# CRUX-MK
