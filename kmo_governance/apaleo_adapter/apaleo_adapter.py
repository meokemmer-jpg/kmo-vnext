"""KMO Apaleo-Adapter [CRUX-MK].

Welle-9-zeta Phase-5 Modul 5.1: External-Hotel-Stack-Anbindung (SKELETON).

Bio-Aequivalent: Membran-Rezeptor-Komplex. Externe Signal-Bindung mit
Internalisierung (Endocytose-Pattern). Multi-Tenancy via Hotel-Kompartimentierung.

Anorg-Mapping: A-04 Quine Self-Boot (Token-Lifecycle = Selbst-Reproduktion),
A-26 Templated-Crystal-Growth (Mock-Server als Templated-Wachstumsmuster).

Status: SKELETON. KEINE Real-Apaleo-Credentials. Pflicht-Phronesis-Sperr-Liste P6 #5
fuer Production-Aktivierung. Pre-Action-Verification-Pflicht (CLAUDE.md §0).

Komponenten:
  - Exceptions: ApaleoAuthError, ApaleoRateLimitError, ApaleoNetworkError
  - ApaleoTokenState: Frozen-Dataclass (Immutable Auth-State)
  - ApaleoMockAuth: OAuth2-Token-Lifecycle (get/refresh/expire/validate)
  - ApaleoBookingAdapter: CRUD mit hotel_id-Scoping (Multi-Tenancy enforced)
  - ApaleoErrorHandler: Retry-on-5xx + Exponential-Backoff + Rate-Limit-Header
  - ApaleoMockServer: In-Memory-Mock mit Configurable success_rate / latency / status
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------- Exceptions ----------------


class ApaleoAuthError(Exception):
    """Raised on invalid credentials / expired token / refresh failure."""


class ApaleoRateLimitError(Exception):
    """Raised on HTTP 429. Carries retry_after seconds."""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = float(retry_after)


class ApaleoNetworkError(Exception):
    """Raised on simulated network errors / 5xx after max retries."""


# ---------------- Frozen Auth-State ----------------


@dataclass(frozen=True)
class ApaleoTokenState:
    """Immutable OAuth2-Token-State (Frozen-Dataclass-Pattern).

    Pre:
        - access_token: non-empty str
        - refresh_token: non-empty str
        - expires_at: future timestamp (caller-validated)
        - issued_at: <= expires_at
    Post:
        - All fields immutable
        - provenance_hash deterministic ueber (access_token, issued_at)
    """

    access_token: str
    refresh_token: str
    issued_at: float
    expires_at: float
    provenance_hash: str

    @staticmethod
    def make(
        access_token: str,
        refresh_token: str,
        issued_at: float,
        expires_at: float,
    ) -> "ApaleoTokenState":
        if not access_token:
            raise ValueError("access_token required")
        if not refresh_token:
            raise ValueError("refresh_token required")
        if expires_at <= issued_at:
            raise ValueError("expires_at must be > issued_at")
        h = hashlib.sha256(
            f"{access_token}|{issued_at}".encode("utf-8")
        ).hexdigest()[:16]
        return ApaleoTokenState(
            access_token=access_token,
            refresh_token=refresh_token,
            issued_at=issued_at,
            expires_at=expires_at,
            provenance_hash=h,
        )


# ---------------- Mock OAuth2 ----------------


class ApaleoMockAuth:
    """Mock-OAuth2-Token-Lifecycle (KEINE Real-Apaleo-Credentials).

    Pre:
        - default_ttl_s > 0
        - client_id non-empty
    Post:
        - get_token() returns ApaleoTokenState (cached if valid)
        - refresh_token() returns NEW ApaleoTokenState (different access_token)
        - expire_token(t) markiert Token als invalid
        - is_token_valid(t) prueft Cache + Expiry + Revocation

    Thread-safety: All public methods sind threading.RLock-guarded
    (Concurrent-Refresh-Idempotency).
    """

    def __init__(
        self,
        client_id: str = "kmo-mock-client",
        client_secret: str = "kmo-mock-secret",
        default_ttl_s: float = 3600.0,
    ) -> None:
        if not client_id:
            raise ValueError("client_id required")
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        self.client_id = client_id
        self.client_secret = client_secret
        self.default_ttl_s = float(default_ttl_s)
        self._lock = threading.RLock()
        self._current_token: Optional[ApaleoTokenState] = None
        # Revocation-set: access_tokens marked expired explicitly
        self._revoked: set[str] = set()
        # Audit: count get/refresh calls fuer Caching-Test
        self._auth_call_count = 0

    def get_token(self) -> ApaleoTokenState:
        """Returns cached valid token, else mints new one.

        Post: returned token is_token_valid(t) == True at return-time.
        """
        with self._lock:
            if self._current_token and self._is_valid_internal(
                self._current_token
            ):
                return self._current_token
            # Mint new
            self._auth_call_count += 1
            now = time.time()
            access = f"mock-access-{secrets.token_urlsafe(16)}"
            refresh = f"mock-refresh-{secrets.token_urlsafe(16)}"
            tok = ApaleoTokenState.make(
                access_token=access,
                refresh_token=refresh,
                issued_at=now,
                expires_at=now + self.default_ttl_s,
            )
            self._current_token = tok
            return tok

    def refresh_token(self, refresh_token: str) -> ApaleoTokenState:
        """Exchanges refresh_token for new access_token.

        Pre: refresh_token must match current token's refresh_token.
        Post:
            - new access_token != old access_token
            - new ApaleoTokenState replaces cache
        Raises: ApaleoAuthError if refresh_token invalid.
        """
        if not refresh_token:
            raise ApaleoAuthError("refresh_token required")
        with self._lock:
            cur = self._current_token
            if cur is None or cur.refresh_token != refresh_token:
                raise ApaleoAuthError("invalid refresh_token")
            self._auth_call_count += 1
            now = time.time()
            new_access = f"mock-access-{secrets.token_urlsafe(16)}"
            new_refresh = f"mock-refresh-{secrets.token_urlsafe(16)}"
            new_tok = ApaleoTokenState.make(
                access_token=new_access,
                refresh_token=new_refresh,
                issued_at=now,
                expires_at=now + self.default_ttl_s,
            )
            # Old token implicit-revoked
            self._revoked.add(cur.access_token)
            self._current_token = new_tok
            return new_tok

    def expire_token(self, access_token: str) -> bool:
        """Marks access_token as revoked (immediate invalidation).

        Returns: True if token was current (or known), False otherwise.
        """
        if not access_token:
            return False
        with self._lock:
            self._revoked.add(access_token)
            if (
                self._current_token
                and self._current_token.access_token == access_token
            ):
                # Mark cache stale by clearing
                self._current_token = None
                return True
            return access_token in self._revoked

    def is_token_valid(self, access_token: str) -> bool:
        """True iff token matches current state, not revoked, not expired."""
        if not access_token:
            return False
        with self._lock:
            if access_token in self._revoked:
                return False
            cur = self._current_token
            if cur is None or cur.access_token != access_token:
                return False
            return self._is_valid_internal(cur)

    def auth_call_count(self) -> int:
        """Audit-Helper: counts get/refresh-calls fuer Caching-Test."""
        with self._lock:
            return self._auth_call_count

    def authenticate(
        self, client_id: str, client_secret: str
    ) -> ApaleoTokenState:
        """Initial-Authenticate-Pfad mit explicit Credentials.

        Raises: ApaleoAuthError on credential mismatch.
        """
        if client_id != self.client_id or client_secret != self.client_secret:
            raise ApaleoAuthError("invalid credentials")
        return self.get_token()

    @staticmethod
    def _is_valid_internal(tok: ApaleoTokenState) -> bool:
        return time.time() < tok.expires_at


# ---------------- Mock Server ----------------


class ApaleoMockServer:
    """In-Memory-Mock-Server fuer Apaleo-API-Responses.

    Configurable:
      - success_rate (0.0-1.0): probability of 200 OK
      - latency_ms: artificial sleep before response
      - rate_limit_remaining: count down per call; raises 429 at 0
      - forced_status_codes: list of status codes to return in sequence

    Thread-safe via RLock.
    """

    def __init__(
        self,
        success_rate: float = 1.0,
        latency_ms: float = 0.0,
        rate_limit_remaining: int = 1000,
        rate_limit_retry_after: float = 1.0,
    ) -> None:
        if not 0.0 <= success_rate <= 1.0:
            raise ValueError("success_rate must be in [0.0, 1.0]")
        self.success_rate = success_rate
        self.latency_ms = float(latency_ms)
        self.rate_limit_remaining = int(rate_limit_remaining)
        self.rate_limit_retry_after = float(rate_limit_retry_after)
        self._lock = threading.RLock()
        self._bookings: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        # Forced-status sequence for retry tests
        self._forced_status_codes: list[int] = []
        # Auth-token gate (any non-empty token accepted in mock)
        self._require_auth = True

    def set_forced_status_sequence(self, codes: list[int]) -> None:
        """Force next N calls to return given status codes (then back to normal)."""
        with self._lock:
            self._forced_status_codes = list(codes)

    def _consume_forced_status(self) -> Optional[int]:
        with self._lock:
            if self._forced_status_codes:
                return self._forced_status_codes.pop(0)
            return None

    def _check_rate_limit(self) -> None:
        with self._lock:
            if self.rate_limit_remaining <= 0:
                raise ApaleoRateLimitError(
                    "rate limit exceeded",
                    retry_after=self.rate_limit_retry_after,
                )
            self.rate_limit_remaining -= 1

    def _sleep_latency(self) -> None:
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000.0)

    def _check_auth(self, access_token: Optional[str]) -> None:
        if self._require_auth and not access_token:
            raise ApaleoAuthError("missing access_token")

    def _maybe_inject_failure(self) -> None:
        forced = self._consume_forced_status()
        if forced is not None:
            if forced == 429:
                raise ApaleoRateLimitError(
                    "forced 429", retry_after=self.rate_limit_retry_after
                )
            if forced == 401:
                raise ApaleoAuthError("forced 401")
            if 500 <= forced <= 599:
                raise ApaleoNetworkError(f"forced {forced}")
            # 2xx => success path

    def create_booking(
        self,
        access_token: str,
        hotel_id: str,
        guest_data: dict,
        check_in: str,
        check_out: str,
    ) -> dict:
        """POST /bookings -> {booking_id, ...}.

        Pre:
            - access_token non-empty
            - hotel_id non-empty
            - guest_data dict
        Post:
            - booking persisted in self._bookings keyed by id
            - booking_id-prefix encodes hotel_id (Multi-Tenancy-Tag)
        """
        self._check_auth(access_token)
        self._sleep_latency()
        self._check_rate_limit()
        self._maybe_inject_failure()
        if not hotel_id:
            raise ValueError("hotel_id required")
        if not isinstance(guest_data, dict):
            raise TypeError("guest_data must be dict")
        with self._lock:
            booking_id = f"bkg-{hotel_id}-{self._next_id:06d}"
            self._next_id += 1
            record = {
                "booking_id": booking_id,
                "hotel_id": hotel_id,
                "guest": dict(guest_data),
                "check_in": check_in,
                "check_out": check_out,
                "status": "confirmed",
                "created_at": time.time(),
            }
            self._bookings[booking_id] = record
            return dict(record)

    def read_booking(self, access_token: str, booking_id: str) -> dict:
        self._check_auth(access_token)
        self._sleep_latency()
        self._check_rate_limit()
        self._maybe_inject_failure()
        with self._lock:
            rec = self._bookings.get(booking_id)
            if rec is None:
                raise KeyError(f"booking {booking_id!r} not found")
            return dict(rec)

    def update_booking(
        self, access_token: str, booking_id: str, updates: dict
    ) -> dict:
        self._check_auth(access_token)
        self._sleep_latency()
        self._check_rate_limit()
        self._maybe_inject_failure()
        if not isinstance(updates, dict):
            raise TypeError("updates must be dict")
        with self._lock:
            rec = self._bookings.get(booking_id)
            if rec is None:
                raise KeyError(f"booking {booking_id!r} not found")
            # Forbid hotel_id mutation (Multi-Tenancy invariant)
            updates_safe = {
                k: v for k, v in updates.items() if k != "hotel_id"
            }
            rec.update(updates_safe)
            return dict(rec)

    def delete_booking(self, access_token: str, booking_id: str) -> bool:
        self._check_auth(access_token)
        self._sleep_latency()
        self._check_rate_limit()
        self._maybe_inject_failure()
        with self._lock:
            if booking_id in self._bookings:
                del self._bookings[booking_id]
                return True
            return False

    def list_bookings(
        self,
        access_token: str,
        hotel_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        self._check_auth(access_token)
        self._sleep_latency()
        self._check_rate_limit()
        self._maybe_inject_failure()
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        with self._lock:
            scoped = [
                dict(rec)
                for rec in self._bookings.values()
                if rec["hotel_id"] == hotel_id
            ]
            scoped.sort(key=lambda r: r["booking_id"])
            total = len(scoped)
            start = (page - 1) * page_size
            end = start + page_size
            items = scoped[start:end]
            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_next": end < total,
            }


# ---------------- Error Handler ----------------


class ApaleoErrorHandler:
    """Retry-on-5xx + Rate-Limit-Backoff + Exponential-Backoff.

    Pre:
        - max_retries >= 0
        - backoff_base > 0
    Post:
        - retry_on_5xx() retries up to max_retries on ApaleoNetworkError
        - rate_limit_backoff() respects retry_after header
        - On success: returns first successful result
        - On exhaustion: raises last exception
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_base: float = 0.1,
        max_backoff_s: float = 30.0,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if backoff_base <= 0:
            raise ValueError("backoff_base must be > 0")
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)
        self.max_backoff_s = float(max_backoff_s)
        # Audit: counts attempts per call
        self.last_attempt_count = 0

    def retry_on_5xx(
        self,
        fn: Callable[[], Any],
        max_retries: Optional[int] = None,
        backoff_base: Optional[float] = None,
    ) -> Any:
        """Retry fn on ApaleoNetworkError up to max_retries times.

        Backoff: backoff_base * (2 ** attempt), capped at max_backoff_s.
        """
        retries = self.max_retries if max_retries is None else int(max_retries)
        base = (
            self.backoff_base if backoff_base is None else float(backoff_base)
        )
        attempts = 0
        last_exc: Optional[Exception] = None
        while attempts <= retries:
            attempts += 1
            try:
                result = fn()
                self.last_attempt_count = attempts
                return result
            except ApaleoNetworkError as exc:
                last_exc = exc
                if attempts > retries:
                    break
                sleep_s = min(base * (2 ** (attempts - 1)), self.max_backoff_s)
                time.sleep(sleep_s)
        self.last_attempt_count = attempts
        if last_exc is not None:
            raise last_exc
        raise ApaleoNetworkError("retry_on_5xx exhausted without exception")

    def rate_limit_backoff(self, retry_after_header: float) -> None:
        """Sleep for retry_after_header seconds (clamped to max_backoff_s)."""
        if retry_after_header < 0:
            raise ValueError("retry_after_header must be >= 0")
        sleep_s = min(retry_after_header, self.max_backoff_s)
        time.sleep(sleep_s)


