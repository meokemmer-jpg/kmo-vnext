---
type: decisions-consolidation
target: KMO Decisions konsolidiert (3 ARCHITEKT-DECIDED-DCs + Pending-Phronesis + K_0-Sperr-Mapping)
status: active (Welle-7-LIVE)
priority: HIGH
crux-mk: true
created: 2026-04-30
created-by: mac-heylou-ota-l0-2026-04-30 (Subagent-C TOP-Doku)
parent-handoff: branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md
master-spec: branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md
---

# 07 — Decisions konsolidiert [CRUX-MK]

Alle Architecture-Decisions die in der KMO-Build-Pipeline 2026-04-30 getroffen wurden, mit Trinity-Optionen, Wahl, Begruendung, MHC-Override-Pfad und Falsifikations-Bedingung.

## Decision-Audit-Trail

| Wer | Wann | Was | Wo dokumentiert |
|-----|------|-----|-----------------|
| Architekt (Mac-Opus) | 2026-04-30 14:10 | DC-HEYLOU-ABS-TIER (Region-Hybrid) | `Claude-Vault/docs/decision-cards/DC-HEYLOU-ABS-TIER-2026-04-30.md` |
| Architekt (Mac-Opus) | 2026-04-30 14:10 | DC-9OS-STACK-COMPROMISE (HeyLou-v3.3 + Mews-Shadow) | `Claude-Vault/docs/decision-cards/DC-9OS-STACK-COMPROMISE-2026-04-30.md` |
| Architekt (Mac-Opus) | 2026-04-30 ~14:30 | SPEC-LATENZ-STACK (Hybrid Pre-Compute + Edge-Cache + Async-AI) | `branch-hub/blueprints/SPEC-LATENZ-ENGINEERING-STACK-2026-04-30.md` |
| Architekt (Mac-Opus) | 2026-04-30 ~15:04 | KMO Spec v0.1.0 (Vor Welle-0 Wargame) | `branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md` |
| Architekt (Mac-Opus) | 2026-04-30 ~15:25 | KMO Spec v0.2.0 (post Welle-1, A4+A1+A5 implementiert) | gleiche Spec, wargame-welle1 Frontmatter-Update |
| Architekt (Mac-Opus) | 2026-04-30 ~16:58 | KMO Spec v0.3.0 (post Welle-3, ADOPT-PILOT-ONLY) | gleiche Spec, wargame-welle3 Frontmatter-Update |

---

## DC-1: HeyLou ABS-Tier (ARCHITEKT-DECIDED — Region-Hybrid)

### Trigger

HeyLou-OTA-Greenfield erfordert Pricing-Engine. Aktuell Duetto-RMS (klassisches Yield-Management auf Kategorien). AI-driven Attribute Based Pricing kann Yield steigern (+3-18% ADR), benoetigt aber Zimmer-Attribut-Inventarisierung. **Drei Tier-Optionen** mit unterschiedlichem Aufwand-Yield-Risiko-Profil.

### Trinity-Optionen

| Option | Pattern | Yield-Differential | rho 7 Hotels | Aufwand | Risiko |
|--------|---------|--------------------|---------------|---------|--------|
| **A — Conservative: Smart-Kategorien** | 4-7 Master-Kategorien + 3 Modifier | +3-5% ADR | +€80-200k/J | 2-4h pro Hotel | klein (rollback in 1h) |
| **B — Aggressive: Voll-ABS Mews-Native** | 30-50 Attribute pro Zimmer | +10-18% ADR | +€350-900k/J | 60-200h pro Hotel | **gross** (Mews-Vendor-Lock-in, blockiert 3-Region) |
| **C — Contrarian: Region-Hybrid (gewahlt)** | EU=Hybrid (Apaleo + Mews-Shadow), US=Voll-ABS (Mews), ASIA=Smart (Shiji) | +6-12% ADR gemittelt | **+€250-650k/J** | 8-200h pro Hotel je Region | **mittel** (Region-isoliertes Rollback) |

### Wahl: Option C — Region-Hybrid

### Begruendung (Layer 1-5)

1. **Direkt:** Region-Hybrid matched zu existierender 3-Region-Architektur (Parent-Session-Welle 5)
2. **Begruendung:** Region-spezifische PMS-Faehigkeiten optimal genutzt — kein Kompromiss zwischen Mews-ABS-Native (US-Stark), Apaleo-API-First (EU-Stark) und Shiji-Limited (ASIA-Realitaet)
3. **Strukturursache:** Yield-Differential ist **concave** in Inventarisierungs-Aufwand. Sweet spot ist Hybrid-Tier — sub-linearer Yield-Gain bei Voll-ABS rechtfertigt nicht 5-10x Aufwand-Mehrkosten + Lock-in-Risiko
4. **Folgerungen:** ABS-Adapter-Layer wird Cross-Region-Abstraktion (analog 9-Adapter-Konsolidierung). Pilot Hildesheim startet mit EU-Hybrid-ABS (Apaleo + Mews-Shadow). Skalierung pro Region
5. **CRUX-Verbindung:** K_0 geschuetzt durch Region-isolierten Rollback. Q_0 erhoeht durch graduelles Lernen. W_0 optimiert (Mac/Architekt-Bandbreite)

