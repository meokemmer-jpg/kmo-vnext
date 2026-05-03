"""KMO Approval-Gate [CRUX-MK]

Signed approval tokens + deploy-locks for KMO Dark-Factory production-resources.

Architecture:
- HMAC-SHA256 signed tokens with shared-secret from ENV
- 24h-TTL per token (timestamp + signature)
- Single-use enforcement via SQLite-DB (token marked "used" after first verify)
- Authorized identities from YAML-config (Martin-Key + Gerdi-Key for 2-stage approval)
- Deploy-lock per production-resource (SQLite-table `deploy_locks`)

Implements KMO v0.2.0 Patch P-KMO-A4.

A4.2 (Welle-4) — Dual-Control + Atomic Pre-Deploy-Pipeline:
- `request_dual_approval()` issues TWO tokens (primary + secondary signer),
  3-way disjoint (requester != primary != secondary).
- `verify_dual_token()` verifies both tokens and identity-disjointness.
- `pre_deploy_atomic()` runs verify+lock+audit as ONE SQLite-Transaction
  (BEGIN IMMEDIATE / COMMIT / ROLLBACK). No approval-theater between calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import secrets
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# Constants with units (no magic numbers)
TOKEN_TTL_SECONDS: int = 24 * 60 * 60  # 24 hours
TOKEN_NONCE_BYTES: int = 16  # 128-bit nonce
HMAC_DIGEST_HEX_LEN: int = 64  # SHA256 -> 64 hex chars
DEFAULT_DB_PATH: Path = Path.home() / ".kmo" / "approval_gate.db"
DEFAULT_CONFIG_PATH: Path = Path.home() / ".kmo" / "authorized_identities.yaml"
ENV_SECRET_KEY: str = "KMO_APPROVAL_SECRET"


@dataclass(frozen=True)
class ApprovalToken:
    """Immutable approval token. Pre: requester in authorized identities. Post: HMAC-signed."""

    requester: str
    resource: str
    action: str
    issued_at: int  # UNIX epoch seconds
    expires_at: int
    nonce: str  # hex
    signature: str  # hex HMAC-SHA256

    def serialize(self) -> str:
        """Return URL-safe token string."""
        payload = {
            "requester": self.requester,
            "resource": self.resource,
            "action": self.action,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "signature": self.signature,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def deserialize(cls, token_str: str) -> "ApprovalToken":
        """Parse token from string. Raises ValueError on malformed input."""
        try:
            data = json.loads(token_str)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError(f"Malformed token: {exc}") from exc


class ApprovalGate:
    """Approval-Gate with HMAC-tokens, single-use, deploy-locks.

    Pre-condition: ENV var KMO_APPROVAL_SECRET set OR secret passed to ctor.
    Post-condition: All approvals are auditable via SQLite-DB.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        config_path: Path = DEFAULT_CONFIG_PATH,
        secret: Optional[str] = None,
    ):
        self._secret = secret or os.environ.get(ENV_SECRET_KEY)
        if not self._secret:
            raise RuntimeError(
                f"Approval secret missing: set ENV {ENV_SECRET_KEY} or pass secret="
            )
        self.db_path = db_path
        self.config_path = config_path
        self._init_db()
        self._authorized = self._load_authorized()

    def _init_db(self) -> None:
        """Create tables if not exist. Idempotent."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    nonce TEXT PRIMARY KEY,
                    requester TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    action TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER DEFAULT NULL,
                    revoked_at INTEGER DEFAULT NULL
                );
                CREATE TABLE IF NOT EXISTS deploy_locks (
                    resource TEXT PRIMARY KEY,
                    holder TEXT NOT NULL,
                    acquired_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                """
            )
            conn.commit()

    def _load_authorized(self) -> dict[str, str]:
        """Load authorized identities {name: role} from YAML-config."""
        if not self.config_path.exists():
            # Default: Martin + Gerdi as 2-stage approvers
            default = {"identities": {"martin": "primary", "gerdi": "secondary"}}
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config_path.open("w", encoding="utf-8") as fp:
                yaml.safe_dump(default, fp)
            return default["identities"]
        with self.config_path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        return data.get("identities", {})

    def _sign(self, requester: str, resource: str, action: str, issued_at: int, expires_at: int, nonce: str) -> str:
        """HMAC-SHA256 over canonical message."""
        msg = f"{requester}|{resource}|{action}|{issued_at}|{expires_at}|{nonce}".encode("utf-8")
        return hmac.new(self._secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def request_approval(self, resource: str, action: str, requester: str) -> str:
        """Issue a signed approval-token.

        Pre: requester is in authorized identities, resource and action non-empty.
        Post: Token persisted in DB, returns serialized token-string.
        """
        if requester not in self._authorized:
            raise PermissionError(f"Unauthorized requester: {requester}")
        if not resource or not action:
            raise ValueError("resource and action must be non-empty")

        now = int(time.time())
        expires_at = now + TOKEN_TTL_SECONDS
        nonce = secrets.token_hex(TOKEN_NONCE_BYTES)
        signature = self._sign(requester, resource, action, now, expires_at, nonce)

        token = ApprovalToken(
            requester=requester,
            resource=resource,
            action=action,
            issued_at=now,
            expires_at=expires_at,
            nonce=nonce,
            signature=signature,
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO approvals (nonce, requester, resource, action, issued_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nonce, requester, resource, action, now, expires_at),
            )
            conn.commit()

        return token.serialize()

    def verify_token(self, token_str: str, resource: str, action: str) -> bool:
        """Verify and consume token (single-use).

        Pre: token_str is serialized ApprovalToken.
        Post: Token marked as used; returns True iff valid+matching+unexpired+unused.
        """
        try:
            token = ApprovalToken.deserialize(token_str)
        except ValueError:
            return False

        # Check signature constant-time
        expected_sig = self._sign(
            token.requester, token.resource, token.action,
            token.issued_at, token.expires_at, token.nonce,
        )
        if not hmac.compare_digest(expected_sig, token.signature):
            return False

        # Check resource + action match
        if token.resource != resource or token.action != action:
            return False

        # Check expiry
        now = int(time.time())
        if now >= token.expires_at:
            return False

        # Check single-use + revocation in DB
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT used_at, revoked_at FROM approvals WHERE nonce = ?",
                (token.nonce,),
            ).fetchone()
            if row is None:
                return False  # nonce not in DB (forged or wrong DB)
            used_at, revoked_at = row
            if used_at is not None or revoked_at is not None:
                return False  # already used or revoked
            # Mark as used (atomic)
            conn.execute(
                "UPDATE approvals SET used_at = ? WHERE nonce = ? AND used_at IS NULL AND revoked_at IS NULL",
                (now, token.nonce),
            )
            if conn.total_changes != 1:
                return False  # race condition lost
            conn.commit()

        return True

    def revoke_token(self, token_str: str) -> None:
        """Revoke a token. Idempotent. Pre: token parseable. Post: future verify returns False."""
        try:
            token = ApprovalToken.deserialize(token_str)
        except ValueError:
            return  # silent no-op on malformed
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE approvals SET revoked_at = ? WHERE nonce = ? AND revoked_at IS NULL",
                (now, token.nonce),
            )
            conn.commit()

    def acquire_deploy_lock(self, resource: str, holder: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> bool:
        """Acquire exclusive deploy-lock. Returns True on success, False if held by other."""
        now = int(time.time())
        expires_at = now + ttl_seconds
        with closing(sqlite3.connect(self.db_path)) as conn:
            # Cleanup expired
            conn.execute("DELETE FROM deploy_locks WHERE expires_at <= ?", (now,))
            try:
                conn.execute(
                    "INSERT INTO deploy_locks (resource, holder, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                    (resource, holder, now, expires_at),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # already held

    def release_deploy_lock(self, resource: str, holder: str) -> bool:
        """Release lock if held by `holder`. Returns True on release."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                "DELETE FROM deploy_locks WHERE resource = ? AND holder = ?",
                (resource, holder),
            )
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # A4.2 Dual-Control + Atomic Pre-Deploy-Pipeline (Welle-4)
    # ------------------------------------------------------------------

    def request_dual_approval(
        self,
        resource: str,
        action: str,
        requester: str,
        primary_signer: str,
        secondary_signer: str,
    ) -> "DualApprovalToken":
        """Issue a DualApprovalToken (two independent tokens).

        Pre:
          - resource and action non-empty
          - requester, primary_signer, secondary_signer all in authorized
          - 3-way disjoint: requester != primary != secondary != requester
        Post:
          - Two tokens persisted in DB; returns DualApprovalToken.
        """
        if not resource or not action:
            raise ValueError("resource and action must be non-empty")
        if requester not in self._authorized:
            raise PermissionError(f"Unauthorized requester: {requester}")
        if primary_signer not in self._authorized:
            raise PermissionError(f"Unauthorized primary_signer: {primary_signer}")
        if secondary_signer not in self._authorized:
            raise PermissionError(f"Unauthorized secondary_signer: {secondary_signer}")

        # 3-way identity-disjoint enforcement
        identities = {requester, primary_signer, secondary_signer}
        if len(identities) != 3:
            raise PermissionError(
                "Dual-control requires 3 distinct identities "
                f"(requester={requester}, primary={primary_signer}, secondary={secondary_signer})"
            )

        # Issue two tokens; signer becomes the requester-of-record on each token
        # (so verify_token's signature check ties the token to that identity).
        primary_token_str = self.request_approval(resource, action, primary_signer)
        secondary_token_str = self.request_approval(resource, action, secondary_signer)

        primary_token = ApprovalToken.deserialize(primary_token_str)
        secondary_token = ApprovalToken.deserialize(secondary_token_str)

        return DualApprovalToken(
            primary=primary_token,
            secondary=secondary_token,
            requester=requester,
        )

    def verify_dual_token(
        self,
        dual_token: "DualApprovalToken",
        resource: str,
        action: str,
    ) -> bool:
        """Verify both tokens + 3-way disjointness without consuming them.

        NOTE: Read-only check. Does NOT mark single-use. Consumption
        happens transactionally inside `pre_deploy_atomic`.
        """
        primary = dual_token.primary
        secondary = dual_token.secondary
        requester = dual_token.requester

        # 3-way disjoint identity-check
        identities = {requester, primary.requester, secondary.requester}
        if len(identities) != 3:
            return False

        # Resource + action match on both
        if primary.resource != resource or primary.action != action:
            return False
        if secondary.resource != resource or secondary.action != action:
            return False

        # Signature check on both (constant-time)
        for tok in (primary, secondary):
            expected_sig = self._sign(
                tok.requester, tok.resource, tok.action,
                tok.issued_at, tok.expires_at, tok.nonce,
            )
            if not hmac.compare_digest(expected_sig, tok.signature):
                return False

        # Expiry check on both
        now = int(time.time())
        if now >= primary.expires_at or now >= secondary.expires_at:
            return False

        # Both nonces must exist in DB, both unused, both not revoked
        with closing(sqlite3.connect(self.db_path)) as conn:
            for tok in (primary, secondary):
                row = conn.execute(
                    "SELECT used_at, revoked_at FROM approvals WHERE nonce = ?",
                    (tok.nonce,),
                ).fetchone()
                if row is None:
                    return False
                used_at, revoked_at = row
                if used_at is not None or revoked_at is not None:
                    return False

        return True

    def pre_deploy_atomic(
        self,
        dual_token: "DualApprovalToken",
        resource: str,
        action: str,
        holder: str,
    ) -> bool:
        """Atomic pre-deploy pipeline (verify + lock + audit) in ONE transaction.

        Pre: dual_token issued via request_dual_approval; resource/action match.
        Post:
          - On success: both tokens marked used, deploy_lock acquired by holder,
            audit-chain extended by one block (pre-deploy event).
          - On any failure: ROLLBACK (no token use, no lock, no audit-line).

        Returns True on full success. False on any step-failure with rollback.

        Threat-Model addressed:
          Welle-3 Re-Re-Wargame schwaeche: separate verify_token + acquire_lock
          + audit_append left a window where Approval-Theater can replace one
          token between steps, or the lock is acquired without consuming the
          token. With BEGIN IMMEDIATE the entire pipeline is atomic w.r.t. the
          DB-state.
        """
        from kmo_audit_log import AuditLog  # local import avoids cycle at load

        audit = AuditLog()
        now = int(time.time())

        conn = sqlite3.connect(self.db_path, isolation_level=None)  # manual TX
        try:
            conn.execute("BEGIN IMMEDIATE")

            # ---------- Step 1: verify dual token (in-transaction) ----------
            primary = dual_token.primary
            secondary = dual_token.secondary
            requester = dual_token.requester

            # 3-way disjoint identities
            if len({requester, primary.requester, secondary.requester}) != 3:
                conn.execute("ROLLBACK")
                return False

            # Resource/action/signature/expiry checks (no DB needed yet)
            for tok in (primary, secondary):
                if tok.resource != resource or tok.action != action:
                    conn.execute("ROLLBACK")
                    return False
                expected_sig = self._sign(
                    tok.requester, tok.resource, tok.action,
                    tok.issued_at, tok.expires_at, tok.nonce,
                )
                if not hmac.compare_digest(expected_sig, tok.signature):
                    conn.execute("ROLLBACK")
                    return False
                if now >= tok.expires_at:
                    conn.execute("ROLLBACK")
                    return False

            # In-DB: both tokens must exist, unused, not revoked → mark used
            for tok in (primary, secondary):
                row = conn.execute(
                    "SELECT used_at, revoked_at FROM approvals WHERE nonce = ?",
                    (tok.nonce,),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return False
                used_at, revoked_at = row
                if used_at is not None or revoked_at is not None:
                    conn.execute("ROLLBACK")
                    return False
                # Mark used (still inside TX)
                conn.execute(
                    "UPDATE approvals SET used_at = ? "
                    "WHERE nonce = ? AND used_at IS NULL AND revoked_at IS NULL",
                    (now, tok.nonce),
                )
                if conn.total_changes < 1:
                    conn.execute("ROLLBACK")
                    return False

            # ---------- Step 2: acquire deploy-lock (in-transaction) ----------
            conn.execute("DELETE FROM deploy_locks WHERE expires_at <= ?", (now,))
            try:
                conn.execute(
                    "INSERT INTO deploy_locks (resource, holder, acquired_at, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (resource, holder, now, now + TOKEN_TTL_SECONDS),
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                return False

            # ---------- Step 3: append audit (in-transaction) ----------
            audit_action = f"pre_deploy:{action}"
            staged_entry = audit.append_within_transaction(
                conn=conn,
                action=audit_action,
                resource=resource,
                requester=requester,
                approver_token_nonce=f"{primary.nonce[:16]}+{secondary.nonce[:16]}",
            )

            # ---------- Step 4: COMMIT ----------
            conn.execute("COMMIT")

            # JSONL-flush AFTER successful commit (file-system is post-TX boundary)
            audit.flush_entry_to_jsonl(staged_entry)
            return True

        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return False
        finally:
            conn.close()


@dataclass(frozen=True)
class DualApprovalToken:
    """Two independent ApprovalTokens for dual-control.

    Invariants (enforced at construction-site `request_dual_approval`):
      - primary.requester != secondary.requester  (different signers)
      - requester != primary.requester != secondary.requester (3-way disjoint)
      - primary.resource == secondary.resource
      - primary.action == secondary.action
    """

    primary: ApprovalToken
    secondary: ApprovalToken
    requester: str  # the party who initiated the request (not a signer)

    def serialize(self) -> str:
        return json.dumps(
            {
                "primary": json.loads(self.primary.serialize()),
                "secondary": json.loads(self.secondary.serialize()),
                "requester": self.requester,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, dual_str: str) -> "DualApprovalToken":
        data = json.loads(dual_str)
        return cls(
            primary=ApprovalToken(**data["primary"]),
            secondary=ApprovalToken(**data["secondary"]),
            requester=data["requester"],
        )
