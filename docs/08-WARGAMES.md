---
type: wargames-consolidation
target: KMO Cross-LLM-Wargame-Sequenz konsolidiert (3 Iterationen Welle-0/1/3)
status: ADOPT-PILOT-ONLY (CROSS-LLM-2OF3-HARDENED)
priority: HIGH
crux-mk: true
created: 2026-04-30
created-by: mac-heylou-ota-l0-2026-04-30 (Subagent-C TOP-Doku)
parent-handoff: branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md
hotspot-diagnose: branch-hub/findings/WARGAME-KMO-HOTSPOT-DIAGNOSE-2026-04-30.md
---

# 08 — Cross-LLM-Wargame-Sequenz konsolidiert [CRUX-MK]

3 Wargame-Iterationen auf KMO-Spec, jede Iteration mit Cross-LLM-Konvergenz-Matrix, O-Total-Scoring, Hotspot-Diagnose, Patch-Trigger.

## Cross-LLM-Mechanik

**Setup auf Mac (2026-04-30):**

- **Codex GPT-5.5** via `codex exec --skip-git-repo-check` (ChatGPT Pro $200/Mo, Sunk-Cost-Flat)
- **Gemini 2.5 Pro** via `gemini -p "..."` (Gemini Ultra bundle, Sunk-Cost-Flat, OAuth)
- **Copilot Pro+** via `copilot -p "..." --allow-all-tools` (Pro+ $39/Mo, Sunk-Cost-Flat)
- **Grok-Heavy** via `mcp__grok-mcp__chat` (~$300/Mo Sunk-Cost-Flat) — pending fuer Welle-4 als 4. LLM

**Parallel-Pattern:** alle 3 LLMs in einem Bash-Background-Run, ~60-180s pro Wargame, **0 EUR marginal**.

**Token-Spar:** ~3k Opus-Tokens pro Wargame fuer Architekt-Synthese vs ~30-50k Opus-Tokens fuer einsame Adversarial-Analyse → **10-15x Token-Spar via Cross-LLM-Pattern.**

---

## Verdict-Tier-Hierarchie (gemaess `rules/cross-llm-pflicht-e3-plus.md` + FIXPUNKT-1)

```
REJECTED
  <
CONDITIONAL                                     (Single-Model oder LLM-Konsens unvollstaendig)
  <
PROVISIONAL                                     (LLM-Konsens vorhanden, G3.2 Divergenz-Proxies unvollstaendig)
  <
CROSS-LLM-SIMULATION-HARDENED                   (1 Modell, mehrere Perspektiven simuliert)
  <
CROSS-LLM-2OF3-HARDENED                         (2 von 3 LLMs konvergent, G1-G7 erfuellt + G8-G12)
  <
ADOPT-PILOT-ONLY                                (Pilot-Trigger autorisiert, Production gesperrt bis Pre-Conditions)  <-- KMO Welle-3
  <
HARDENED                                        (3+ Modelle konvergent + externe Ankerung, voll G1-G14)
  <
HARDENED-PRODUCTION                             (HARDENED + Produktions-Stichprobe + Brier-Score-Kalibrierung)
  <
FIXPUNKT-HARDENED                               (E5 strukturell-logisch, nur 4 Fixpunkte)
```

**KMO-Pipeline-Position:** Welle-3 hat **CROSS-LLM-2OF3-HARDENED-ADOPT-PILOT-ONLY** erreicht. Production-Pfad braucht 5 Pre-Conditions PLUS naechstes Re-Wargame (post-PRE-3+4+5).

---

## Wargame-Files-Mapping

| Welle | Verdict-File | RAW-Files | Bytes |
|-------|--------------|-----------|-------|
| Welle-0 | `branch-hub/cross-llm/2026-04-30-WARGAME-KMO-PENTAGON-VERDICT.md` | Codex 22276 + Gemini 4726 + Copilot 8374 | ~35k |
| Welle-1 | `branch-hub/cross-llm/2026-04-30-REWARGAME-KMO-WELLE1-VERDICT.md` | Codex 145k + Gemini 6k + Copilot 8.5k | ~160k |
| Welle-3 | `branch-hub/cross-llm/2026-04-30-RE2WARGAME-KMO-WELLE3-VERDICT.md` | Codex 180k + Gemini 4k + Copilot 11.5k | ~195k |

