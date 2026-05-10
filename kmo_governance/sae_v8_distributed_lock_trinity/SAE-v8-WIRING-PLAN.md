# SAE-v8 Wiring Realismus-Plan [CRUX-MK]

**Aktiviert:** 2026-05-09 durch Cross-LLM-V16 REJECTED Welle-34 (Codex GPT-5.5)
**Lambda-Honesty G2:** Ehrliche Dokumentation: Welle-34 SAE-v8-Adapter-Module sind **DEMO**, kein Real-Cross-Repo-Wiring.
**Status:** PLAN (Welle-50+ Implementation pending Repo-Access-Decision)

## Codex-V16-Verdict (workspace-verified)

> *"Welle-34 modules exist in KMO, but SAE-v8 imports/wiring are absent;
> rg found zero SAE-v8 usage of the three adapters. Trinity lock is
> in-memory RLock/dict, duplicates TrinityVariant, and is not integrated
> with core.trinity.TrinitySlot; not a production distributed voting lock.
> Backpressure/homeostasis are standalone samplers; 200-slot pool and
> GovernanceManager q_norm are not enforced from live SAE-v8 state."*

**Aggregat:** 42% (REJECTED). Cross-LLM-V16-File: `branch-hub/cross-llm/2026-05-08-WARGAME-WELLE-34-V16.md`.

## Welle-34 ACHIEVED (Bio-Pattern-Lift-Demo)

3 Module deployed (58 Tests, 1550 LoC):

| Modul | Pattern | Bio-Aequivalent | Tests | LoC |
|---|---|---|---|---|
| sae_v8_distributed_lock_trinity | Synaptic | Synapse | 23 | 517 |
| sae_v8_homeostasis_governance | Thermoregulation | Hypothalamus | 18 | 421 |
| sae_v8_backpressure_slot_admission | Baroreflex | Baroreflex | 17 | 612 |

**Was sie machen:**
- Reproduzieren architektonisches Pattern (Conservative/Aggressive/Contrarian) auf SAE-Slot-Domain-Vokabular
- In-Memory-Lock/Sampling/Voting-Logik thread-safe + RLock-protected
- 16. Multi-Domain-Bio-Pattern-Lift-Beweis (3-Domain-Vergleich pro Modul)

**Was sie NICHT machen (per V16):**
- KEIN `from sae_v8.core.trinity import TrinitySlot` Import
- KEIN Live-State-Sync mit SAE-v8 600-Agent-Pool
- KEIN verteilter Lock zwischen SAE-v8-Workern
- KEIN GovernanceManager-q_norm-Enforcement aus SAE-v8

## Welle-50+ Real-Wiring-Plan (3 Phasen)

### Phase 1: SAE-v8-Repo-Access (Phronesis P6-?)

**Frage an Martin:** Read-Access-Approval fuer `dark-factories/sae-v8/` von KMO-Repo?

**Optionen:**
- **A** (Conservative): SAE-v8 als git submodule in KMO einhaengen (read-only-clone)
- **B** (Aggressive): Symlink `dark-factories/kmo/sae_v8 → dark-factories/sae-v8/sae_v8`
- **C** (Contrarian): Adapter via REST/RPC-Bridge (kein direkter Import, aber Live-State-Sync via HTTP)

**Default-Empfehlung Architekt:** Option A (submodule) — nicht-destruktiv, reversibel, kein Filesystem-Tampering.

### Phase 2: Adapter-Mapping-Tabelle (welche TrinitySlot-Klasse braucht welche Adapter-Methode)

| KMO-Adapter | SAE-v8-Klasse (Real-Source) | Pflicht-Methoden | Read/Write |
|---|---|---|---|
| sae_v8_distributed_lock_trinity.SAEv8DistributedLockTrinity | sae_v8.core.trinity.TrinitySlot | acquire(), release(), get_winner() | Read+Write |
| sae_v8_homeostasis_governance.SAEv8HomeostasisGovernance | sae_v8.core.governance.GovernanceManager | get_q_norm(), get_T_max(), update_q() | Read-only |
| sae_v8_backpressure_slot_admission.SAEv8BackpressureSlotAdmission | sae_v8.core.slot_pool.SlotPool | get_active_count(), get_capacity(), reserve() | Read+Write |

**Wiring-Pflicht-Tests (post-Real-Wiring):**
- `test_real_trinity_slot_lock_integration` — KMO-Adapter haelt Lock, SAE-v8-Worker beobachtet Lock-Held
- `test_real_governance_q_norm_propagates` — SAE-v8 setzt q=2.0, KMO-Adapter sieht new q_norm
- `test_real_slot_pool_reservation_propagates` — KMO-Adapter reserviert Slot, SAE-v8-Pool sieht slot_count++

### Phase 3: Risiko-Analyse

**Risiken Real-Wiring:**

