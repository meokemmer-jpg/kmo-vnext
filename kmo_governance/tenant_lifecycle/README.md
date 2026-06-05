# KMO Tenant-Lifecycle Module [CRUX-MK]

**Welle-11-E1 Multi-Tenant-Erweiterung**

Tenant-Lifecycle-State-Machine fuer Multi-Tenant-Hotelier-Onboarding.

## State-Machine

```
PROVISIONED -> ACTIVE        (activate)
PROVISIONED -> DECOMMISSIONED (cancel)
ACTIVE      -> SUSPENDED     (suspend)
SUSPENDED   -> ACTIVE        (reactivate)
ACTIVE      -> DECOMMISSIONED (decommission)
SUSPENDED   -> DECOMMISSIONED (decommission)
DECOMMISSIONED -> ARCHIVED   (archive)
```

## Komponenten

- `src/tenant.py` — Tenant dataclass + canonical_record_hash
- `src/lifecycle_pipeline.py` — Pipeline-Funktionen + State-Transition-Validation
- `src/db.py` — SQLite-State + jsonl-Backup (LC2 Direct-Mode)

## Tests

29 Tests (Tenant: 7, Pipeline: 12, DB: 10) — alle passing.

## Pflicht-Felder

K11-K16 + LC1-LC5 in `config.yaml` definiert. Pre-Action-Hook via DF-W8-11-Pattern.

## CRUX-Bindung

- K_0: geschuetzt (saubere Provisioning)
- Q_0: erhoeht (deterministische State-Machine + Audit-Log)
- I_min: 5-State-Machine + LC1-LC5
- W_0: Multi-Tenant-Onboarding ohne Martin-Review pro Tenant
