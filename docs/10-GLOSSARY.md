---
type: glossary
target: KMO Dokumentation Begriffe konsolidiert
status: active
priority: MEDIUM
crux-mk: true
created: 2026-04-30
created-by: mac-heylou-ota-l0-2026-04-30 (Subagent-C TOP-Doku)
---

# 10 — Glossary [CRUX-MK]

Konsolidierter Begriffs-Index fuer KMO-Dokumentation. Alphabetisch nach Domain gruppiert.

---

## A. KMO-Architektur + Patches

### KMO

**Kemmer-Master-Orchestrator.** Master-Orchestrator-Layer ueber 28 LaunchAgents + 72 Skills + Subagent-Pool + 5 Flat-LLM-Pools. Architekt-Welle-7-Gateway das Tasks ueber Capability-Matrix routet, Token-sparend, Multi-Machine-tauglich, Build-Test-Demo-Approval-Pipeline durchsetzt.

### A1 Resource-Lease (P-KMO-A1)

Zentrales Mutex/Lease-System fuer alle shared Resources: DF-Lock (verhindert Concurrent-Spawn analog K16), Port-Lock (TCP-Port), Token-Lock (API-Key/Provider), Drive-Path-Lock (File-Pattern), Tunnel-Lock (Cloudflare). SQLite-WAL-Backend, Heartbeat 60s, TTL 300s, STOP.flag-Respect-Test. **Status:** DONE 18/18 PASS production-tauglich.

### A2 Saga-Pattern (P-KMO-A2)

Jede Phase 1-7 hat `do(input) -> output` Forward-Action und `undo(output) -> rollback_state` Kompensations-Logic. Phase-State persistent in `branch-hub/workflow-state/<KMO-Run-ID>-state.json`. Bei Phase-N-Fail: undo Phase-N → Phase-N-1 → ... → Phase-1. Schaden-Schutz -€50-500k Approval-Theater. **Status:** DONE 9/9 PASS.

### A3 Outbox-Pattern (P-KMO-A3)

Durable Dispatch-Queue zwischen Mac/Windows/Mobile. Producer schreibt Event in `branch-hub/outbox/<machine>-<topic>-<seq>.json` (atomic write). Consumer (anderer Branch) liest, processed, schreibt Acknowledgement. Idempotent Consumer-Regel + Dead-Letter-Queue bei Fail nach 3 Retries. Multi-Machine-Konsistenz-Schutz. **Status:** DONE 6/6 PASS post-Idempotency-Fix.

### A4 Approval-Gate (P-KMO-A4)

Approval ist NICHT prozessual sondern technisch enforced: Production-Credentials separat von DEV, Deploy-Lock pro Production-Resource, Signed Approval-Tokens (HMAC + 24h-TTL + single-use), Immutable Audit-Log (append-only, hash-verkettet). Pre-Deploy-Hook prueft Token-Validity. **Status:** DONE 18/18 PASS, post-A4.2 Welle-4 Dual-Control + Atomic Pre-Deploy-Pipeline (+25/25 Tests).

### A5 Data-Class-Filter (P-KMO-A5)

Pre-Routing-Filter klassifiziert jeden Input/Prompt in 4 Stufen:

- **Class-1 PUBLIC:** kein Constraint
- **Class-2 INTERNAL:** nur an Codex/Gemini/Grok mit dokumentiertem Datenvertrag
- **Class-3 CONFIDENTIAL:** nur Claude-Opus + lokale Modelle (Ollama Mac), KEINE Flat-LLMs
- **Class-4 SECRET (Credentials, Customer-PII, Finance, Legal):** KEINE LLMs, nur Architekt + verschluesselte Storage

9 SECRET-Patterns inkl. Bearer-JWT-Fix. **Status:** DONE 32/32 PASS.

### A6 Control/Data-Plane Separation (P-KMO-A6)