| Risiko | Wahrscheinlichkeit | Mitigation |
|---|---|---|
| SAE-v8-Repo-Schema-Drift bricht KMO | HIGH | Adapter-Layer mit Version-Pinning + Test-Regression-Suite |
| Read-Tampering aus KMO in SAE-v8 | LOW (read-only-Phase) | nur Phase-2-Read-Access initial; Write erst Phase-3 nach Audit |
| Distributed-Lock-Inkonsistenz bei Cross-Repo | MED | RFC3161-Anker fuer kritische Lock-State-Snapshots (siehe `rules/external-anchor-requirement-audit-logs.md`) |
| Performance-Penalty bei Live-Sync | MED | Cache-Layer in Adapter (TTL 1s) + Health-Check-Cadence |
| Production-Drift waehrend SAE-v8-Migration | HIGH | KMO-Adapter ENV-VAR-gated (`SAE_V8_REAL_WIRING_ENABLED=true`) per `rules/env-var-gated-real-integration-default.md` |

**SAE-v8 Read-Access-Sicherheits-Profil:**
- Phase 2: read-only OK (Pre-Action-Verification per K13)
- Phase 3 (Write): nur via PHRONESIS_TICKET (per env-var-gated-Rule)
- Kein-Auto-Override: Hard-Stop bei Failed-Pre-Cond

## Welle-50 Bootstrap-Action (in HANDOFF-S Plan-V11 dokumentiert)

```
1. Phronesis P6-? Martin: Repo-Access Option A/B/C entscheiden
2. cd /Users/make/Projects/dark-factories
3. Wenn Option A: git submodule add sae-v8 kmo/sae_v8_real
4. Wenn Option B: ln -s /Users/make/Projects/dark-factories/sae-v8/sae_v8 kmo/sae_v8
5. Wenn Option C: SPEC-SAE-v8-RPC-BRIDGE-V1.md schreiben
6. Adapter-Wiring nach Mapping-Tabelle (Phase 2)
7. Real-Wiring-Tests (3 Tests pro Adapter)
8. Cross-LLM-V21+ Adversarial-Audit auf Real-Wiring (statt Demo)
```

## Lambda-Honesty Self-Audit (G2 Pflicht)

- **G2:** Real-Wiring-Status wird ehrlich dokumentiert (DEMO-only bis Welle-50+, kein Pseudo-Production-Claim).
- **G3:** SAE-v8-Wiring-Tier ist KEIN HARDENED, sondern PRE-PRODUCTION-CONDITIONAL (`rules/pre-production-conditional-default.md`).
- **G6:** Codex-V16-Findings (3 of 3) sind echte Real-Issues (Imports absent, Lock duplicates, Sampler-Standalone) — nicht Halluzinationen.
- **G14:** Surprise-Integration: Welle-34 als "SAE-v8-Wiring" gelabelt war ueberzogen. Korrektur in HANDOFF-R + HANDOFF-S Plan-V11.

## Beziehung zu anderen Rules

- **`rules/env-var-gated-real-integration-default.md`:** Phase-3-Real-Aktivierung MUSS ENV-VAR-gated sein.
- **`rules/df-akzeptanz-kriterien.md` K13:** Pre-Action-Verification fuer Real-Wiring Pflicht.
- **`rules/pre-production-conditional-default.md`:** SAE-v8-Real-Wiring max PRODUCTION-READY-CONDITIONAL bis 90-Tage-Pilot.
- **`rules/external-anchor-requirement-audit-logs.md`:** Distributed-Lock-State braucht RFC3161-Anker.

## CRUX-Bindung

- **K_0:** geschuetzt (kein false-Production-Wiring-Claim, keine destruktive SAE-v8-Modifikation)
- **Q_0:** epistemische Integritaet via Lambda-Honesty G2
- **W_0:** Phronesis-Bandwidth fuer Repo-Access-Decision spaeter via P6-?
- **L_Martin:** stabilisiert durch transparenten Plan + Welle-50+-Roadmap

## Falsifikations-Bedingung

Diese Plan-Datei ist falsifiziert wenn:
- Repo-Access wird NIE genehmigt → Welle-34-Module bleiben permanent DEMO (akzeptabel als Bio-Pattern-Lift-Beweis)
- Real-Wiring-Performance-Penalty > 10x Latenz → RPC-Bridge-Option C revidieren
- SAE-v8-Schema-Drift > 5x/Jahr → Adapter-Maintenance unbezahlbar

## Cross-LLM-Audit-Pflicht

Status: SKELETON-CONDITIONAL. Aktivierung Welle-50+ erfordert:
1. Cross-LLM-V21+ Adversarial-Pruefung des Wiring-Plans
2. Empirische Pilot-Phase auf 1 Adapter (z.B. nur Trinity-Lock zuerst)
3. Performance-Latenz gemessen (Schwelle <100ms p99)

[CRUX-MK]
