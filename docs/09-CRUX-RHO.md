---
type: crux-rho-analysis
target: KMO CRUX-Bindung + rho-Analyse + Falsifikations-Bedingungen + SAE-Isomorphie
status: ADOPT-PILOT-ONLY (CROSS-LLM-2OF3-HARDENED)
priority: HIGH
crux-mk: true
created: 2026-04-30
created-by: mac-heylou-ota-l0-2026-04-30 (Subagent-C TOP-Doku)
parent-handoff: branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md
---

# 09 — CRUX + rho [CRUX-MK]

CRUX-Pfad-Decomposition (K_0/Q_0/I_min/W_0), rho-Berechnungen, Falsifikations-Bedingungen, SAE-Isomorphie-Bezuege fuer KMO-Pipeline.

## CRUX-Verfassung (Kurz-Referenz)

**Oberste Invariante (CRUX-MK):**

```
max INTEGRAL_0^{T_life} [ rho(a,t) * L(t) ] dt
= Vermoegen der Familie Kemmer * Lebensqualitaet ueber Lebenszeit
```

mit
- **rho(a,t)** = CM * Lambda(a,t) - OPEX(a,t) - h * Lambda(a,t) * W(a,t)
- **L(t)** = Lebensqualitaets-Faktor [0,1] (Gesundheit, Familie, Freiheit)
- **T_life** = Lebenserwartung (zu MAXIMIEREN)
- **Nebenbedingungen:** K>=K_0 (Kapitalerhaltung), Q>=Q_0 (Qualitaetsinvarianz), I>=I_min (Ordnungsminimum)

Detail-Verfassung in `~/.claude/CLAUDE.md` §0 + §1.

---

## CRUX-Pfad-Decomposition fuer KMO

### K_0 — Kapitalerhaltung

**Was wird geschuetzt:**

- **Pilot-Hotel-Investment Hildesheim 2026-06-08:** 450-710k EUR
- **Worst-Case 9 P0-Bugs DSGVO:** 30-55k EUR
- **Approval-Theater-Cascade-Schaden:** 50-500k EUR (HOTSPOT-A)
- **Production-Cascade-Schaden:** 50-500k EUR (HOTSPOT-A)
- **DSGVO-Risk via Flat-LLM-Routing:** 25-250k EUR (HOTSPOT-D)
- **Resource-Konkurrenz-Cascade:** 10-75k EUR (HOTSPOT-C)

**Wie wird geschuetzt:**

| Mechanismus | Patch | Schaden-Schutz |
|-------------|-------|----------------|
| Pilot-Trigger autorisiert in **DEV-Stage isoliert** (Cloudflare Tunnel + Mac-Local Docker, ~0-5 EUR/Mo Cost) | Phase-5 DEV-Demo | full Pilot-Cost-Schutz |
| **Production-Trigger gesperrt** bis 5 Pre-Conditions erfuellt | PRE-1..PRE-5 | full Production-Cascade-Schutz |
| **Approval-Gate Dual-Control + Atomic Pre-Deploy-Pipeline** (HMAC-Signed-Tokens + Hash-Chain + Audit-Log) | A4 + A4.2 | -€50-500k |
| **Resource-Lease-System** SQLite-WAL Mutex (DF-Lock + Port-Lock + Token-Lock + Drive-Path-Lock + Tunnel-Lock) | A1 | -€10-75k |
| **Data-Class-Filter** 4-Stufen No-Go-Matrix (Public/Internal/Confidential/Secret) | A5 | -€25-250k DSGVO |
| **Saga-Pattern** mit do/undo-Compensation-Chain (jede Phase rollback-bar) | A2 | -€50-500k Approval-Theater |
| **MHC-Override-Pfad** jederzeit (Edit DC → status REJECTED + Architekt rollt zurueck) | alle DCs | full Architekt-Reversibilitaet |

**Pre-Action-Verification-Pflicht (CLAUDE.md §0 [PRE-ACTION-VERIFICATION-PFLICHT]):**