KMO ist pure Control-Layer. Repository-Restructuring kmo_control/governance/executors. **Trennung-Regeln:** kmo_control/ darf NICHT direkt in DFs schreiben (nur via Lease-Manager + Approval-Gate-Calls). df_executors/ haben KEINE Sicht auf andere DFs (Bulkhead-Isolation). kmo_governance/ Module sind shared services. Cross-Service-Kommunikation NUR via Outbox-Pattern (async) bei sync via Lease-API + Approval-API. **Status:** Spec-Welle-3 + Code-Welle-4 PRE-1 COMPLETE.

### A7 Durable-Execution (P-KMO-A7)

Persistente State-Machine fuer 7-Phasen-Workflows. Workflow-State serialisiert in `branch-hub/workflow-state/`. Crash-Recovery bei Restart letzter State geladen + Phase fortgesetzt. Event-Sourcing fuer Routing-Decisions, DF-Statuswechsel, STOP.flag-Transitions, Approval-States. Trinity-Wahl: Conservative (Self-Built JSON-State, Empfehlung). **Status:** DONE 18/18 PASS.

### Welle-7

User-Direktive 2026-04-30 *"bis hin zum Coden darfst du alles machen ... baue dir ein Dark Faktory Betriebsgelaende"*. Architekt-Mandat fuer **Code + DF-Building + Wargame-Execution + Subagent-Pool-Orchestrierung autonom**. Pipeline-Erweiterung: Build → Test → DEV-Demo (Docker) → Martin-Freigabe → Gerdi-CTO-Review.

### Welle-7-Pipeline

7 Phasen sequenziell: Plan + Spec → Wargame-Pentagon → Build → Test → DEV-Demo → Martin-Freigabe → Gerdi-CTO-Review. Each Phase mit Owner + Token-Profil + Output-Pflicht.

### kmo_control / kmo_governance / df_executors