### Voraussetzungen

1. Parent-DC (9OS-Stack-Konflikt) entschieden — siehe DC-2
2. W-ABS-Pentagon-Wargame durchgefuehrt — Cross-LLM-2OF3-HARDENED auf Windows-Vault
3. Latenz-Engineering-Stack-Spec freigegeben — siehe SPEC-LATENZ-STACK
4. Pilot-Hotel ausgewaehlt — Hildesheim Default

### MHC-Override-Pfad

Edit `Claude-Vault/docs/decision-cards/DC-HEYLOU-ABS-TIER-2026-04-30.md` → `status: REJECTED` + Begruendung. Architekt rollt zurueck (1h Aufwand).

### Falsifikations-Bedingung

Pilot-Hotel-A/B-Test (90 Tage) Yield-Differential < 4% ADR (vs predicted +6-12% Hybrid):
- Sofort: Tier-Downgrade auf Smart-Kategorien (Option A)
- Untersuchung: Branchendaten-Validitaet, Mess-Methodik, Confounding-Faktoren

---

## DC-2: 9OS-Stack-Compromise (ARCHITEKT-DECIDED — HeyLou-v3.3 + Mews-Shadow)

### Trigger

Aus Parent-Session PMS-9OS-Architektur identifiziert: **9OS-v1 (RN+Python+MEWS) und HeyLou-v3.3 (Next.js+Go+Apaleo) beanspruchen beide Hildesheim 2026-06-08 als Pilot-Hotel.** Plus 9 P0-Bugs mit DSGVO-Violations. K_0-Risk: Pilot-Hotel-Investment 450-710k EUR + 30-55k EUR Worst-Case + 9 DSGVO-Bugs = aktiver Compliance-Risk. Engpass-Primat: Solange Stack nicht klar, ist jede ABS/Latenz-Arbeit vorgezogene Optimierung.

### Trinity-Optionen

| Option | Pattern | Pro | Kontra | Risiko |
|--------|---------|-----|--------|--------|
| **A — Conservative: 9OS-v1 (RN+Python+MEWS) gewinnt** | Python-Tooling, Mews-ABS-Native | Mews-Lock-in akzeptiert, klare Pricing-Engine | RN+Python veraltet vs Next.js+Go, blockiert 3-Region | mittel |
| **B — Aggressive: HeyLou-v3.3 (Next.js+Go+Apaleo) gewinnt** | Modern Stack, EU-stark | zukunftsfaehig | verlieren Mews-ABS-Native, US/Asia brauchen anderen Stack | hoch |
| **C — Contrarian: HeyLou-v3.3 + Mews-Shadow (gewahlt)** | HeyLou primary, Mews shadow read-only | matched zu 3-Region, parallel PMS-Vendor-Staerken | 1.5-2x Ops-Aufwand | mittel (Shadow-Mode rueckabwickelbar) |

### Wahl: Option C — HeyLou-v3.3 + Mews-Shadow-Compromise

### Begruendung (Layer 1-5)

1. **Direkt:** HeyLou-v3.3 als Primary, Mews als Shadow
2. **Begruendung:** Matched zu 3-Region-Architektur (Apaleo EU-Stark, Mews US-Stark) statt Single-Vendor-Lock-in
3. **Strukturursache:** Hot-Switch-Pattern aus Hot-Switch-Wargame (Apaleo↔Mews) ist bereits architektonisch vorbereitet — Stack-Compromise nutzt diese Faehigkeit, statt sie zu verschenken
4. **Folgerungen:** P0-Bug-Sprint kann SOFORT starten (DSGVO-Violations Pflicht), unabhaengig von Stack-Wahl. ABS-Region-Hybrid (DC-1) baut auf diesem Stack-Compromise auf. Latenz-Engineering (SPEC-LATENZ-STACK) ist Stack-agnostisch
5. **CRUX-Verbindung:** K_0 geschuetzt durch Shadow-Mode-Rollback. Q_0 erhoeht durch P0-Bug-Sprint-Start. W_0 optimiert (graduelle Skalierung statt Big-Bang). I_min strukturiert (Hot-Switch-Pattern wiederverwendet)

### MHC-Override-Pfad