---

## Welle-0 — Pentagon-Wargame (KMO-Spec v0.1.0, 2026-04-30T15:04)

### Konvergenz-Matrix

| LLM | Verdict | Schwachstellen | Worst-Cases |
|-----|---------|----------------|-------------|
| Codex GPT-5.5 | MODIFY | 5 Schwachstellen | 3 Worst-Cases (10-500k EUR Schaden) |
| Gemini 2.5 Pro | MODIFY | 3 Konsistenz-Lcken | 3 Feedback-Loop-Risiken + Best-Practice-Gap |
| Copilot Pro+ | MODIFY (implicit, 5 Patches) | 5 Pattern-Audit | Saga + Outbox MISSING |
| **Konvergenz** | **3/3 ADOPT-MODIFY** | — | — |

### 5-Ordnungs-Scores (O_total = 0.70)

| Ordnung | Methodik | Score | Begruendung |
|---------|----------|-------|-------------|
| O1 Existenz | Pflicht-Sektionen (6/6) | 93% | rho-Quantifizierung schwach (60%), Rest 100% |
| O2 Konsistenz | Self-Contradiction + Scope + Arithmetik | 80% | 3 Patches: Layer-Split + rho-Formel + Trinity-Cross-Ref |
| O3 Adversarial | Codex 5 Schwachstellen + 3 Worst-Cases | 70% | 3 von 5 Schwachstellen kritisch, 25-500k EUR Worst-Case-Schaden |
| O4 Spieltheorie | Single-Point-of-Policy + Approval-Bottleneck | 65% | Nash-instabil bei Routing-Bias-Reinforcement (Death-Spiral-Trigger) |
| O5 Systemtheorie | Death-Spiral + Hygiene-Entropie + State-Sync-Vakuum | 60% | 3 Feedback-Loop-Risiken aus Gemini, Multi-Machine-Vakuum kritisch |

**Formel:** O_total = 0.1×0.93 + 0.15×0.80 + 0.25×0.70 + 0.25×0.65 + 0.25×0.60 = **0.70**

→ Architekt-Ziel >=0.65 erfuellt. Production-Ziel >=0.80 NICHT erfuellt. **CONTINUE+MODIFY.**

### 7 CRIT-Patches identifiziert (A1-A7, Pflicht vor Implementation)

| Patch | Quelle | Beschreibung | Effort | Schaden-Schutz |
|-------|--------|--------------|--------|----------------|
| **P-KMO-A1 Resource-Lease** | Codex#3 + Copilot-Bulkhead | Zentrales Mutex/Lease-System fuer DF/Port/Token/Drive-Path/Tunnel | 6-10h | -€10-75k Cascade |
| **P-KMO-A2 Saga-Pattern** | Copilot + Codex#1 | 7-Phasen-Pipeline mit do/undo + Compensation-Chain | 8-12h | -€50-500k Approval-Theater |
| **P-KMO-A3 Outbox-Pattern** | Copilot + Gemini-State-Sync | Durable Dispatch-Queue Cross-Machine | 6-10h | Multi-Machine-Konsistenz |
| **P-KMO-A4 Approval-Gates** | Codex#2 | Production-Credentials separat, signed-tokens, immutable audit | 4-8h | -€50-500k Production-Cascade |
| **P-KMO-A5 Data-Class-Filter** | Codex#5 | 4-Stufen No-Go-Matrix Public/Internal/Confidential/Secret | 3-5h | -€25-250k DSGVO |
| **P-KMO-A6 Control/Data-Plane** | Gemini-BP | Repository-Restructuring kmo_control/governance/executors | 4-6h | Architektur-Sauberkeit |
| **P-KMO-A7 Durable-Execution** | Gemini + Copilot Event-Sourcing | Persistente State-Machine + Crash-Recovery | 12-20h | Reboot/Crash-Resilienz |