KMO-Module muessen vor jeder Production-Action verifizieren:
- env_tag (dev/staging/prod) — DEV-Stage isoliert von Production
- Mount-Point/Network-Region
- Backup-Status + Replication-Lag
- blast_radius + Reversibilitaets-Klasse

Pre-Action-Check-Failure = HARD-STOP, kein Auto-Override durch Allow-Liste. Begruendung: PocketOS-Incident 2026-04-27 (Cursor IDE + Opus 4.6: 9-Sek-DB-Delete + Backup-Konvergenz weil env-Tag nicht verifiziert).

### Q_0 — Qualitaetsinvarianz

**Was wird geschuetzt:**

- **Code-Qualitaet** (keine Production-Bugs)
- **Cross-LLM-Bias-Korrelation** (Gefahr: alle LLMs trainiert auf gleichen Korpora, Schein-Konsens)
- **Test-Coverage** (vermeidet False-Green via pytest-Run-Permission)
- **Model-Vergiftung via Output-Loops** (Distillation-Resistenz K12)

**Wie wird geschuetzt:**

| Mechanismus | Beleg |
|-------------|-------|
| **133/133 Tests PASS** (108 post-A6-Refactor + 25 A4.2 Dual-Control) | Empirisch belegt 2026-04-30 |
| **3-stufige Cross-LLM-Wargame-Hardening** (Welle-0 + Welle-1 + Welle-3) | 3 unabhaengige Cross-LLM-Iterationen |
| **4 Bias-Catalog-Layer-Lehren** plus 1 Zusatz-Lehre Cross-LLM-Workspace-Permission | 5 Layer dokumentiert + persistiert |
| **Hotspot A/B/C/D Tracking** (3 von 4 geschlossen post-Welle-3) | konvergent ueber Gemini + Copilot |
| **A5 Data-Class-Filter** mit 9 SECRET-Patterns inkl. Bearer-JWT-Fix | 32/32 Tests PASS post-Bug-Fix |
| **Pre-Action-Verification-Pflicht** (K13 Independent-Ground-Truth) | CRUX-Niveau-Invariante CLAUDE.md §0 |

### I_min — Ordnungsminimum

**Was wird geschuetzt:**

- **Strukturierte 7-Phasen-Pipeline** (Plan → Spec → Wargame → Build → Test → DEV-Demo → Martin-Freigabe → Gerdi-CTO)
- **3-Layer-Hierarchie** (Control / Governance / Executors) mit Cross-Layer-Audit-Trail
- **4-Welle-Build-Pattern** (Welle-1 + Welle-2 + Welle-3 + Welle-4 PRE-Production)
- **5-Pre-Production-Bedingungen** (PRE-1..PRE-5) mechanisch enforced
- **Decision-Card-Disziplin** (alle Architekt-Decisions dokumentiert mit MHC-Override-Pfad)

**Wie wird geschuetzt:**

| Mechanismus | Beleg |
|-------------|-------|
| **A6 Control/Data-Plane-Separation** Repository-Restructuring kmo_control/governance/executors | Welle-4 PRE-1 COMPLETE |
| **Action-Log + Permission-Log + Workflow-State** drei parallele Audit-Streams | rules/audit-trail.md |
| **Trinity-Pattern** auf evaluatorischer Ebene (3 Optionen Conservative/Aggressive/Contrarian pro DC) | rules/trinity-evaluatorisch.md |
| **Cross-LLM-Pflicht-E3-Plus** fuer Meta-Audit | rules/cross-llm-pflicht-e3-plus.md |
| **Wargame-First-Pflicht** vor Implementation | rules/wargame-first-pflicht.md |

### W_0 — Working-Capital-Optimierung

**Was wird optimiert:**

- **Token-Engpass-Hierarchie:** Martin-Zeit > Claude-Opus-Tokens > Flat-LLMs (alle Sunk-Cost)
- **Architekt-Bandbreite:** Welle-7-Autonomie ohne Phronesis-Outsourcing (Bias-Catalog Layer 1+2)
- **Subagent-Pool-Pattern:** Sonnet-Default fuer Routine, Opus minimal