Edit `Claude-Vault/docs/decision-cards/DC-9OS-STACK-COMPROMISE-2026-04-30.md` → `status: REJECTED` + Begruendung. Architekt rollt zurueck.

### Falsifikations-Bedingung

Pilot-Hildesheim ueber 90 Tage zeigt:
- Apaleo-API-Latenz > 200ms p50 chronisch → Stack-Wechsel zu Mews-Primary erwaegen
- Mews-Shadow-Cost > €5k/Monat pro Hotel → Shadow rausnehmen, ABS-Tier herunterstufen
- DSGVO-Audit-Fail trotz P0-Bug-Sprint → Stack-Konflikt war nicht Wurzelproblem

---

## DC-3: SPEC-LATENZ-STACK (ARCHITEKT-DECIDED — Hybrid Pre-Compute + Edge-Cache + Async-AI)

### Trigger

HeyLou Internet Booking Engine (IBE) muss Search-Results inkl. ABS-Pricing in **p50<100ms / p99<300ms / TTFB<50ms** liefern. Bei naive Implementation faellt Latenz auf 800-1500ms (DB-Roundtrip + AI-Inference + Tax/Fee/Bundle-Logik). **Latenz-Engineering und ABS-Inventarisierung sind orthogonal entkoppelt** — beide Pfade parallel optimierbar.

### Trinity-Optionen

| Option | Pattern | Performance (p99) | Kosten/Mo (7 Hotels) | Risiko |
|--------|---------|-------------------|----------------------|--------|
| **A — Conservative: Pre-Compute Daily + Edge-Cache** | Cloudflare Workers + KV (TTL 6h) | 50-150ms | €100-500 | mittel (Stale 6h, Cache-Invalidation) |
| **B — Aggressive: Real-Time AI + Materialized-Views** | Aurora-Serverless v2 + ECS-Fargate AI | 200-500ms | €1300-5800 | hoch (p99 Tail, AI-Outage = IBE-Outage) |
| **C — Contrarian: Hybrid (gewahlt)** | Pre-Compute + Edge-Cache (TTL 60s SWR) + Async-AI-Refresh | **80-200ms** | **€500-1900** | mittel (Cache-Inkonsistenz reduziert, AI-Outage-Mitigation) |

### Wahl: Option C — Hybrid

### Begruendung

- **Latenz-Performance:** p99 < 200ms (under Conversion-Killer-Schwelle)
- **Cost:** ~3x billiger als Option B, ~2-3x teurer als Option A — sweet spot
- **Aktualitaet:** Stale-Window max 60s (vs 6h bei Option A) — Inventory-Drift-Risk klein
- **AI-Resilienz:** Cache haelt bei AI-Outage, kein IBE-Outage
- **Skalierung:** Cloudflare Edge skaliert horizontal kostenfrei, Aurora-Serverless skaliert vertikal

### MHC-Override-Pfad

Edit `branch-hub/blueprints/SPEC-LATENZ-ENGINEERING-STACK-2026-04-30.md` → `status: REJECTED` + Begruendung.

### Falsifikations-Bedingung

Pilot-Hildesheim-Latenz-Test ueber 30 Tage:
- p99 > 300ms in >5% der Requests → Architektur revidieren
- Stale-Marker > 1% der Requests → AI-Refresh-Worker-Skalierung
- AI-API-Cost > €500/Monat fuer 1 Pilot-Hotel → Modell-Wahl revidieren (lokales Modell statt Cloud-API)

---

## Architekt-Decisions zur KMO-Architektur-Selbst (post Welle-0)

Zusaetzlich zu den drei domain-DCs hat der Architekt waehrend der KMO-Build-Pipeline mehrere Patches als Architekt-Decisions getroffen (P-KMO-A1 bis A7). Detail-Doku siehe [03-MODULES.md](03-MODULES.md). Kurz:

| Patch | Decision | Begruendung |
|-------|----------|-------------|
| P-KMO-A1 Resource-Lease | Trinity-Conservative: SQLite-WAL Self-Built Mutex | low-Ops, debugbar, kein Vendor |
| P-KMO-A2 Saga-Pattern | Trinity-Conservative: Self-Built do/undo + State-Persistence | matched zu existing Patterns, kein Temporal-Setup-Aufwand |
| P-KMO-A3 Outbox-Pattern | Trinity-Conservative: File-System-basiert Atomic-Write + JSON-Format | Drive-Sync-kompatibel, Cross-Machine-tauglich ohne extra Infra |
| P-KMO-A4 Approval-Gate | Trinity-Conservative: HMAC-Signed-Tokens + Hash-Chain Audit-Log | kryptographisch sicher, kein Vendor-Service |
| P-KMO-A5 Data-Class-Filter | 4-Stufen Public/Internal/Confidential/Secret + Pre-Routing-Hook | DSGVO-Schutz + Modell-Vergiftungs-Schutz |
| P-KMO-A6 Control/Data-Plane | Repository-Restructuring kmo_control/governance/executors | Architektur-Sauberkeit + Audit-Faehigkeit |
| P-KMO-A7 Durable-Execution | Trinity-Conservative: Self-Built JSON-State + Event-Sourcing | Crash-Recovery garantiert, kein Temporal-Vendor-Lock |