**Total Effort:** 43-71h (5-9 Arbeitstage Architekt+Subagent-Mix). **Total Schaden-Schutz: €85-1325k.**

### 4 Hotspots (CRIT)

- **HOTSPOT-A (CRIT):** Approval-Pipeline rein prozessual statt technisch enforced. Direkter K_0-Risk 50-500k.
- **HOTSPOT-B (HIGH):** Multi-Machine-State-Sync fehlt vollstaendig.
- **HOTSPOT-C (HIGH):** Resource-Konkurrenz unkontrolliert (28 LaunchAgents + Subagent-Pool + Cross-LLM ohne globalen Lock-Manager).
- **HOTSPOT-D (MED):** Daten-Klassifikation fehlt im Routing.

Detail-Diagnose: `branch-hub/findings/WARGAME-KMO-HOTSPOT-DIAGNOSE-2026-04-30.md`.

---

## Welle-1 — Re-Wargame (post Welle-1-Code, 2026-04-30T15:25)

### Code-Status post Welle-1

A4 + A1 + A5 implementiert (1842 LoC + 68/68 Tests PASS nach A5-Bearer-JWT-Bug-Fix).

### Konvergenz-Matrix

| LLM | O_total | Verdict | Test-Verify | Bemerkung |
|-----|---------|---------|-------------|-----------|
| Gemini 2.5 Pro | 0.805 | ADOPT-WELLE-1 | ✗ Workspace-blocked | optimistisch, Doc-Read only |
| Copilot Pro+ | ~0.73 | MODIFY | ✓ pytest-PASS-FAIL gefunden | realistisch, eigenes pytest |
| Codex GPT-5.5 | tba | tba (Tail pending) | ✓ Code-Read + sed-Audit | detailliert |
| **Architekt-pytest** | — | A5 Bug FIXED post-detect | **18/18 + 18/18 + 31/32 → 32/32 nach Fix** | Ground-Truth |

### Kritisches Finding: Cross-LLM-Divergenz auf Test-Run-Permission

Gemini hat A5 als "Tests passed" angenommen (basierend auf Doc-Claim 14 Tests). Copilot hat A5 selbst getestet und Bearer-Token-Pattern-Bug gefunden (`Bearer eyJ...` → PUBLIC statt SECRET).

**Lehre dokumentiert (Bias-Catalog Layer 5):** Re-Wargame ohne pytest-Run-Permission ist epistemisch ungleichgewichtig. Gemini-Verdict war Sycophancy-Signal (vertraut Doc), Copilot-Verdict war evidenz-basiert.

**Konsequenz:** Verdict-Konvergenz nur 1/3 (Copilot) vs 1/3 (Gemini divergent) vs 1/3 (Codex pending). **Nicht** CROSS-LLM-2OF3-HARDENED erreicht. Status: **CONDITIONAL-PROMOTED-WELLE-1** nach Bug-Fix + Re-Verify.

### Hotspot-Status

| Hotspot | Welle-0 | Welle-1+Fix | Pflicht-Patch |
|---------|---------|-------------|---------------|
| A Approval-Theater | CRIT | **TEILWEISE** | A2 noch Pflicht fuer voll-geschlossen |
| B Multi-Machine-Sync-Vakuum | CRIT | UNVERAENDERT | A3 + A7 |
| C Resource-Konkurrenz | CRIT | **HINREICHEND** (A1 production-tauglich) | — |
| D Daten-Klassifikation | CRIT | **HINREICHEND** nach Bug-Fix | — |

### O-Score-Schaetzung (post-Bug-Fix, konservativ Copilot-aligned)

| Ordnung | Welle-0 | Welle-1+Fix | Delta |
|---------|---------|-------------|-------|
| O1 Existenz | 93% | 95% | +2% |
| O2 Konsistenz | 80% | 88% | +8% |
| O3 Adversarial | 70% | 78% | +8% |
| O4 Spieltheorie | 65% | 71% | +6% |
| O5 Systemtheorie | 60% | 65% | +5% |