**Wie wird optimiert:**

| Mechanismus | Empirisch belegt |
|-------------|------------------|
| **Architekt ~25-35k Opus-Tokens** fuer 5500+ LoC + 3 Wargames + 4 Wellen | 2026-04-30 Session |
| **Faktor 10-15x Token-Spar** via Sonnet-Pool (10 Subagent-Dispatches) | vs Solo-Architekt-Implementation (~250-400k Opus-Tokens) |
| **0 EUR marginal** fuer 9 Cross-LLM-Calls (3 Wargames × 3 LLMs) | Codex Pro + Gemini-CLI-OAuth + Copilot Pro+ alle Sunk-Cost-Flat |
| **DEV-Demo Cost** 0-5 EUR/Mo (Cloudflare free-tier + Mac-Hardware Sunk-Cost) | Phase-5 Skeleton |

---

## rho-Analyse

### Capex-Aufwand (einmalig)

| Posten | Marginal-Cost | Begruendung |
|--------|---------------|-------------|
| Hardware (Mac M4 Max) | ~€0 | Sunk-Cost (existing) |
| Subscriptions (Claude Pro/Max + Codex Pro + Copilot Pro+ + Grok Heavy + Gemini Ultra + Perplexity Ultimate) | ~€0 | Sunk-Cost (existing, ~€600-1000/Mo flat) |
| Cloudflare Tunnel (free-tier) | €0 | free-tier ausreichend |
| Architekt-Zeit (Welle-7-autonom) | ~25-35k Opus-Tokens | Cost-of-Compute, ~$2-5 |
| Subagent-Pool-Tokens | ~250-400k Sonnet-Tokens | Cost-of-Compute, ~$5-15 |
| **Total Capex einmalig** | **~$10-25** | Welle-1+2+3+4 Build (5500 LoC) |

### Opex-Estimate (laufend)

| Posten | Cost/Mo (7 Hotels) | Begruendung |
|--------|--------------------|-------------|
| Cloudflare Workers + KV (Latenz-Stack DC-3) | €100-500 | Edge-Cache + KV |
| Aurora-Serverless v2 (Latenz-Stack DC-3) | €200-500 | Materialized-View, less Compute-heavy |
| ECS-Fargate Async-Refresh (Latenz-Stack DC-3) | €100-400 | low-priority, scheduled-scale |
| AI-API-Calls (Refresh-only) | €100-500 | nicht per Request |
| **Latenz-Stack Total** | **€500-1900** | gemittelt €1200/Mo |
| KMO-DEV-Stage (Cloudflare Tunnel + Mac-Local) | €0-5 | free-tier |
| KMO-Production-Hosting (post Production-Deploy) | tba | abhaengig von Region-Choice |

### rho-Hypothese (post Production-Deploy)

**Geschaetzt:** **+€500k-€2M/Jahr** bei Production-Skalierung. Decomposition:

| Quelle | rho-Hebel | Begruendung |
|--------|-----------|-------------|
| **Token-Cost-Reduction Mac-Opus-Routing** | +€100-300k/J | KMO-Routing reduziert Opus-Tokens 60-80% (rules/token-engpass-hierarchie.md) |
| **DF-Coordination Multi-Machine** | +€50-200k/J | Outbox-Pattern + Saga vermeidet Lost-Updates + Cascade-Failures |
| **Approval-Theater-Schutz** | +€50-500k/J | A4+A4.2 verhindert Production-Cascade (Codex Worst-Case-Schaetzung) |
| **DSGVO-Risk-Reduktion** | +€25-250k/J | A5 Data-Class-Filter blockiert Sensitive-Data-an-Flat-LLMs |
| **Build-Test-Demo-Pipeline-Latenz-Reduktion** | +€20-50k/J | 7-Phasen-Pipeline + Subagent-Pool reduziert Cycle-Time |
| **HeyLou ABS-Region-Hybrid Yield-Gain** (DC-1, indirekt via KMO-Enabling) | +€250-650k/J | +6-12% ADR gemittelt 7 Hotels |
| **Total** | **+€500k-€2M/J** | Sum mit Lambda-Skalierung |