# ---------------- Booking Adapter (CRUD-Wrapper) ----------------


@dataclass
class ApaleoBookingAdapter:
    """CRUD-Wrapper against ApaleoMockServer mit hotel_id-Scoping.

    Multi-Tenancy enforced: each method takes hotel_id explicit; never
    aggregates across hotels (use Organism-Layer for cross-hotel).

    Auth-Lifecycle:
      - Lazy: get_token() on first call
      - Auto-Refresh on 401 (one retry)
      - Provenance-Hash in every response payload

    Pre:
        - server: ApaleoMockServer instance
        - auth: ApaleoMockAuth instance
        - error_handler: ApaleoErrorHandler instance (optional)
    Post:
        - all responses contain provenance_hash field
        - hotel_id mismatch raises PermissionError (defensive check)
    """

    server: ApaleoMockServer
    auth: ApaleoMockAuth
    error_handler: ApaleoErrorHandler = field(
        default_factory=ApaleoErrorHandler
    )

    def _attach_provenance(self, payload: dict) -> dict:
        """Attach provenance_hash to response (immutability marker)."""
        out = dict(payload)
        token = self.auth.get_token()
        out["provenance_hash"] = token.provenance_hash
        return out

    def _call_with_auth_retry(self, fn: Callable[[str], Any]) -> Any:
        """Run fn(access_token); on 401 refresh-and-retry once."""
        token = self.auth.get_token()
        try:
            return fn(token.access_token)
        except ApaleoAuthError:
            # Force-refresh and try once more
            new_tok = self.auth.refresh_token(token.refresh_token)
            return fn(new_tok.access_token)

    def create_booking(
        self,
        hotel_id: str,
        guest_data: dict,
        check_in: str,
        check_out: str,
    ) -> dict:
        """POST booking. Returns dict with booking_id + provenance_hash."""
        if not hotel_id:
            raise ValueError("hotel_id required")

        def call(tok: str) -> dict:
            return self.error_handler.retry_on_5xx(
                lambda: self.server.create_booking(
                    tok, hotel_id, guest_data, check_in, check_out
                )
            )

        rec = self._call_with_auth_retry(call)
        if rec.get("hotel_id") != hotel_id:
            raise PermissionError(
                f"hotel_id mismatch: expected {hotel_id!r}, got "
                f"{rec.get('hotel_id')!r}"
            )
        return self._attach_provenance(rec)

    def read_booking(self, hotel_id: str, booking_id: str) -> dict:
        if not hotel_id or not booking_id:
            raise ValueError("hotel_id + booking_id required")

        def call(tok: str) -> dict:
            return self.error_handler.retry_on_5xx(
                lambda: self.server.read_booking(tok, booking_id)
            )

        rec = self._call_with_auth_retry(call)
        if rec.get("hotel_id") != hotel_id:
            raise PermissionError(
                f"booking {booking_id!r} belongs to different hotel"
            )
        return self._attach_provenance(rec)

    def update_booking(
        self, hotel_id: str, booking_id: str, updates: dict
    ) -> dict:
        if not hotel_id or not booking_id:
            raise ValueError("hotel_id + booking_id required")
        if not isinstance(updates, dict):
            raise TypeError("updates must be dict")
        # Pre-Check: read first to verify hotel_id ownership
        existing = self.read_booking(hotel_id, booking_id)
        if existing.get("hotel_id") != hotel_id:
            raise PermissionError("update across hotels forbidden")

        def call(tok: str) -> dict:
            return self.error_handler.retry_on_5xx(
                lambda: self.server.update_booking(tok, booking_id, updates)
            )

        rec = self._call_with_auth_retry(call)
        return self._attach_provenance(rec)

    def delete_booking(self, hotel_id: str, booking_id: str) -> bool:
        if not hotel_id or not booking_id:
            raise ValueError("hotel_id + booking_id required")
        # Pre-Check ownership
        try:
            existing = self.read_booking(hotel_id, booking_id)
            if existing.get("hotel_id") != hotel_id:
                raise PermissionError("delete across hotels forbidden")
        except KeyError:
            return False

        def call(tok: str) -> bool:
            return self.error_handler.retry_on_5xx(
                lambda: self.server.delete_booking(tok, booking_id)
            )

        return self._call_with_auth_retry(call)

    def list_bookings(
        self, hotel_id: str, page: int = 1, page_size: int = 50
    ) -> dict:
        if not hotel_id:
            raise ValueError("hotel_id required")

        def call(tok: str) -> dict:
            return self.error_handler.retry_on_5xx(
                lambda: self.server.list_bookings(
                    tok, hotel_id, page=page, page_size=page_size
                )
            )

        page_data = self._call_with_auth_retry(call)
        # Defensive: filter to hotel_id (Multi-Tenancy hardening)
        page_data["items"] = [
            r for r in page_data.get("items", []) if r.get("hotel_id") == hotel_id
        ]
        return self._attach_provenance(page_data)


# CRUX-MK
