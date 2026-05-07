# KMO Lease Manager [CRUX-MK]

KMO-Patch P-KMO-A1: zentraler Mutex/Lease-Manager fuer DF/Port/Token/Drive-Path/Tunnel-Locks.

## Use-Case (DF-K16-konform)

`rules/df-akzeptanz-kriterien.md` K16 verlangt Concurrent-Spawn-Mutex pro Dark-Factory.
Bisher: ad-hoc `mkdir`-Locks pro DF + pgrep-Heuristiken. Neu: zentraler SQLite-basierter
Lease-Manager mit atomic UNIQUE-Constraint, TTL-Renewal, STOP.flag-Respect.

Resource-Types:
- `DF` — Dark-Factory engine instance (z.B. `df-86`)
- `PORT` — TCP-Port (z.B. `8080`)
- `API_TOKEN` — OAuth-/API-Token-Slot (z.B. NLM-Storage-State)
- `DRIVE_PATH` — Filesystem-Path / Drive-Mount
- `TUNNEL_SUBDOMAIN` — Cloudflare/ngrok Subdomain

## Setup

```bash
# Optional: dedizierte venv
python3.11 -m venv .venv && source .venv/bin/activate
pip install pytest

# DB liegt default unter:
#   ~/Library/Application Support/kmo/leases.db
# STOP-Flags werden gesucht in:
#   ~/branch-hub/audit/STOP-{resource_id}.flag
```

## Smoke-Test

```bash
cd /Users/make/Projects/dark-factories/kmo/lease-manager
python -m pytest tests/ -v
```

## Decorator-Example

```python
import os
from kmo_lease_manager import LeaseManager, ResourceType
from kmo_lease_decorator import with_lease

mgr = LeaseManager()

@with_lease(
    manager=mgr,
    resource_type=ResourceType.DF,
    resource_id_func=lambda df_name, *a, **kw: df_name,
    holder_func=lambda df_name, *a, **kw: f"mac.{df_name}.pid-{os.getpid()}",
    ttl_sec=300,
    heartbeat_interval_sec=60,
)
def run_df_engine(df_name: str) -> None:
    # Lease ist hier garantiert exklusiv.
    # Background-Heartbeat-Thread refreshet TTL alle 60s.
    # Bei Exception: Lease wird trotzdem released.
    do_long_running_work(df_name)
```

## Manuelle API

```python
from kmo_lease_manager import LeaseManager, ResourceType

mgr = LeaseManager()
token = mgr.acquire(ResourceType.DF, "df-86", holder="mac.df-86.pid-1234", ttl_sec=300)
if token:
    try:
        # ... arbeite ...
        mgr.heartbeat(token)  # alle 60s waehrend langlaufender Tasks
    finally:
        mgr.release(token)
else:
    # Resource war busy ODER STOP.flag aktiv
    pass

# Diagnostik:
info = mgr.is_locked(ResourceType.DF, "df-86")
mgr.list_active()
mgr.force_release_stale()  # Cleanup expired Leases
```

## Pre-Action-Verification (CLAUDE.md §0)

Der Manager pruef vor jedem `acquire()` automatisch ob `branch-hub/audit/STOP-{resource_id}.flag`
existiert. Wenn ja: STOP, return None. Damit ist die K13-Pre-Action-Verification fuer
Concurrent-Spawn-Schutz mechanisch verankert.

## Status

- v0.1.0 (2026-04-30): Code geschrieben, lokal pytest pending.
- pending Cross-LLM-Code-Review (W-Patch-A1-Pentagon).
- Promotion auf CROSS-LLM-2OF3-HARDENED nach Codex+Gemini-Audit.

[CRUX-MK]