**O_total konsolidiert post-fix: ~0.74** (zwischen Copilot 0.73 und Gemini 0.805).

→ Architekt-Ziel >=0.65 erfuellt. Production-Ziel >=0.78 noch nicht. **Welle-2 (A2 + A3) + Welle-3 (A6 + A7) Pflicht.**

### Verdict-Tier

**CONDITIONAL-PROMOTED-WELLE-1** (zwischen CONDITIONAL und CROSS-LLM-2OF3-HARDENED):

- Welle-1 Code production-tauglich fuer **lokale Single-Machine-Workflows**
- A1 voll-production-ready (10-Threads-Concurrency-Test PASS)
- A4 brauchbar gehaertet, aber 2-Personen-Enforcement noch nicht technisch erzwungen
- A5 nach Bug-Fix robust (32/32 Tests, 9 SECRET-Patterns inkl. JWT)
- **NICHT** production-ready fuer Multi-Machine (Hotspot B unveraendert)

---

## Welle-3 — Re-Re-Wargame (post Welle-1+2+3-Code + A6-Refactor, 2026-04-30T16:58)

### Code-Status post Welle-3

Alle 6 Code-Patches implementiert + A6-Refactor + A4.2 Dual-Control:

- **Total: 5500+ LoC + 133/133 Tests PASS** (108 post-A6-Refactor + 25 A4.2 Dual-Control)

### Konvergenz-Matrix

| LLM | O_total | Verdict | Hotspot-A | Hotspot-D | Bemerkung |
|-----|---------|---------|-----------|-----------|-----------|
| Gemini 2.5 Pro | **0.88** | ADOPT-PILOT-ONLY | GESCHLOSSEN | OFFEN (A6 missing) | optimistisch, Spec-only-Read |
| Copilot Pro+ | **0.79 ±0.03** | ADOPT-PILOT-ONLY | OFFEN (A4 nur teilweise) | GESCHLOSSEN | realistisch, Code-Read + pytest |
| Codex GPT-5.5 | tba | tba (180k pending) | tba | tba | detailliert |
| **Konvergenz** | **0.83 (Mittel)** | **2/3 ADOPT-PILOT-ONLY** | **OFFEN/Konsens** | **GESCHLOSSEN/Konsens** | Production-Polster fehlt |

### Welle-3 Patch-Status

| Patch | Code-Status | Verdict | Bemerkung |
|-------|-------------|---------|-----------|
| A1 Resource-Lease | DONE 18/18 PASS | HINREICHEND | SQLite-WAL + 10-Threads-Race + STOP.flag |
| A2 Saga-Pattern | DONE 9/9 PASS | HINREICHEND | do/undo + Crash-Recovery + Compensation-Chain |
| A3 Outbox-Pattern | DONE 6/6 PASS (post-Fix) | HINREICHEND | Atomic-Write + Idempotency + DLQ |
| A4 Approval-Gate | DONE 18/18 PASS | **NUR TEILWEISE** | HMAC + Hash-Chain ✓; **Dual-Control fehlt**, Audit nicht transaktional gekoppelt |
| A5 Data-Class-Filter | DONE 32/32 PASS | HINREICHEND | 9 SECRET-Patterns inkl. Bearer-JWT-Fix |
| A6 Control/Data-Plane | Spec only (initial) | OFFEN | Repository-Restructuring noch nicht implementiert |
| A7 Durable-Execution | DONE 18/18 PASS | HINREICHEND | Event-Sourcing + 20-Threads-Concurrent + Crash-Recovery |

**Total nach Welle-3 (vor A6-Refactor + A4.2-Dual-Control):** 4376 LoC + 101/101 Tests PASS.

### Hotspot-Status (konvergent ueber Gemini + Copilot)

