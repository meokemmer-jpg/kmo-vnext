# KMO Cell-Boundary [CRUX-MK]

KMO-vNext Welle-9α Phase-1 Modul 2.1: Cell-Membrane fuer Saga-Run-Cells mit
Resource-Quotas, I/O-Channel-Validierung, Multi-Tenancy-Boundary und Apoptose-Hook.

## Bio-Aequivalent

**Lipid-Bilayer mit selektiven Channels.** Aquaporine fuer Wasser, Ionen-Kanaele fuer Ionen,
GPCR fuer Signal-Liganden. Nur was zum Schema passt, passiert die Membrane.
Ueberschreitung der Channel-Capacity (Quota) triggert kontrollierten Apoptose-Cascade-Tod
statt unkontrolliertem Crash.

## Architektur

```
┌────────────────────────────────────────────────┐
│ CellBoundary (frozen dataclass, immutable)     │
│   - cell_id, hotel_id, quota, schemas          │
└────────────────────────────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│ CellBoundaryManager (stateful, thread-safe)    │
│   - consume_tokens / consume_cpu / consume_mem │
│   - validate_input / validate_output           │
│   - record_io_call (rate-limit)                │
│   - apoptose-callback on quota-exhaustion      │
└────────────────────────────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│ QuotaEnforcer (combines manager + audit)       │
│   - charge_tokens / charge_cpu / charge_mem    │
│   - charge_io_call                             │
│   - validate_input / validate_output           │
└────────────────────────────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│ BoundaryAuditLog (SQLite-WAL, append-only)     │
│   - hotel_id Row-Level-Security                │
│   - GDPR purge_hotel cascade-delete            │
└────────────────────────────────────────────────┘
```

## Public API

```python
from kmo_governance.cell_boundary import (
    CellBoundary, CellQuota, CellBoundaryManager,
    QuotaEnforcer, BoundaryAuditLog,
    QuotaExhaustedError, SchemaViolationError,
)

# 1. Define boundary (immutable contract)
boundary = CellBoundary(
    cell_id="saga-run-abc123",
    hotel_id="apaleo-eu-hotel-001",
    quota=CellQuota(
        cpu_seconds=300,
        memory_mb=512,
        llm_token_budget=50_000,
        io_calls_per_minute=120,
    ),
    input_schema=lambda x: isinstance(x, dict) and "booking_id" in x,
    output_schema=lambda x: isinstance(x, dict) and x.get("status") in ("ok", "ack"),
)

# 2. Wire manager + audit + apoptose-callback
def trigger_apoptose(reason: str, details: dict) -> None:
    # Phase-1.2.2 wires this to apoptosis_engine
    print(f"[APOPTOSE] cell triggered: {reason} {details}")

audit = BoundaryAuditLog()
mgr = CellBoundaryManager(boundary, on_quota_exhausted=trigger_apoptose)
enforcer = QuotaEnforcer(mgr, audit)

# 3. Use during saga-run
if enforcer.validate_input(payload):
    enforcer.charge_tokens(1234, payload={"prompt": "..."})
    enforcer.charge_io_call(payload={"endpoint": "/api/x"})
```

## CRUX-Konformitaet

- **K11 Cascade-Containment:** Cell-Failure isoliert pro `cell_id`, kein Spillover.
- **K11.b Pipeline-Cost-Estimate:** Pre-Action-Quota-Check vor jedem charge.
- **K12 Distillation-Resistenz:** payload_hash in BoundaryEvent fuer Provenance.
- **K13 Independent-Ground-Truth:** SQLite-WAL extern, Row-Level-Security per hotel_id.
- **K14 Human-Override-Decay:** STOP via STOP.flag in `branch-hub/audit/STOP-{cell_id}.flag` (LC4).
- **K15 Entropy-Budget:** ~620 LoC + 12 Tests = ratio 51.7 LoC/Test, justified.
- **K16 Concurrent-Spawn-Mutex:** RLock per Manager + atomic counter.

## LC1-LC5 Lose-Coupling

- **LC1 Graceful-Degradation:** `audit_log=None` -> in-memory only (degraded), Kern-Funktion bleibt.
- **LC2 Direct-Mode-Fallback:** Manager funktioniert ohne BoundaryAuditLog. Capability ~70%.
- **LC3 Circuit-Breaker:** SQLite-Timeout 5s + busy_timeout. Apoptose schliesst Cell.
- **LC4 Failure-Isolation:** State extern (SQLite), atomic INSERT idempotent via UUID.
- **LC5 Health-Check-Independence:** Manager.is_apoptosed lesbar ohne DB-Zugriff.

## Setup

```bash
cd /Users/make/Projects/dark-factories/kmo
python3 -m pytest kmo_governance/cell_boundary/tests/ -v
```

DB-Default: `~/Library/Application Support/kmo/boundary_audit.db`

## Multi-Tenancy (GDPR)

`hotel_id` ist **Pflicht-Field** auf jedem CellBoundary. Alle DB-Queries ziehen
`hotel_id`-Filter. `purge_hotel(hotel_id)` cascade-deleted alle Events fuer ein Hotel
(Right-to-be-Forgotten).

```python
audit.purge_hotel("apaleo-eu-hotel-001")  # GDPR cascade
```

## Apoptose-Hook

Quota-Exhaustion triggert `on_quota_exhausted(reason, details)` callback EXAKT EINMAL.
Phase-1.2.2 wired das zu `apoptosis_engine.trigger()`. Heute: Stub (logging).

## Status

- v0.1.0 (2026-05-01): 12/12 Tests passing.
- pending Cross-LLM-Code-Review (Welle-9α-Pentagon).
- Promotion auf CROSS-LLM-2OF3-HARDENED nach Codex+Gemini-Audit.

[CRUX-MK]
