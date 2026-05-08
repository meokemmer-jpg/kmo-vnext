"""SAE-v8 Capability-Guard [CRUX-MK].

Welle-31 P-W31-2: Capability-basierte Mock-Sicherung (statt env-var-Toggle).

Problem (V14 Codex MODIFY):
    Default ``MockSlot.mock_mode_only=True`` Schutz ist umgehbar wenn
    Code mock_mode_only=False explizit setzt oder env-var manipuliert.
    Mode-Escape via Env-Var-Mutation moeglich.

Loesung:
    HMAC-signierte Capability-Tokens. Production-SAE-Slots brauchen ein
    crypto-signiertes Capability-Token mit timestamp + scope. Tokens
    sind nicht durch env-var-Mutation faelschbar (Secret im Vault).

    Mock-Mode hat KEIN Token (oder ein explizites Mock-Token) und kann
    daher physisch nicht in Production-Slots eskalieren.

Bio-Aequivalent:
    Apoptose-Engine darf nur Zellen mit Apoptose-Marker (Death-Receptor)
    ansprechen. Healthy-Zellen ohne Marker sind physisch unangreifbar.

CRUX-Bindung:
    K_0: direkt zentral (Mock-Escape ins SAE-Production-Cluster ist
         K_0-Risiko)
    Q_0: epistemische Integritaet via crypto-Beweis statt env-Glaube
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional


# Constants (no magic numbers)
DEFAULT_TOKEN_TTL_SEC: int = 3600  # 1h
ENV_CAPABILITY_SECRET: str = "SAE_CHAOS_CAPABILITY_SECRET"
SCOPE_MOCK_ONLY: str = "mock_only"
SCOPE_PRODUCTION_AUDIT: str = "production_audit"
SCOPE_FORBIDDEN: str = "forbidden"


@dataclass(frozen=True)
class CapabilityToken:
    """Crypto-signiertes Capability-Token.

    Pre: scope in {mock_only, production_audit, forbidden}.
    Post: signature = HMAC-SHA256(secret, canonical-payload).
    """

    scope: str
    issued_at: int
    expires_at: int
    issuer: str
    nonce: str
    signature: str

    def serialize(self) -> str:
        return json.dumps(
            {
                "scope": self.scope,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "issuer": self.issuer,
                "nonce": self.nonce,
                "signature": self.signature,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, token_str: str) -> "CapabilityToken":
        try:
            data = json.loads(token_str)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError(f"Malformed capability token: {exc}") from exc


class CapabilityGuard:
    """Capability-Guard: HMAC-Token-Verifikation fuer Mock-vs-Production.

    Pre: ENV var SAE_CHAOS_CAPABILITY_SECRET set OR secret passed.
    Post: ``verify_mock_only`` returns True iff Token bewiesen Mock-Scope.

    Anti-Pattern (REJECTED):
        env-var-only-Toggles. Capability ist Crypto-Beweis.
    """

    def __init__(self, secret: Optional[str] = None) -> None:
        self._secret = secret or os.environ.get(ENV_CAPABILITY_SECRET)
        if not self._secret:
            raise RuntimeError(
                f"Capability secret missing: set ENV "
                f"{ENV_CAPABILITY_SECRET} or pass secret="
            )

    def _sign(
        self,
        scope: str,
        issued_at: int,
        expires_at: int,
        issuer: str,
        nonce: str,
    ) -> str:
        msg = f"{scope}|{issued_at}|{expires_at}|{issuer}|{nonce}".encode(
            "utf-8"
        )
        return hmac.new(
            self._secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()

    def issue_mock_token(
        self,
        issuer: str,
        ttl_sec: int = DEFAULT_TOKEN_TTL_SEC,
    ) -> CapabilityToken:
        """Issue a Mock-Only Capability-Token.

        Pre: issuer non-empty, ttl_sec > 0.
        Post: Token mit scope=mock_only, signature valid.
        """
        if not issuer:
            raise ValueError("issuer must be non-empty")
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")

        now = int(time.time())
        expires = now + ttl_sec
        # Use os.urandom for cryptographically strong nonce.
        nonce = os.urandom(16).hex()
        sig = self._sign(SCOPE_MOCK_ONLY, now, expires, issuer, nonce)
        return CapabilityToken(
            scope=SCOPE_MOCK_ONLY,
            issued_at=now,
            expires_at=expires,
            issuer=issuer,
            nonce=nonce,
            signature=sig,
        )

    def verify_mock_only(self, token: CapabilityToken) -> bool:
        """Verify Token has Mock-Only-Scope and is unexpired+signed.

        Pre: token is CapabilityToken instance.
        Post: True iff scope=mock_only AND HMAC matches AND not expired.
        """
        # Scope check (most specific gate).
        if token.scope != SCOPE_MOCK_ONLY:
            return False

        # Signature check (constant-time).
        expected = self._sign(
            token.scope,
            token.issued_at,
            token.expires_at,
            token.issuer,
            token.nonce,
        )
        if not hmac.compare_digest(expected, token.signature):
            return False

        # Expiry check.
        now = int(time.time())
        if now >= token.expires_at:
            return False

        return True

    def is_production_attempt(self, token: Optional[CapabilityToken]) -> bool:
        """Returns True if a non-mock token is presented (anti-escape)."""
        if token is None:
            # Default-deny: missing token means Mock-Mode required, which
            # is the SAFE default but not a Production-Attempt either.
            return False
        if token.scope == SCOPE_FORBIDDEN:
            return True
        if token.scope != SCOPE_MOCK_ONLY:
            return True
        return False


def capability_guard_check_or_raise(
    guard: CapabilityGuard,
    token: Optional[CapabilityToken],
) -> None:
    """Hard-Fail wenn kein verifiziertes Mock-Token vorliegt.

    Pre: guard initialized.
    Post: returns silently if Mock-Scope verified; else PermissionError.
    """
    if token is None:
        raise PermissionError(
            "K_0-Schutz: capability_token=None. "
            "Mock-Scope-Token Pflicht fuer chaos_engineering."
        )
    if guard.is_production_attempt(token):
        raise PermissionError(
            f"K_0-Schutz: capability_token.scope={token.scope!r}. "
            "SAE-Production darf NIE durch chaos_engineering aktiviert "
            "werden."
        )
    if not guard.verify_mock_only(token):
        raise PermissionError(
            "K_0-Schutz: capability_token verification FAILED "
            "(signature/expiry/scope-mismatch)."
        )


# CRUX-MK
