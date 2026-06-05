# KMO Compliance-Backbone-Layer [CRUX-MK]

**Welle-11-E1 Multi-Tenant-Erweiterung**

Mock-Integration mit DF-W8-11-DSGVO-Auditor + DPIA-per-Tenant Lifecycle.

## Komponenten

- `src/compliance_orchestrator.py` — DSGVO-Aggregat-Checks (Consent/Retention/CrossBorder/DPIA)
- `src/dpia_per_tenant.py` — DPIA-Lifecycle (DRAFT/ACTIVE/EXPIRED/SUPERSEDED)

## Compliance-Status-Aggregation

```
all PASS  -> overall PASS
any FAIL  -> overall FAIL
any WARN  -> overall WARN
sonst     -> UNKNOWN
```

## DPIA-Lifecycle

```
DRAFT    -> activate_dpia()  -> ACTIVE (validity_days=365 Default)
ACTIVE   -> expire_if_overdue() -> EXPIRED
ACTIVE/EXPIRED -> supersede_dpia() -> SUPERSEDED (durch neue Version)
```

## Tests

22 Tests (Orchestrator: 10, DPIA: 12) — alle passing.

## Phase-2-Integration

In Phase-2 wird `_mock_auditor` durch direkten DF-W8-11-Import ersetzt
(siehe `dependencies_phase_2` in config.yaml).

## CRUX-Bindung

- K_0: DIREKT GESCHUETZT (Compliance-Strafe-Vermeidung pro Tenant)
- Q_0: erhoeht (DPIA-Lifecycle + Provenance pro Tenant)
- W_0: Tenant-Compliance ohne Martin-Review pro Audit