3-Layer-Hierarchie post A6-Refactor. **kmo_control/** = Layer 3 Architekt-Routing-Gateway (Phase-5 Stub, kmo_router.py, kmo_capability_matrix.yaml). **kmo_governance/** = Layer 3 shared services (approval-gate, lease-manager, data-class-filter, saga-pattern, outbox-pattern, durable-execution). **df_executors/** = Layer 2 isolierte Pilot-DFs (Data-Plane).

---

## B. Wargames + Verdict-Tiers

### CONDITIONAL

Default-Verdict-Tier fuer E3-Aussagen ohne Cross-LLM-Validation. Single-Model oder unzureichende Konsens-Belegung. Pragmatisch auf HARDENED aufwertbar in formalisierten Systemen via empirische rho-Gain-Messung.

### CROSS-LLM-SIMULATION-HARDENED

Eine Stufe unter echter HARDENED. Single-Model spielt mehrere Perspektiven (z.B. Opus 4.7 simuliert Codex+Gemini+Grok). Honest Labeling Pflicht: welches Basis-Modell, warum keine echten LLMs.

### CROSS-LLM-2OF3-HARDENED

2 von 3 LLMs konvergent, G1-G7 erfuellt + G8-G12 geprueft. **KMO Welle-3-Verdict.** Voll-Konvergenz mit 3+ Modellen wuerde HARDENED ergeben.

### ADOPT-PILOT-ONLY

Verdict-Untertyp von CROSS-LLM-2OF3-HARDENED: Pilot-Trigger fuer DEV-Stage **autorisiert**, Production-Trigger **gesperrt** bis Pre-Production-Bedingungen erfuellt. **KMO Welle-3-Status post 2026-04-30.**

### HARDENED

3+ Modelle konvergent + externe Ankerung, voll G1-G14 erfuellt. Selten auf E4 wegen Cross-Model-Korrelation.

### HARDENED-PRODUCTION

HARDENED + Produktions-Stichprobe + Brier-Score-Kalibrierung empirisch belegt.

### FIXPUNKT-HARDENED

E5 strukturell-logisch zwingend, selbst-konsistent. Nur 4 Fixpunkte (Asymmetrie, Ebenen-Kollaps-Verbot, Pragmatisches-Akzeptanz-Kriterium, Endlichkeit).

### ARCHITEKT-DECIDED

DC-Status fuer Architekt-Welle-7-autonome Decision mit Trinity-Optionen + Empfehlung + MHC-Override-Pfad. NICHT Phronesis-Outsourcing wenn nicht K_0/Q_0/L13-relevant.

### Pentagon-Wargame

5-Ordnungs-Audit (O1 Existenz / O2 Konsistenz / O3 Adversarial / O4 Spieltheorie / O5 Systemtheorie) + Multi-LLM-Adversarial + Iteration-Gate. KMO Welle-0 = O_total 0.70 → 7 CRIT-Patches A1-A7.

### Hotspot

Konvergent-identifizierte Schwachstelle aus 3-LLM-Cross-LLM-Wargame mit CRIT/HIGH/MED-Klassifikation. KMO 4 Hotspots: A Approval-Theater (CRIT) / B Multi-Machine-Sync (HIGH) / C Resource-Konkurrenz (HIGH) / D Daten-Klassifikation (MED).

### Trinity-Pattern (3 Optionen)

3 Optionen mit unterschiedlicher Risiko/Reward-Charakteristik: **Conservative** (bewaehrt, langsam, geringes Risiko), **Aggressive** (schnell, hoch-Reward, hoeheres Risiko), **Contrarian** (gegen-intuitiv, oft hybrid, fragt Frame in Frage). Pflicht in evaluativen Kontexten (rules/trinity-evaluatorisch.md).

### O_total

5-Ordnungs-Score-Aggregation: 0.1×O1 + 0.15×O2 + 0.25×O3 + 0.25×O4 + 0.25×O5. **KMO-Trajektorie:** Welle-0 0.70 → Welle-1 ~0.74 → Welle-3 ~0.83.

### Re-Wargame

Iteratives Cross-LLM-Wargame nach Patch-Implementation. Pflicht bis O_total >= 0.78 fuer Production-Approval.

---

## C. CRUX-Verfassung + Zeitwert

### CRUX (CRUX-MK)

**Oberste Invariante (CRUX-MK):**
```
max INTEGRAL_0^{T_life} [ rho(a,t) * L(t) ] dt
```
Vermoegen der Familie Kemmer × Lebensqualitaet ueber Lebenszeit. Wenn eine Aktion dieses Ziel nicht foerdert: REJECT.

### K_0 (Kapitalerhaltung)

Harte Nebenbedingung K >= K_0. Kein Substanzverzehr. KMO schuetzt K_0 via Pilot-DEV-Isolation, Production-Gesperrt bis Pre-Conditions, Approval-Gate Dual-Control, MHC-Override-Pfad.

### Q_0 (Qualitaetsinvarianz)

Harte Nebenbedingung Q >= Q_0. Keine Degradation von Produkt, Marke, Prozess, Information. KMO schuetzt Q_0 via 133/133 Tests + 3-stufige Cross-LLM-Wargame-Hardening + 5 Bias-Catalog-Layer.

### I_min (Ordnungsminimum)

Harte Nebenbedingung I_Ordnung >= I_min. IT, Prozesse, Dokumentation, Governance. KMO erfuellt via 7-Phasen-Pipeline + 4-Welle-Build + 3-Layer-Hierarchie + 5 Pre-Production-Bedingungen.

### W_0 (Working Capital)

Term `h * Lambda(a) * W(a)` in rho-Formel. Gebundenes Working Capital × Zeitwert. KMO optimiert W_0 via Token-Spar-Pattern (Architekt ~25-35k Opus-Tokens fuer 5500+ LoC + 3 Wargames).

### rho (a, t)

Zielfunktion: `rho(a,t) = CM * Lambda(a,t) - OPEX(a,t) - h * Lambda(a,t) * W(a,t)`. Einheit EUR/Zeit. CM = Deckungsbeitragsmarge, Lambda = Engpass-Durchsatz min(D, mu_b), OPEX = operative Kosten, W = gebundenes Working Capital, h = Zeitwert-/Kapitalkostensatz.

### Lambda

Engpass-Durchsatz `Lambda(a) := min{D, mu_b(a)}` (Theory-of-Constraints, TOC). Demand `D` × Bottleneck-Capacity `mu_b`.

### h (Zeitwert)

Zeitwert-/Kapitalkostensatz, typisch 0.08-0.15/Jahr fuer Kemmer-System. Bestraft gebundenes Working Capital ueber Zeit.

### Hamilton-Funktion H = u + lambda*f

Trade-Off-Aggregation in SAE: `H = u(jetzt) + lambda * f(Zukunft)`. Sofort-Gain (u) und Zukunftswert (f) kalibriert ueber lambda.

### Phronesis (L13)

Praktische Weisheit, normativ-strategische Decisions. **Nicht delegierbar** an Agent: bei normativ-strategischen Decisions (CRUX-Werte, Familien-Werte, Hotel-DNA): NICHT entscheiden. Martin Optionen geben, Trade-offs explizit machen, ihn fragen lassen. (rules/leadership.md L13).

### MHC (Meaningful Human Control)

Bevorzugter Term fuer Human-on-the-Loop. Override-Pfad fuer Architekt-autonome Entscheidungen. Edit der Decision-Card → status REJECTED + Begruendung. Architekt rollt zurueck (~1h Aufwand).

### K_0-Sperr-Liste

Aus rules/passivitaets-hemmung.md §K_0-Sperr-Liste: 7 Sperr-Items wo Architekt MUSS Phronesis-Frage stellen (Budget >€10k, Brand-Wechsel, Familien-Beziehungs-Aenderung, Rechtliche/Steuer-Auslegung, Cross-System-Architektur-Wechsel >4h Rollback, neue CRUX-Nebenbedingung, Familien-Gesundheit-Decisions).

### Bias-Catalog

Persistente Eigenfehler-Lehren in `branch-hub/learnings/bias-catalog.jsonl`. KMO-Pipeline 5 Layer dokumentiert: Phronesis-Outsourcing-NLM, Phronesis-Outsourcing-K0-Sperr, Context-Overestimation Layer-1+2, Cross-LLM-Workspace-Permission-Divergenz.

### Pentagon-Verfahren

Abschluss-Ritual jeder Aufgabe: Plan → Spec → Implement → Test → Refine. Pflicht vor Codieren (rules/CLAUDE.md §1 Denkweise).

---

## D. Token-Engpass + LLM-Routing

### Token-Engpass-Hierarchie

Engpass-Hierarchie absteigend (rho-bindend, rules/token-engpass-hierarchie.md):

1. **Martin-Zeit** (Primaer-Engpass, non-substituierbar)
2. **Claude-Opus-4.7-Tokens** (Sekundaer-Engpass, MAX-Plan + Usage-Billing)
3. **Codex GPT-5.4 + Gemini 2.5 Pro + Grok Heavy + Copilot Pro+ + Perplexity Ultimate** (Sunk-Cost-Flat-Abos, ~0 EUR marginal pro Call)

### Sunk-Cost-Flat-LLMs

5 Subscription-LLMs ~€600-1000/Mo flat: Claude Pro/Max + Codex Pro $200/Mo + Copilot Pro+ $39/Mo + Grok SuperGrok Heavy $300/Mo + Gemini Ultra bundle + Perplexity Ultimate $40/Mo. Marginal-Cost pro Call ≈ 0 EUR.

### Hidden-Costs der Flat-LLMs

CONDITIONAL-Erkenntnis 2026-04-29: Flat-LLM-Calls haben Latenz-Cost (30-300s Wall-Clock) + Retry-Cost + Maintenance-Cost + Setup-Cost + Claude-Validierung-Token-Cost. Pragmatische Regel: nutze Flat-LLMs nur wenn erwarteter Nutzen Blockierzeit + Nacharbeitskosten klar uebersteigt.

### Cross-LLM-Mechanik (Mac 2026-04-30)

- Codex via `codex exec --skip-git-repo-check`
- Gemini via `gemini -p "..."`
- Copilot via `copilot -p "..." --allow-all-tools`
- Grok via `mcp__grok-mcp__chat`
- Parallel-Pattern: alle 3 in Bash-Background-Run, ~60-180s, 0 EUR marginal

### Sonnet/Opus-Routing

Default Sonnet fuer Routine, Haiku fuer Trivial-Klassifikation, Opus nur K_0/Q_0/Phronesis/Meta-E4+ (rules/sonnet-opus-routing.md). Im Zweifel: staerkstes Modell.

### Subagent-Pool

3 max gleichzeitig (rules/passivitaets-hemmung.md §Kulminationspunkt-Schutz). Sonnet-Default. Token-Spar-Faktor 10-15x via Sonnet-Pool vs Solo-Architekt-Code-Implementation.

---

## E. HeyLou + 9OS + PMS-Domain

### HeyLou Hotels

7 AI-first Hotels, ~7 FTE pro Haus. Place-Value-Entitaet (mit 9dots GmbH und LexVance). Pilot-Hotel Hildesheim 2026-06-08.

### 9OS

**9-Operating-System.** Hotel-Operating-System mit 4-Kreis-Prozessarchitektur. v3.3 = HeyLou-Stack (Next.js+Go+Apaleo). v1 = legacy RN+Python+Mews. Hot-Switch-Pattern Apaleo↔Mews architektonisch vorbereitet.

### IBE

**Internet Booking Engine.** HeyLou-Component fuer direkte Hotel-Buchungen via OTA-Greenfield. Latenz-Ziel p50<100ms / p99<300ms / TTFB<50ms.

### PMS

**Property Management System.** Mews / Apaleo / Cloudbeds / Shiji. Region-spezifisch: Apaleo EU-stark, Mews US-stark (ABS-Native), Shiji ASIA-Limited.

### ABS-Pricing (Attribute Based Pricing)

AI-driven Pricing auf Zimmer-Attribut-Ebene (vs klassisches Yield-Management auf Kategorien). Yield-Differential +3-18% ADR je nach Tier.

### ABS-Tier (Trinity)

3 Inventarisierungs-Tiere:
- **Smart-Kategorien:** 4-7 Master-Kategorien + 3 Modifier (2-4h pro Hotel, +3-5% ADR)
- **Hybrid-ABS:** Top-5 Attribute (Stockwerk, Aussicht, m², Bett, Balkon, 8-20h pro Hotel, +6-12% ADR)
- **Voll-ABS:** 30-50 Attribute (Mews-ABS-Schema, 60-200h pro Hotel, +10-18% ADR)

### Region-Hybrid (DC-1)

**Architekt-Decided Option C:** EU=Hybrid-ABS (Apaleo + Mews-Shadow), US=Voll-ABS (Mews-Native), ASIA=Smart-Kategorien (Shiji). Yield-Differential +6-12% ADR gemittelt. rho 7 Hotels: +€250-650k/J.

### Mews-Shadow

Mews PMS parallel zu Apaleo Primary, Read-Only fuer ABS-Pricing-Layer. DC-2 Architektur Hot-Switch-Pfad bleibt offen.

### Latenz-Stack (Hybrid)

**Architekt-Decided Option C (DC-3):** Pre-Compute Daily 02:00 (Aurora-Materialized-View, 90 Tage forward) + Edge-Cache Cloudflare Workers (TTL 60s SWR) + Async-AI-Refresh (ECS-Fargate low-priority). p99<200ms, ~€500-1900/Mo 7 Hotels, AI-Outage-resilient.

### TTFB

**Time To First Byte.** Latenz-Metrik fuer First-Paint-Optimum. KMO-Ziel: TTFB<50ms (Cloudflare Edge weltweit).

---

## F. Flat-LLMs + LLM-Anbieter

### Codex

OpenAI/ChatGPT Pro CLI mit gpt-5.x-Modellen. `codex exec` (non-interactive scripting), `codex review` (code review), `codex mcp-server` (MCP-Server in Claude Code). $200/Mo Pro-Abo, 6x Rate-Limits vs Plus.

### Gemini 2.5 Pro

Google Gemini Ultra bundle. CLI via `gemini -p "..."`. OAuth-Auth. Lange Context-Window (1M Tokens), Faktencheck + Citations + Authority-Rolle.

### Copilot Pro+

GitHub Copilot Pro+ $39/Mo. CLI via `copilot -p "..." --allow-all-tools`. 1500 Premium-Requests/Monat inkludiert. GitHub-MCP-Integration. Code-Gen + Refactor + Docs.

### Grok 4 Heavy

xAI SuperGrok Heavy ~$300/Mo. CLI via `mcp__grok-mcp__chat` mit `model=grok-4.20-0309-reasoning`. Anti-Sycophancy verifiziert. X/Twitter-Live-Search exklusiv. Multi-Agent-Reasoning mit 4-16 parallelen Agents.

### Perplexity Ultimate

~$40/Mo. Real-time-Web-Search mit Citations. Authority + Sources fuer Faktencheck.

### Mac-Setup (Cross-LLM 2026-04-30)

- Codex Pro $200/Mo (existing OAuth)
- Gemini-CLI OAuth (existing)
- Copilot Pro+ $39/Mo (existing)
- Grok Heavy MCP (Cooldown-Status pruefen, ggf. nicht aktiv)
- Total Sunk-Cost: ~€600-1000/Mo

---

## G. SAE-v8 Bezuege

### SAE v7.5 / v8

**Symbiotic Agentic Ecosystem.** 9dots-Architektur mit 600 Agenten (200 Slots × Trinity-Pattern), 10 AgentClasses, klassenspezifische Strategien. Pontryagin/Hamilton-Optimierung H = u + lambda*f. Myzel-Layer (MYZ-01..28, 7 Schichten). 5-Level Curriculum + PKB. Room Identity Layer. HIVE (Shannon-Team-Score) + COSMOS (Compliance-Oversight-Safeguard-Monitoring-Sovereignty). MHC.

### Trinity-Slot

200 Slots × 3 Varianten (Conservative/Aggressive/Contrarian) = 600 Agenten. Best-of-3 wins via `core/trinity.py`.

### Myzel-Layer

7-Schicht-Event-Bus + Inter-Agent-Kommunikation. MYZ-30 Event-Router + MYZ-32 Dispatcher. KMO A3 Outbox-Pattern isomorph.

### COSMOS

**Compliance-Oversight-Safeguard-Monitoring-Sovereignty.** SAE-Governance-Layer. Bounded-Veto + 5 Harte Grenzen. KMO kmo_governance/ Layer ist KMO-COSMOS.

### HIVE-Score

Shannon-basierter Team-Score in SAE. KPM (Kemmer-Portfolio-Management) Variante-D Governance-Gate fuer Leverage-Erhoehung.

### F_CUM_DECAY

`F_CUM_DECAY = 0.98` in SAE: Fitness-Verfall pro Zyklus, HWZ ~34 Tage. Familien-Ewigkeits-Horizont. Nicht 0.70 wie alter Trading-Wert.

### T_CAP

`T_CAP = 50000 Tokens` harte Obergrenze pro Agent in SAE. Effektive Untergrenze T_RECOVERY_FLOOR / (1+W_CAP) = 5000 Tokens.

### Q_SCALE

`Q_SCALE_INTEGRAL = 11.11 = Q_SCALE_EMA / GAMMA = 0.5 / 0.045`. Nicht 25.0 (Bug, Gamma found, Beta fixed, 6 Wargames validated).

---

## H. Tools + Methoden

### Cross-LLM-Pflicht-E3-Plus

Aus rules/cross-llm-pflicht-e3-plus.md: Keine E3-, E4- oder E5-Aussage canonisch ohne Cross-LLM-Audit mit min. 2 externen LLM-Modellen + dokumentierter Konsens-Analyse + Verdict-Tier gemaess FIXPUNKT-1.

### Wargame-First-Pflicht

Aus rules/wargame-first-pflicht.md: Vor Implementation eines E3+-relevanten Items (Skill/Rule/DF/Architektur/Pipeline-Aenderung) PFLICHT-Cross-LLM-Wargame.

### Pre-Action-Verification-Pflicht

Aus CLAUDE.md §0 + rules/df-akzeptanz-kriterien.md K13: Bei jeder Action auf shared/external Resources (Filesystem, DBs, Cloud-APIs, Drive-Sync, Backup-Storage, GitHub) MUSS VOR Ausfuehrung verifiziert werden: env_tag (dev/staging/prod), Mount-Point, Backup-Status, blast_radius + Reversibilitaets-Klasse. Pre-Action-Check-Failure = HARD-STOP.

### DF (Dark-Factory)

Level-5-Autonomie fuer Repetition>=10/Monat + Narrow Scope + Determinismus + Rollback + 90% Test-Coverage + K_0 geschuetzt + Q_0 messbar + Escalation-Trigger + rho-Budget + Audit-Trail. Aus rules/when-to-archon.md.

### Skill

Wiederverwendbarer Workflow in `~/.claude/skills/<name>/SKILL.md`. Triggers + Capability + Anti-Patterns dokumentiert. KMO orchestriert 72 Skills via Capability-Matrix.

### LaunchAgent

macOS launchd-Service fuer persistente Background-Tasks. KMO-Multi-Machine via 28 LaunchAgents (Mac) + Scheduled-Tasks (Windows). DF-06/10/12-v2/15/43-86 etc.

### Capability-Matrix

YAML-Config Task-Type → Tool-Mapping fuer KMO-Routing. Static-Default + Haiku-Classifier-Override fuer Edge-Cases (Trinity-Option C Hybrid).

---

## I. Status-Markers + Lifecycle

### PRE-1 bis PRE-5

5 Pre-Production-Bedingungen aus Welle-3-Re-Re-Wargame:

- **PRE-1** A6 Code-Implementation Repository-Restructuring (COMPLETE)
- **PRE-2** A4.2 Dual-Control + Atomic Pre-Deploy-Pipeline (COMPLETE)
- **PRE-3** End-to-End-Test mit allen Patches (RATE-LIMITED-RETRY)
- **PRE-4** Shared-path-Test auf echtem Drive-Sync (pending)
- **PRE-5** Concurrency 100-Threads-Stress-Test (pending)

### Welle-1 / Welle-2 / Welle-3 / Welle-4

KMO-Build-Wellen sequenziell:

- **Welle-1:** A4 + A1 + A5 (1842 LoC + 68/68 Tests)
- **Welle-2:** A2 + A3 (1452 LoC + 15/15 Tests)
- **Welle-3:** A7 + A6-Spec (1082 LoC + 18/18 Tests)
- **Welle-4 PRE-Production:** A4.2 Dual-Control (+552 LoC + 25/25 Tests) + A6 Repo-Restructuring + E2E-Test (Rate-Limited)

### SUPERSEDED

Disziplin: alte Findings nicht loeschen, Zeile-1-Header `# SUPERSEDED — Lies stattdessen: <pfad> [CRUX-MK]` einfuegen. Aus rules/kb-hygiene.md.

### CONDITIONAL / PROVISIONAL / HARDENED-Tier-Migration

Lifecycle-Pfad fuer Claims: REJECTED < CONDITIONAL < PROVISIONAL < CROSS-LLM-SIM-HARDENED < CROSS-LLM-2OF3-HARDENED < HARDENED < HARDENED-PRODUCTION < FIXPUNKT-HARDENED.

---

## Cross-Reference

- **Master-Spec:** `branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md`
- **Master-Index:** [00-INDEX.md](00-INDEX.md)
- **Decisions:** [07-DECISIONS.md](07-DECISIONS.md)
- **Wargames:** [08-WARGAMES.md](08-WARGAMES.md)
- **CRUX + rho:** [09-CRUX-RHO.md](09-CRUX-RHO.md)
- **CLAUDE.md:** `~/.claude/CLAUDE.md` (Verfassung)
- **rules/:** `~/.claude/rules/` (35+ aktive Rules)

[CRUX-MK]
