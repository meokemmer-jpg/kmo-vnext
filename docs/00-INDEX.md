---
type: master-index
target: KMO Kemmer-Master-Orchestrator Dokumentation
status: PIPELINE-LIVE-PRE-PRODUCTION (Welle-7 LIVE, ADOPT-PILOT-ONLY)
priority: HIGH
crux-mk: true
created: 2026-04-30
created-by: mac-heylou-ota-l0-2026-04-30 (Subagent-C TOP-Doku)
audience: Architekt + Martin (Phronesis) + Gerdi-CTO (Production-Approval)
---

# KMO — Kemmer-Master-Orchestrator [CRUX-MK]

**Master-Index der TOP-Dokumentation. Stand 2026-04-30, Welle-7 LIVE, Verdict ADOPT-PILOT-ONLY (CROSS-LLM-2OF3-HARDENED).**

## Was ist KMO?

**KMO** ist ein Master-Orchestrator-Layer ueber alle bestehenden Komponenten der Kemmer-Architektur:

- **28 LaunchAgents** (DF-06/10/12-v2/15/43-86)
- **72 Skills** (in `~/.claude/skills/`)
- **Subagent-Pool** (Explore, general-purpose, Plan, feature-dev:*, code-reviewer)
- **5 Flat-LLM-Pools** (Codex GPT-5.4, Gemini 2.5 Pro, Grok-Heavy, Copilot Pro+, Perplexity Ultimate)

KMO ist **Architekt-Welle-7-Gateway** das Tasks ueber eine Capability-Matrix routet, Token-sparend (Sunk-Cost-Abos maximal), Multi-Machine-tauglich (Mac-M5 + Windows-Vault + PC1 + Yogamobil + Xiaomi-Mobil), und eine **Build-Test-Demo-Approval-Pipeline** technisch durchsetzt.

## Was tut KMO?

7-Phasen-Pipeline (sequenziell, jede Phase mit Owner + Token-Profil + Output):

| # | Phase | Owner | Token-Profil | Output |
|---|-------|-------|--------------|--------|
| 1 | Plan + Spec | Architekt (autonom) | Opus minimal | DC + Spec-Files |
| 2 | Wargame-Pentagon | KMO orchestriert Codex+Gemini+Copilot+Grok | Flat-LLM (0 EUR marg.) | Cross-LLM-Verdict |
| 3 | Build | DF-Code via Subagent (Sonnet) ODER Codex CLI | Flat-LLM | Code in `~/Projects/dark-factories/<DF>/` |
| 4 | Test | Test-Suite (Smoke + Integration + E2E) | Subagent (Sonnet) | Test-Reports |
| 5 | DEV-Demo | Mac-Local Docker-Compose + Cloudflare Tunnel | Architekt-Setup | Demo-URL + Materialien |
| 6 | Martin-Freigabe | Martin (MHC explizit) | — | Signed Approval-Token |
| 7 | Gerdi-CTO-Review | Gerdi (CTO Hofstede SAE v8.0) | — | Production-Approval |

## Wer ist die Zielgruppe?

- **Architekt (Mac-Opus):** Welle-7-autonome Orchestrierung mit Welle-Verlauf-Status
- **Martin Kemmer (Phronesis):** K_0/Q_0/L13-Decisions, MHC-Override, Demo-Review
- **Gerdi (CTO):** Production-Approval, Code-Review, Security, SAE-Isomorphie-Check

## Status-Snapshot (2026-04-30)

- **Code:** 5500+ LoC Python in 7 Modulen, 133/133 Tests PASS
- **Verdict:** CROSS-LLM-2OF3-HARDENED-ADOPT-PILOT-ONLY (Welle-3 Re-Re-Wargame)
- **O_total:** ~0.83 (Architekt-Ziel >=0.65 erfuellt, Production-Ziel >=0.78 erfuellt)
- **Pre-Production-Bedingungen:** PRE-1 (A6 Repo-Restructuring) + PRE-2 (A4.2 Dual-Control) COMPLETE; PRE-3 (E2E-Test Rate-Limited-Retry) + PRE-4 (Drive-Sync-Test) + PRE-5 (100-Threads-Stress) pending
- **Pipeline-Position:** Phase-5 DEV-Stage Skeleton ready, docker-compose Build pending, dann Pilot-Run + Martin-Freigabe + Gerdi-CTO

## Inhaltsverzeichnis

