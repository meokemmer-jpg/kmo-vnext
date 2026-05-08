"""Graphity Lock Manager (Domain-Adapter ueber Synaptic-Lock-Core) [CRUX-MK]

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

Domain-Adapter combining:
- `synaptic_lock_core`        (Pattern-Core: acquire/release/refractory/HMAC)
- Graphity-Verlag-spezifische Field-Names (author/project_id/section_id)
- Backwards-compat LockToken-Type (frozen dataclass)
- ENV-Var-Secret-Resolution (GRAPHITY_LOCK_SECRET)

Bio-Pattern-Korrespondenz (Synaptic-Vesikel-Release-Lock):
- Synaptic-Vesikel       -> Lock-Token (acquired by author)
- Pre-Synaptic-Release   -> acquire_lock (Author-X startet Edit)
- Post-Synaptic-Receptor -> wait_for_lock (Author-Y wartet auf Release)
- Refractory-Period      -> Lock-Cooldown (kein sofortiges Re-Lock)
- Neurotransmitter-Reuptake -> release_lock (Cleanup)

CRUX-Bindung:
- Q_0: Section-Edit-Integritaet (kein Lost-Update)
- I_min: strukturierte Lock-Mechanik
- W_0: Pattern-Reuse aus Hotel-Saga (Synaptic-Pattern wiederverwendet)
"""

from __future__ import annotations

import os
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Optional

from synaptic_lock_core import (
    CoreLockToken,
    LOCK_NONCE_BYTES,
    HMAC_DIGEST_HEX_LEN,
    acquire_core,
    init_core_db,
    release_core,
    verify_core,
)

# Constants with units (no magic numbers)
DEFAULT_LOCK_TTL_SECONDS: int = 30 * 60  # 30 min
MAX_LOCK_TTL_SECONDS: int = 4 * 60 * 60  # 4h
REFRACTORY_PERIOD_SECONDS: int = 60  # 60s Cooldown nach Release
DEFAULT_DB_PATH: Path = Path.home() / ".graphity" / "lock_manager.db"
ENV_SECRET_KEY: str = "GRAPHITY_LOCK_SECRET"


@dataclass(frozen=True)
class LockToken:
    """Immutable Lock-Token (Domain-Adapter, Bio-Synaptic-Vesikel).

    Backwards-compat shape mit Graphity-spezifischen Feldnamen
    (author/project_id/section_id). Wraps CoreLockToken.
    """

    author: str
    project_id: str
    section_id: str
    acquired_at: int
    expires_at: int
    nonce: str
    signature: str

    def serialize(self) -> str:
        # Graphity-Shape: gleiche Felder wie CoreLockToken aber gemappt
        core = CoreLockToken(
            holder_id=self.author,
            container_key=self.project_id,
            resource_key=self.section_id,
            acquired_at=self.acquired_at,
            expires_at=self.expires_at,
            nonce=self.nonce,
            signature=self.signature,
        )
        # Domain-Compat: emit unter Graphity-Field-Namen
        import json
        return json.dumps(
            {
                "author": self.author,
                "project_id": self.project_id,
                "section_id": self.section_id,
                "acquired_at": self.acquired_at,
                "expires_at": self.expires_at,
                "nonce": self.nonce,
                "signature": self.signature,
            },
            sort_keys=True, separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, token_str: str) -> "LockToken":
        import json
        try:
            data = json.loads(token_str)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError(f"Malformed lock token: {exc}") from exc


def _domain_to_core_token_str(token_str: str) -> str:
    """Domain-Adapter: rename Graphity-Felder zu Core-Feldnamen."""
    import json
    data = json.loads(token_str)
    core_data = {
        "holder_id": data["author"],
        "container_key": data["project_id"],
        "resource_key": data["section_id"],
        "acquired_at": data["acquired_at"],
        "expires_at": data["expires_at"],
        "nonce": data["nonce"],
        "signature": data["signature"],
    }
    return json.dumps(core_data, sort_keys=True, separators=(",", ":"))


