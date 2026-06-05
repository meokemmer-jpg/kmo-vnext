# KMO Hot-Switch-Multi-Adapter [CRUX-MK]

**Welle-11-E1 Multi-Tenant-Erweiterung**

Multi-Adapter-Router (Apaleo/Mews/Cloudbeds) mit Circuit-Breaker + Failover.

## Routing-Logic

```
PRIMARY (apaleo)
   |
   |  on failure (and not circuit-open)
   v
FAILOVER_SECONDARY (mews)
   |
   |  on failure
   v
FAILOVER_TERTIARY (cloudbeds)
   |
   |  all fail
   v
NO_AVAILABLE_ADAPTER
```

## Circuit-Breaker (LC3)

- **CLOSED**: alles normal
- **OPEN**: Adapter wird geskippt nach `threshold_open_after_n_fails` (Default 3)
- **HALF_OPEN**: Test-Call erlaubt nach `half_open_test_interval_s` (Default 30)
- Bei Erfolg im HALF_OPEN -> CLOSED

## Anti-Patterns (verboten)

- Tenant-Hardcoding in Adapter-Code
- Cross-Tenant-Daten-Sharing in Adapter-State
- Monolithic-Adapter ohne Health-Monitoring

## Komponenten

- `src/adapter_health.py` — AdapterHealthMonitor + Circuit-Breaker-Logic
- `src/multi_adapter_router.py` — Routing + Failover-Chain
- `src/failover_orchestrator.py` — Per-Tenant-Router-Verwaltung

## Tests

31 Tests (Health: 12, Router: 8, Orchestrator: 11) — alle passing.

## Per-Tenant-Isolation

Tenant A's Adapter-Failures wirken nicht auf Tenant B's Health-Monitor.
Eigene Router-Instanz pro Tenant via `FailoverOrchestrator.configure_tenant()`.

## CRUX-Bindung

- K_0: geschuetzt (Hot-Switch verhindert Tenant-Downtime bei Outages)
- Q_0: Circuit-Breaker + per-Tenant-Isolation
- W_0: Adapter-Vendor-Independence + Auto-Failover