### Break-Even-Rechnung

- **Capex einmalig:** ~$25 (10-25 USD)
- **Opex Laufend (Latenz-Stack):** ~€500-1900/Mo = ~€6-23k/J
- **Total Cost (Y1):** ~€25k
- **rho-Gain:** +€500k-€2M/J
- **Break-Even:** **~3-7 Tage** (wenn rho-Hypothese halbwegs zutrifft)
- **ROI Y1:** **20-80x**

---

## Falsifikations-Bedingungen-Liste

KMO-Pipeline ist falsifiziert wenn:

### Pipeline-Falsifikationen

1. **E2E-Test post-Retry > 1 von 5 FAIL-Tests** → Welle-5 Bug-Fix-Cycle erforderlich
2. **Codex-Tail (180k Bytes pending) signifikant divergent** zu Gemini+Copilot (z.B. REJECT) → Verdict-Tier auf CONDITIONAL zurueckstufen
3. **Pilot-Run scheitert** (Docker-Build-Fail / Cloudflare-Tunnel-Latency / Test-Cases-Verdicts inkonsistent)
4. **Martin-Demo-Reject** → Demo-Materialien ueberarbeiten, kein direkter Production-Pfad
5. **Gerdi-CTO-Reject** (Production-Quality nicht erreicht) → Implementation-Patches nach Gerdi-Feedback
6. **Production-Deploy schlaegt fehl in ersten 30 Tagen** → Welle-6 Production-Bug-Fixes

### Architektur-Falsifikationen (KMO selbst)

7. **Build-Test-Demo-Pipeline-Latenz > 2 Wochen pro DF** (zu langsam) → Pipeline-Restruktur
8. **Token-Cost > 50% Pre-KMO-Baseline** (kein Spar-Effekt) → Routing-Capability-Matrix revidieren
9. **Martin-Freigabe-Quote < 60%** (zu schlecht vorbereitet) → Demo-Materialien-Template ueberarbeiten
10. **Gerdi-CTO-Reject-Quote > 30%** (Production-Quality nicht erreicht) → Test-Pipeline + Security-Standards verschaerfen

### Domain-Falsifikationen (DC-1/DC-2/DC-3)

11. **Pilot-Hildesheim Yield-Differential < 4% ADR** (vs predicted +6-12% Hybrid) → Tier-Downgrade auf Smart-Kategorien
12. **Apaleo-API-Latenz > 200ms p50 chronisch** → Stack-Wechsel zu Mews-Primary erwaegen
13. **Mews-Shadow-Cost > €5k/Monat pro Hotel** → Shadow rausnehmen, ABS-Tier herunterstufen
14. **DSGVO-Audit-Fail trotz P0-Bug-Sprint** → Stack-Konflikt war nicht Wurzelproblem
15. **p99 Latenz > 300ms in >5% der Requests** → Architektur revidieren
16. **Stale-Marker > 1% der Requests** → AI-Refresh-Worker-Skalierung
17. **AI-API-Cost > €500/Monat fuer 1 Pilot-Hotel** → Modell-Wahl revidieren (lokales Modell statt Cloud-API)

---

## SAE-Isomorphie-Bezuege

KMO-Architektur isomorph zu SAE v8 Pattern:

### Trinity-Pattern (3 Varianten Conservative/Aggressive/Contrarian)

- **SAE:** 200 Slots × 3 Varianten = 600 Agenten, Best-of-3 wins (`core/trinity.py`)
- **KMO:** 3 Optionen pro Architektur-Decision (DC-1/DC-2/DC-3 + 7 Patches), Architekt waehlt mit Begruendung

Detail: rules/trinity-evaluatorisch.md.

### Hamilton-Funktion H = u + lambda*f

- **SAE:** Trade-Off zwischen Sofort-Gain (u) und Zukunftswert (lambda*f) auf Slot-Ebene (`core/hamilton.py`)
- **KMO:** Welle-7-Autonomie balanciert kurzfristig (Pipeline-Latenz reduzieren) vs langfristig (Production-Stabilitaet, K_0-Schutz)