| File | Domain | Zweck |
|------|--------|-------|
| [00-INDEX.md](00-INDEX.md) | Master-README | Diese Datei. Top-Level-Uebersicht + Quick-Start |
| [01-ARCHITEKTUR.md](01-ARCHITEKTUR.md) | Architektur | 3-Layer (Control/Governance/Executors), Module, Diagramme |
| [02-PIPELINE.md](02-PIPELINE.md) | Pipeline | 7-Phasen mit Owner-Matrix + Token-Profil + State-Transitions |
| [03-MODULES.md](03-MODULES.md) | Module | 6 governance-Module Detail-Doku (A1-A7 Patches) |
| [04-PATTERNS.md](04-PATTERNS.md) | Patterns | Saga, Outbox, Resource-Lease, Approval-Gate, Data-Class-Filter, Durable-Execution |
| [05-TESTS.md](05-TESTS.md) | Tests | 133/133 Tests Layer-Decomposition (Smoke + Integration + E2E) |
| [06-DEV-STAGE.md](06-DEV-STAGE.md) | DEV-Stage | Docker-Compose + Cloudflare Tunnel + Mac-Local-Setup |
| **[07-DECISIONS.md](07-DECISIONS.md)** | **Decisions** | **3 ARCHITEKT-DECIDED-DCs + Pending-Phronesis + K_0-Sperr-Mapping** |
| **[08-WARGAMES.md](08-WARGAMES.md)** | **Wargames** | **3 Cross-LLM-Iterationen + Verdict-Tier-Hierarchie + Bias-Catalog** |
| **[09-CRUX-RHO.md](09-CRUX-RHO.md)** | **CRUX + rho** | **CRUX-Pfad + rho-Berechnungen + Falsifikations-Bedingungen + SAE-Isomorphie** |
| **[10-GLOSSARY.md](10-GLOSSARY.md)** | **Glossar** | **Begriffe konsolidiert (KMO, A1-A7, ABS, CRUX, etc.)** |

**Bold = Subagent-C Output (diese Welle).** Files 01-06 sind Subagent-A (Architektur) + Subagent-B (Tests) Verantwortung.

## Quick-Start (5-10 Minuten von Zero zu KMO-running)

### Voraussetzungen

- macOS (Sonoma+ getestet)
- Python 3.11+
- Docker Desktop (fuer Phase-5 DEV-Demo)
- Cloudflare-Account (free-tier reicht, fuer Tunnel)
- Git (fuer Repo-Clone)

### Setup

```bash
# 1. Repository-Pfad
cd ~/Projects/dark-factories/kmo

# 2. Virtual-Env (empfohlen)
python3 -m venv .venv
source .venv/bin/activate

# 3. Dependencies (pro Modul lokal definiert)
pip install -r kmo_governance/approval-gate/requirements.txt
pip install -r kmo_governance/lease-manager/requirements.txt
# ... weitere Module siehe 03-MODULES.md

# 4. Tests laufen lassen
pytest kmo_governance/  # Erwartet: 133/133 PASS
```

### Smoke-Test

```bash
# Health-Check des Gateway-Stubs (Phase-5 Skeleton)
cd dev-stage/
docker compose up -d
curl http://localhost:8080/health
# Erwartet: {"status": "ok", "kmo_version": "0.3.0", "pre_production": true}
```

### Wo es weitergeht

1. **Welle-7 Pipeline-Status:** Pre-Production-Phase, Phase-5 DEV-Stage Skeleton ready
2. **PRE-3 E2E-Test:** Rate-Limited-Retry pending — siehe [05-TESTS.md](05-TESTS.md)
3. **Pilot-Run:** Build-vs-Buy-Gate als 1. live KMO-DF — siehe [06-DEV-STAGE.md](06-DEV-STAGE.md)
4. **Martin-Demo:** Demo-Materialien fuer 8 Pflicht-Felder — siehe [02-PIPELINE.md](02-PIPELINE.md)
5. **Gerdi-CTO-Handoff:** Production-Approval-Package — siehe [02-PIPELINE.md](02-PIPELINE.md)

## Glossar-Verweis

Alle Begriffe (KMO, A1-A7, Welle-7, Trinity-Pattern, Saga, Outbox, ADOPT-PILOT-ONLY, ABS-Pricing, Region-Hybrid, CRUX, K_0, Q_0, rho, Sunk-Cost-Flat-LLMs, Phronesis, MHC, etc.) sind in [10-GLOSSARY.md](10-GLOSSARY.md) konsolidiert.

## CRUX-Bindung (Kurzform)

- **K_0** Pilot-Trigger autorisiert in DEV-Stage (isoliert), Production gesperrt bis 5 Pre-Conditions erfuellt
- **Q_0** 133/133 Tests + 3-stufige Cross-LLM-Wargame-Hardening + 4 Bias-Catalog-Layer
- **I_min** 7-Phasen-Pipeline + 4-Welle-Build + 3-Layer-Hierarchie strukturiert
- **W_0** Token-Spar-Pattern bewaehrt (Architekt ~25-35k Tokens fuer 5500+ LoC + 3 Wargames)
- **rho** geschaetzt +€500k-€2M/J bei Production-Skalierung (Token-Cost-Reduction + DF-Coordination + Approval-Theater-Schutz)

Detail-Begruendung in [09-CRUX-RHO.md](09-CRUX-RHO.md).

## MHC-Override-Pfad

Alle Architekt-Decisions sind unter Welle-7-Autonomie getroffen. **Martin-Override jederzeit** moeglich:

1. Edit der Decision-Card (z.B. `Claude-Vault/docs/decision-cards/DC-HEYLOU-ABS-TIER-2026-04-30.md`) — `status` auf REJECTED + Begruendung
2. Architekt rollt zurueck (Pre-Implementation-State, ~1h Aufwand)
3. Neue Tier-Wahl + neue DC

Implementation-Trigger sind **K_0-Sperr-pflichtig** (Phronesis-non-delegate). Tier-Wahl + DCs sind Welle-7-autonom.

[CRUX-MK]