**Alle Patches:** ARCHITEKT-DECIDED-2026-04-30 mit MHC-Override-Pfad jederzeit.

---

## Pending-Phronesis-Liste (Eskalations-Pfad)

Architekt darf Welle-7-autonom Tier-Wahl + DCs treffen, aber NICHT:

### Pending: Implementation-Trigger (K_0-relevant)

1. **Production-Deploy** der 6 KMO-Module (post Pilot-Run + Martin-Freigabe + Gerdi-CTO-Review)
2. **Cross-System-Architektur-Wechsel mit Rollback-Aufwand >4h** (z.B. Mews-Shadow → Mews-Primary, ohne A/B-Test)
3. **Pilot-Hotel-Investment-Trigger** (450-710k EUR Hildesheim 2026-06-08)
4. **DSGVO-relevante Code-Aktivierung** (auch wenn implementiert, Aktivierung in Production = K_0-relevant)

### Pending: Decision-Themen (Q_0/L13-relevant)

5. **DSGVO-Bug-Bounty-Pattern** (wer haftet bei P0-Bug-Sprint-Latenz?)
6. **Familien-Beziehungs-Aenderung** (nicht KMO-relevant, aber rules/passivitaets-hemmung.md §K_0-Sperr-Liste #3)
7. **Rechtliche/Steuer-Auslegung** (Apaleo-Datenvertrag DSGVO + E-2 Visa)

### Pending: Cross-Branch-Architektur

8. **Welle-2 KMO-Migration** existing 28 LaunchAgents nach `df_executors/` (Mac + Windows + Mobile-Sync)
9. **Welle-3 KMO Production-Lift** auf Cloud-Stage (AWS Fargate / GCP Cloud Run)

---

## K_0-Sperr-Liste-Mapping (welche Aktionen brauchen Martin-Approval)

Aus `rules/passivitaets-hemmung.md §K_0-Sperr-Liste`:

| # | Sperr-Item | KMO-Relevanz |
|---|-----------|--------------|
| 1 | Budget-Allokation > €10k | Pilot-Hotel-Investment 450-710k EUR (Hildesheim) — **JA** |
| 2 | Brand-Identity-Wechsel | nicht KMO-direkt |
| 3 | Familien-Beziehungs-Aenderung | nicht KMO |
| 4 | Rechtliche/Steuer-Auslegung | DSGVO-Hauptung Apaleo+Mews-Datenvertraege — **JA** |
| 5 | **Cross-System-Architektur-Wechsel mit Rollback-Aufwand >4h** | KMO-Production-Deploy + Vault-Backend-Wechsel — **JA fuer Implementation, NEIN fuer Tier-Wahl** |
| 6 | Neue CRUX-Nebenbedingung | nicht KMO-Build, evtl. spaeter (z.B. neue I_min-Domaene fuer KMO-Production) |
| 7 | Familien-Gesundheit-Decisions | nicht KMO |

**Lehre aus Bias-Catalog Layer 2 (PHRONESIS-OUTSOURCING-K0-SPERR-LISTE-MISINTERPRETATION):**

K_0-Sperr-Liste #5 **betrifft Implementation-Trigger**, nicht Tier-Wahl unter Architekt-Hoheit. Trinity-Empfehlung mit MHC-Override-Pfad = ARCHITEKT-DECIDED-Default. Architekt darf Welle-7-autonom 3 Optionen analysieren, eine mit Begruendung waehlen, MHC-Override-Pfad dokumentieren. Erst Implementation-Trigger (Code-Activation, Vendor-Vertrag, Vermoegens-Transfer) ist Phronesis-pflichtig.

---

## Cross-Reference

- **Master-Spec:** `branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md`
- **Wargame-Verdicts:** [08-WARGAMES.md](08-WARGAMES.md) (3 Iterationen Welle-0/1/3)
- **CRUX + rho:** [09-CRUX-RHO.md](09-CRUX-RHO.md) (CRUX-Pfad + rho-Berechnungen)
- **Glossar:** [10-GLOSSARY.md](10-GLOSSARY.md) (Begriffe konsolidiert)
- **Master-Handoff:** `branch-hub/findings/SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md`

[CRUX-MK]