### Bounded-Veto (myz33)

- **SAE:** COSMOS kann Operation veto'en bei `complexity >= 0.8` mit Eskalation an Manager
- **KMO:** Pre-Action-Verification + Approval-Gate Dual-Control + STOP.flag-Pattern als Bounded-Veto auf Module-Ebene

### Myzel-Layer Event-Bus

- **SAE:** MYZ-30 Event-Router + MYZ-32 Dispatcher fuer Inter-Agent-Kommunikation
- **KMO:** A3 Outbox-Pattern als persistenter Event-Bus zwischen Mac/Windows/Mobile (durable Dispatch-Queue + idempotent Consumer + DLQ)

### COSMOS Compliance-Layer

- **SAE:** Compliance-Oversight-Safeguard-Monitoring-Sovereignty als nicht-deciding Governance-Schicht
- **KMO:** kmo_governance/ Layer (approval-gate + lease-manager + data-class-filter + saga-pattern + outbox-pattern + durable-execution) ist KMO-COSMOS

### F_CUM_DECAY Relegation

- **SAE:** F_CUM_DECAY = 0.98 fuer langsame Relegation (HWZ ~34 Tage)
- **KMO:** DF-Agile-Adaptation rules/df-agile-adaptation.md mit Drift-basierter Frequenz-Anpassung

### Lambda-Honesty (M2)

- **SAE:** `core/crux.py::validate_rho_action` markiert nicht-kalibrierte Werte
- **KMO:** Bias-Catalog Layer 3+4 (Context-Overestimation), rules/meta-governance-framework.md G2 Lambda-Honesty

### T_CAP = 50000 Tokens

- **SAE:** harte Obergrenze pro Agent
- **KMO:** Architekt-Opus-Token-Budget (~25-35k pro Welle), Subagent-Sonnet-Budget (~250-400k pro Welle), Cross-LLM-Calls (Sunk-Cost-Flat)

---

## Implementation-rho pro Patch (rho-optimierte Reihenfolge)

| # | Patch | Effort | Schaden-Schutz | rho/h |
|---|-------|--------|----------------|-------|
| 1 | A4 Approval-Gates | 4-8h | -€50-500k | **hoechster** |
| 2 | A1 Resource-Lease | 6-10h | -€10-75k | hoch |
| 3 | A5 Daten-Klassifikation | 3-5h | -€25-250k | hoch |
| 4 | A2 Saga-Pattern | 8-12h | -€50-500k | mittel |
| 5 | A3 Outbox-Pattern | 6-10h | Multi-Machine-Konsistenz | mittel |
| 6 | A6 Control/Data-Plane | 4-6h | Architektur-Sauberkeit | niedrig |
| 7 | A7 Durable-Execution | 12-20h | Crash-Resilienz | niedrig (zuletzt) |

**Total: 43-71h.**

---

## CRUX-MK Continuation-Pflicht (KMO-Pipeline)

Naechste Mac-Session bei Continuation:

1. **Bootstrap-Pflicht:** CLAUDE.md §0.2 + parallel-session.md §1
2. **Read this Master-Handoff** priorisiert ueber alte Handoffs (`branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md`)
3. **PRE-3 E2E-Test** als next-Action (Subagent-Retry oder Architekt-direkt)
4. **PRE-4 + PRE-5** parallel
5. **Pilot-Run** in DEV-Stage
6. **Demo-Materialien** + Martin-Freigabe + Gerdi-CTO

---

## Cross-Reference

- **Master-Spec:** `branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md`
- **Master-Handoff:** `branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md`
- **Decisions:** [07-DECISIONS.md](07-DECISIONS.md)
- **Wargames:** [08-WARGAMES.md](08-WARGAMES.md)
- **Glossar:** [10-GLOSSARY.md](10-GLOSSARY.md)
- **Hotspot-Diagnose:** `branch-hub/findings/WARGAME-KMO-HOTSPOT-DIAGNOSE-2026-04-30.md`

[CRUX-MK]