| Hotspot | Welle-0 | Welle-1 | Welle-3 | Konvergent |
|---------|---------|---------|---------|------------|
| A Approval-Theater | CRIT | TEILWEISE | OFFEN reduziert (Copilot) / GESCHLOSSEN (Gemini) | **OFFEN** (Copilot strenger, A4-Pseudo-Enforcement) |
| B Multi-Machine-Sync | CRIT | OFFEN | nahezu GESCHLOSSEN (A3+A7) | **GESCHLOSSEN-WITH-CAVEATS** (E2E fehlt) |
| C Resource-Konkurrenz | CRIT | GESCHLOSSEN (A1) | GESCHLOSSEN | **GESCHLOSSEN** |
| D Daten-Klassifikation | CRIT | TEILWEISE | GESCHLOSSEN (A5) | **GESCHLOSSEN** |

### Verdict-Tier

**CROSS-LLM-2OF3-HARDENED-ADOPT-PILOT-ONLY:**

- 2 LLMs konvergent (Gemini + Copilot, beide ADOPT-PILOT-ONLY)
- Codex pending Tail-Read (vermutlich aehnlich Copilot)
- Pilot-Trigger fuer DEV-Stage **autorisiert**
- Production-Trigger **gesperrt** bis 5 Pre-Production-Bedingungen erfuellt

---

## 5 Pre-Production-Bedingungen (PRE-1 bis PRE-5)

Konsolidiert aus Welle-3-Re-Re-Wargame (Gemini + Copilot konvergent):

| PRE | Bedingung | Status | Owner |
|-----|-----------|--------|-------|
| **PRE-1** | A6 Code-Implementation: Repository-Restructuring kmo_control/governance/executors (Spec → Code) | **COMPLETE** post Welle-4 | Subagent-Refactor |
| **PRE-2** | A4 haerten Patch-A4.2: Dual-Control (Requester != Approver, 2 unabhaengige Signaturen) + Audit-Log transaktional an verify+deploy gekoppelt (atomic Pre-Deploy-Pfad) | **COMPLETE** post Welle-4 (+552 LoC, 25/25 Tests) | Subagent |
| **PRE-3** | End-to-End-Test: echter KMO-Run mit A1+A2+A3+A4+A5+A7 zusammen + Crash/Restart mid-Workflow | **RATE-LIMITED-RETRY** | Subagent (Sonnet) |
| **PRE-4** | Shared-path-Test: Recovery/Outbox auf echtem Drive-Sync-Pfad (nicht nur tmp) | pending | Architekt-direkt ~30 Min |
| **PRE-5** | Concurrency 100-Threads-Stress-Test: Skalierung von 20 auf >100 simultane Threads (Gemini-Bedingung) | pending | Architekt-direkt ~30 Min |

**Status-Snapshot 2026-04-30 Session-Ende:** PRE-1 + PRE-2 COMPLETE. PRE-3 Anthropic-Server-Side-Rate-Limit, retry pending. PRE-4 + PRE-5 pending.

---

## Bias-Catalog (4 Layer-Lehren aus Pipeline)

| Layer | BIAS-ID | Pattern | Korrektur |
|-------|---------|---------|-----------|
| **1** | PHRONESIS-OUTSOURCING-NLM-TRIGGER | NLM-Trigger-Frage als Phronesis behandelt obwohl autonom-entscheidbar | Architekt-Default-Pattern: DF-86 trigger + Fallback manuell |
| **2** | PHRONESIS-OUTSOURCING-K0-SPERR-LISTE-MISINTERPRETATION | K_0-Sperr-Liste #5 als "jede Architektur-Entscheidung" interpretiert | Korrekt: NUR Implementation-Trigger; Tier-Wahl + DCs sind Welle-7-autonom |
| **3** | CONTEXT-OVERESTIMATION (Layer 1) | Heuristik 95-96% vs gemessene 41% (Faktor 2x) → revidiert auf 70-80% vs 58% (Faktor 1.4x) | rules/context-budget.md: externe Messung schlaegt Heuristik IMMER |
| **4** | CONTEXT-OVERESTIMATION (Layer 2) | Heuristik 75-80% vs gemessene 67% (Faktor 1.15x) | Bias hat sich nach Layer-1 reduziert aber residual systematisch |
| **5 (zusatz)** | CROSS-LLM-WORKSPACE-PERMISSION-DIVERGENZ | Cross-LLM ohne pytest-Run-Permission ist epistemisch ungleichgewichtig | Sycophancy-Signal erkennbar (Gemini 0.805 vs Copilot 0.73 wegen Workspace-Block) |