def _core_to_domain_token_str(core_token_str: str) -> str:
    """Domain-Adapter: rename Core-Felder zu Graphity-Feldnamen."""
    import json
    core_data = json.loads(core_token_str)
    domain_data = {
        "author": core_data["holder_id"],
        "project_id": core_data["container_key"],
        "section_id": core_data["resource_key"],
        "acquired_at": core_data["acquired_at"],
        "expires_at": core_data["expires_at"],
        "nonce": core_data["nonce"],
        "signature": core_data["signature"],
    }
    return json.dumps(domain_data, sort_keys=True, separators=(",", ":"))


class GraphityLockManager:
    """Domain-Adapter ueber Synaptic-Lock-Core (Pattern-Core).

    Pre-condition: ENV var GRAPHITY_LOCK_SECRET set OR secret passed to ctor.
    Post-condition: All lock-acquire/release auditable via SQLite-DB.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        secret: Optional[str] = None,
    ):
        self._secret = secret or os.environ.get(ENV_SECRET_KEY)
        if not self._secret:
            raise RuntimeError(
                f"Lock secret missing: set ENV {ENV_SECRET_KEY} or pass secret="
            )
        self.db_path = db_path
        init_core_db(self.db_path)

    def acquire_lock(
        self,
        author: str,
        project_id: str,
        section_id: str,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> Optional[str]:
        """Acquire lock on section (Pre-Synaptic-Vesikel-Release).

        Pre: author/project_id/section_id non-empty, ttl in [60, MAX_LOCK_TTL].
        Post: On success returns serialized Graphity-LockToken; on conflict None.
        """
        if not author or not project_id or not section_id:
            raise ValueError(
                "author, project_id, section_id must all be non-empty"
            )
        if ttl_seconds < 60 or ttl_seconds > MAX_LOCK_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be in [60, {MAX_LOCK_TTL_SECONDS}]"
            )

        # Pattern-Core delegate (uses module-level time.time for monkeypatch
        # compatibility in refractory test)
        now_int = int(time.time())
        core_token = acquire_core(
            db_path=self.db_path,
            secret=self._secret,
            holder_id=author,
            container_key=project_id,
            resource_key=section_id,
            ttl_seconds=ttl_seconds,
            refractory_period_sec=REFRACTORY_PERIOD_SECONDS,
            now=now_int,
        )
        if core_token is None:
            return None
        return _core_to_domain_token_str(core_token)

    def verify_lock(self, token_str: str) -> bool:
        """Verify lock-token validity (signature + expiry + DB-presence)."""
        try:
            core_str = _domain_to_core_token_str(token_str)
        except (ValueError, KeyError, TypeError):
            return False
        return verify_core(self.db_path, self._secret, core_str)

    def release_lock(self, token_str: str) -> bool:
        """Release lock (Bio: Neurotransmitter-Reuptake)."""
        try:
            core_str = _domain_to_core_token_str(token_str)
        except (ValueError, KeyError, TypeError):
            return False
        return release_core(self.db_path, self._secret, core_str)

    def get_lock_status(
        self, project_id: str, section_id: str
    ) -> Optional[dict]:
        """Return current lock-holder info or None if free."""
        if not project_id or not section_id:
            raise ValueError("project_id and section_id must be non-empty")

        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "DELETE FROM resource_locks WHERE expires_at <= ?", (now,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT holder_id, acquired_at, expires_at, nonce "
                "FROM resource_locks "
                "WHERE container_key = ? AND resource_key = ?",
                (project_id, section_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "author": row[0],
                "acquired_at": row[1],
                "expires_at": row[2],
                "nonce": row[3],
            }

    def force_release(
        self, project_id: str, section_id: str, admin: str
    ) -> bool:
        """Admin-Override: force-release stuck lock (e.g. crashed author)."""
        if not admin:
            raise ValueError("admin must be non-empty")
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT holder_id, nonce, acquired_at FROM resource_locks "
                "WHERE container_key = ? AND resource_key = ?",
                (project_id, section_id),
            ).fetchone()
            if row is None:
                return False
            holder_id, nonce, acquired_at = row

            conn.execute(
                "DELETE FROM resource_locks "
                "WHERE container_key = ? AND resource_key = ?",
                (project_id, section_id),
            )
            conn.execute(
                "INSERT INTO lock_history "
                "(container_key, resource_key, holder_id, nonce, "
                "acquired_at, released_at, release_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, section_id, holder_id, nonce,
                 acquired_at, now, f"forced_by:{admin}"),
            )
            conn.commit()
        return True
