# KMO Multi-Tenant-Erweiterung (Welle-11-E1) [CRUX-MK]

**5 NEU Module unter `kmo_governance/`** — Pflicht VOR Drittpartei-Hotelier-Onboarding.

## Architektur-Ueberblick

```
                  +--------------------------+
                  | Drittpartei-Hotelier     |
                  | (Tenant)                 |
                  +-----------+--------------+
                              |
              +---------------+---------------+
              | tenant_lifecycle (Module-1)   |
              | - Tenant-State-Machine        |
              | - SQLite + jsonl-Backup       |
              +---------------+---------------+
                              |
              +---------------+---------------+
              | multi_tenant_approval (M-2)   |
              | - Pre-Action-Check            |
              | - Phronesis-Eskalation        |
              +---------------+---------------+
                              |
              +---------------+---------------+
              | compliance_backbone (M-3)     |
              | - DSGVO-Audit (Mock DF-W8-11) |
              | - DPIA pro Tenant             |
              +---------------+---------------+
                              |
              +---------------+---------------+
              | cross_tenant_filter (M-4)     |
              | - PolicyDecisionPoint         |
              | - k-Anonymity (k>=5)          |
              +---------------+---------------+
                              |
              +---------------+---------------+
              | hot_switch_adapter (M-5)      |
              | - Apaleo/Mews/Cloudbeds       |
              | - Circuit-Breaker + Failover  |
              +-------------------------------+
```

## Module-Bilanz

| Modul | LOC | Tests | Status |
|-------|-----|-------|--------|
| tenant_lifecycle | 691 | 29 | passing |
| multi_tenant_approval | 452 | 17 | passing |
| compliance_backbone | 523 | 22 | passing |
| cross_tenant_filter | 522 | 20 | passing |
| hot_switch_adapter | 667 | 31 | passing |
| integration_tests | 167 | 5 | passing |
| **Total** | **3022** | **124** | **passing** |

LOC-Cap < 8K erfuellt. Tests-Target 60+ deutlich uebertroffen.

## Cross-Module Pflicht-Eigenschaften

### Reuse-Pattern (uebergreifend)

- **canonical_record_hash()** Helper in jedem Modul
- **dataclass-Fallback** (kein Pydantic-Dependency)
- **K11-K16 + LC1-LC5** in jedem `config.yaml`
- **Pre-Action-Verification** via DF-W8-11-Pattern

### Anti-Patterns (verboten)

- Pydantic-Pflicht (Fallback-Pattern)
- Cross-Tenant-Queries ohne Audit
- Tenant-Hardcoding in Adapter-Code
- Implicit-Sharing ohne explicit policy
- Phronesis-Outsourcing ohne Hard-No-Delegate

## Test-Run

```bash
# Per-Modul (jeder Modul hat eigenes src/-Namespace)
cd tenant_lifecycle && python3 -m pytest tests/ -q
cd multi_tenant_approval && python3 -m pytest tests/ -q
cd compliance_backbone && python3 -m pytest tests/ -q
cd cross_tenant_filter && python3 -m pytest tests/ -q
cd hot_switch_adapter && python3 -m pytest tests/ -q

# Integration (subprocess-isoliert wegen src/-Namespace-Sharing)
cd integration_tests && python3 -m pytest test_cross_module_flow.py -q
```

## Phase-Plan

### Phase-1 (THIS DEPLOY 2026-05-07)
- 5 Module Build mit dataclass-Fallback
- 124 Tests passing
- K11-K16 + LC1-LC5 in jeder `config.yaml`
- Mock-Integration mit DF-W8-11

### Phase-2 (PENDING)
- Real-DF-W8-11-Integration (nicht Mock)
- Apaleo/Mews/Cloudbeds-Real-API-Hooks
- Tenant-Onboarding-Wizard
- Live-Cron-Activation

### Phase-3 (PENDING)
- Multi-Tenant-Dashboard
- Per-Tenant-Compliance-Status-View
- Cross-Tenant-Sharing-Audit-Log

### Phase-4 (PENDING)
- Integration in V10-Foundation Dashboard
- Shadow-Mode 14 Tage
- Live-Aktivierung

## CRUX-Bindung

- **K_0**: 4 von 5 Modulen direkt schuetzen K_0 (Approval-Gate, Compliance, Cross-Tenant-Filter, Hot-Switch)
- **Q_0**: alle 5 Module erhoehen Q_0 via Provenance + Audit + State-Machines
- **I_min**: strukturierte K11-K16 + LC1-LC5 in allen Modulen
- **W_0**: Multi-Tenant-Onboarding skaliert ohne Martin-Review-pro-Tenant

## Beziehung zu DF-W8-11

Compliance-Backbone-Modul ist Wrapper um DF-W8-11. Mock-Integration in Phase-1,
Real-Integration in Phase-2. Pre-Action-Hook-Pattern direkt aus DF-W8-11 reused.

[CRUX-MK]