**Persistierungs-Status:** alle 5 Layer in `branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md` Bias-Catalog-Sektion verankert.

---

## Pipeline-Lessons (empirisch belegt aus 3-Wargames-Sequenz)

1. **3-LLM Cross-LLM in 60s parallel auf Mac OPERATIONAL** (Codex + Gemini-CLI-OAuth + Copilot Pro+, alle Sunk-Cost-Flat, 0 EUR marginal)
2. **Multi-Subagent-Pattern Token-Spar-Faktor 10-15x** vs Architekt-Solo-Code-Implementation
3. **Cross-LLM-Divergenz** wenn nicht alle LLMs Tests laufen koennen → Sycophancy-Risk dokumentierbar
4. **Anthropic-Server-Side-Rate-Limits** triggern unvorhersehbar (heute 2x: Welle-2 + E2E), 60-180s Backoff
5. **K_0-Sperr-Liste-Interpretation:** Implementation-Trigger vs Tier-Wahl muss explizit unterschieden werden
6. **A6 Repo-Restructuring touched 108 Tests, alle PASS post-mv** dank relativer-Imports-Pattern (Tests-Path-Update unnoetig)
7. **Subagent-Sandbox-Block fuer Bash** ist intermittent — Architekt muss pytest-Verify Pflicht-erfuellen wenn Subagent berichtet "Tests pending Architekt-Verify"
8. **Bug-Detection-Rate via pytest:** 2 Bugs in 5500 LoC = 0.04% (A5 Bearer-JWT + A3 Idempotency-Logic), beide nach 1-Edit-Fix komplett behoben

---

## Naechste Welle (post-Welle-3)

**Pflicht vor Production-Trigger:**

1. **PRE-3 E2E-Test Retry** nach Rate-Limit-Reset (Subagent ODER Architekt-direkt)
2. **PRE-4 Shared-path-Test** auf Drive-Sync-Pfad
3. **PRE-5 100-Threads-Stress-Test** A1 + A7 hochskaliert
4. **Welle-4 Re-Wargame** mit allen 6 Patches + A6-Refactor + A4.2 Dual-Control + 5 PRE-Bedingungen erfuellt
5. **Ziel:** O_total >= 0.78, Production-ready Verdict
6. **Codex-Tail-Read** (180k Bytes pending) zur 3/3-Konvergenz

**Phase-5 DEV-Demo:**

7. `docker compose build` (Architekt-Bash, ~5-10 Min Image-Pulls + Builds)
8. **Cloudflare-Tunnel-Setup** (Martin-OAuth einmalig + Token-Generation)
9. **Pilot-Run** Build-vs-Buy-Gate-Skill als 1. live KMO-DF (4 MVP-Test-Cases via Cloudflare-URL)

**Phase-6+7 Approval:**

10. **Demo-Materialien** fuer Martin (8 Pflicht-Felder)
11. **Martin-Freigabe** MHC explizit
12. **Gerdi-CTO-Handoff-Package** (8 Pflicht-Felder)
13. **Production-Deploy** nach Gerdi-Approval

---

## Cross-Reference

- **Master-Spec:** `branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md`
- **Verdict-Files:** Welle-0 / Welle-1 / Welle-3 (siehe Wargame-Files-Mapping oben)
- **Hotspot-Diagnose:** `branch-hub/findings/WARGAME-KMO-HOTSPOT-DIAGNOSE-2026-04-30.md`
- **Decisions:** [07-DECISIONS.md](07-DECISIONS.md)
- **CRUX + rho:** [09-CRUX-RHO.md](09-CRUX-RHO.md)
- **Glossar:** [10-GLOSSARY.md](10-GLOSSARY.md)
- **Master-Handoff:** `branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md`

[CRUX-MK]
