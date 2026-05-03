---
type: nlm-source-list
notebook_name: KMO-Pipeline-Welle-7-2026-04-30
purpose: Top-Doku-Bundle fuer Martin-Freigabe + Gerdi-CTO-Review
audience: Martin (Initial-Review) + Gerdi-CTO (Handoff-Approval)
crux_mk: true
datum: 2026-04-30
total_sources: 26
---

# NotebookLM-Source-Liste: KMO-Pipeline-Welle-7 [CRUX-MK]

## Zweck
Vollstaendige Quellen-Bundle fuer NotebookLM "KMO-Pipeline-Welle-7-2026-04-30". Dient Martin fuer Initial-Review und Gerdi-CTO fuer Handoff-Approval.

## Setup-Anweisung Martin

1. NotebookLM oeffnen: https://notebooklm.google.com
2. **+ Neues Notebook** → Name: `KMO-Pipeline-Welle-7-2026-04-30`
3. **Quellen hinzufuegen** → "Drive" → naviere zu jeder Quelle aus Liste unten und upload
4. **WICHTIG: Tier-Reihenfolge respektieren** (Tier-1 zuerst, dann Tier-2, dann Tier-3) — Wirkt sich auf NLM-Default-Synthese aus

## Tier-1 Quellen (PFLICHT, 11 Doku-Files in `~/Projects/dark-factories/kmo/docs/` bzw. Drive-Mirror)

Drive-Pfad: `Claude-Knowledge-System/branch-hub/code-mirror/kmo-pipeline-welle-7-2026-04-30/docs/`

| # | Datei | Zeilen | Typ |
|---|-------|--------|-----|
| 1 | 00-INDEX.md | 144 | Master-README + Quick-Start |
| 2 | 01-ARCHITECTURE.md | 320 | Komponenten + 2 Mermaid-Diagramme + SAE-Isomorphie |
| 3 | 02-PIPELINE-FLOWS.md | 396 | E2E + 4 Failure-Modes (7 Mermaid-Diagramme) |
| 4 | 03-API-REFERENCE.md | 1093 | 6 Module API + Code-Beispiele |
| 5 | 04-DEPLOYMENT.md | 468 | Setup + docker-compose Block-fuer-Block + Cloudflare-Tunnel |
| 6 | 05-OPERATIONS.md | 407 | Health/Logs/8 Failure-Modes/Recovery |
| 7 | 06-TESTING.md | 378 | Test-Coverage-Matrix 166/166 PASS |
| 8 | 07-DECISIONS.md | 217 | 3 ARCHITEKT-DECIDED-DCs + Pending-Phronesis |
| 9 | 08-WARGAMES.md | 306 | 3 Cross-LLM-Iter (O 0.70→0.83) + Bias-Catalog |
| 10 | 09-CRUX-RHO.md | 297 | CRUX K_0/Q_0/I_min/W_0 + rho +€500k-2M/J |
| 11 | 10-GLOSSARY.md | 416 | Begriffe konsolidiert |

## Tier-2 Quellen (Specs, 4 Files in `branch-hub/blueprints/`)

| # | Datei | Beschreibung |
|---|-------|-----|
| 12 | SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md | Master-Spec v0.3.0 ADOPT-PILOT-ONLY |
| 13 | SPEC-KMO-DEV-STAGE-CLOUDFLARE-DOCKER-2026-04-30.md | DEV-Stage Architektur |
| 14 | SPEC-KMO-TEST-INFRASTRUKTUR-DEV-STAGE-2026-04-30.md | Test-Infrastruktur |
| 15 | SPEC-LATENZ-ENGINEERING-STACK-2026-04-30.md | TTFB <80ms p99 <200ms Stack |

## Tier-3 Quellen (Wargame-Verdicts, 3 Files in `branch-hub/cross-llm/`)

| # | Datei | Verdict |
|---|-------|---------|
| 16 | 2026-04-30-WARGAME-KMO-PENTAGON-VERDICT.md | Welle-0 MODIFY 3/3 O=0.70 |
| 17 | 2026-04-30-REWARGAME-KMO-WELLE1-VERDICT.md | Welle-1 CONDITIONAL-PROMOTED ~0.74 |
| 18 | 2026-04-30-RE2WARGAME-KMO-WELLE3-VERDICT.md | Welle-3 ADOPT-PILOT-ONLY ~0.83 |

## Tier-4 Quellen (Pre-Production-Findings, 5 Files in `branch-hub/findings/`)

| # | Datei | Verdict |
|---|-------|---------|
| 19 | PRE-3-E2E-FULL-PIPELINE-2026-04-30.md | 5/5 PASS in 0.06s |
| 20 | PRE-4-SHARED-PATH-TEST-2026-04-30.md | PASS-mit-Erkenntnis (Tree-Hash identisch, kein Auto-Sync) |
| 21 | PRE-5-100-THREADS-STRESS-TEST-2026-04-30.md | PASS-FULL (A1: 64ms / A7: p99=72ms) |
| 22 | SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md | 40 Sektionen, 6h Wall-Clock |
| 23 | WARGAME-KMO-HOTSPOT-DIAGNOSE-2026-04-30.md | Hotspot A/B/C geschlossen, D offen |

## Tier-5 Quellen (Demo + Slide-Deck, 3 Files in `~/Projects/dark-factories/kmo/docs/`)

| # | Datei | Beschreibung |
|---|-------|-----|
| 24 | DEMO-MATERIALIEN-MARTIN-GERDI-2026-04-30.md | 8 Pflicht-Felder (Architecture, Test-Report, Live-Demo-URL, Walkthrough, Risk, Rollback, SAE-Isomorphie, Falsifikation) |
| 25 | SLIDE-DECK-MARTIN-GERDI-2026-04-30.md | 30-Folien Slide-Deck (Lead-Enterprise-Architect-Style) |
| 26 | NLM-SOURCE-LIST-KMO-2026-04-30.md | DIESE Datei (zur Selbst-Referenz) |

## NotebookLM-Studio-Panel-Outputs nach Source-Upload

Sobald alle 26 Quellen geladen sind, im NotebookLM Studio-Panel folgende Outputs generieren:

1. **Praesentation** (per /mk Skill-Pflicht-Prompt — 30-Folien Lead-Enterprise-Architect Slide-Deck)
2. **Audio-Uebersicht / Podcast** (Deep-Dive 25-30 Min, Martin-Mobile-Listening, Conversational-Style)
3. **Mind Map** (Architektur-Visual, alle 6 Patches + 3 DCs + Pipeline-Phasen)
4. **Briefing-Dok** (One-Pager fuer Gerdi-First-Look)
5. **Quiz** (Verstaendnis-Check fuer Gerdi, 10 Fragen mit Loesungen)
6. **Studienleitfaden** (Onboarding fuer neuen Engineer)
7. **Zeitleiste** (Welle-7-Build-Sequenz, 6h Wall-Clock breakdown)

Optional: Video-Uebersicht wenn NLM-Account das unterstuetzt.

## Cross-Reference

- Master-Handoff: `branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md`
- Pipeline-Live-URL (lokal): http://localhost:8081/health + http://localhost:8081/demo (BasicAuth martin/change-me)
- Pipeline-Live-URL (Cloudflare): pending OAuth-Setup
- Code-Repo (lokal): `~/Projects/dark-factories/kmo/`
- Code-Mirror (Drive): `branch-hub/code-mirror/kmo-pipeline-welle-7-2026-04-30/`
- GitHub: `meokemmer-jpg/kemmer-knowledge-system` Branch `crash-report-cr-2026-04-19-001` Commit `b0fde0f`

[CRUX-MK]
