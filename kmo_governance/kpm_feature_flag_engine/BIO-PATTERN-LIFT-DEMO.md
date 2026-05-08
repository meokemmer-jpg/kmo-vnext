# Bio-Pattern-Lift Demo: feature_flag_engine -> kpm_feature_flag_engine [CRUX-MK]

**Welle-29 Phase-22 KMO-vNext Plan-V7**
**Datum:** 2026-05-08
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Pattern-Quelle

`kmo_governance/feature_flag_engine/` (Welle-9, Hotel-Domain)

- Bio-Aequivalent: Genexpressions-Regulation (Promoter/Enhancer/Silencer)
- Use-Case: Hotel-Feature-Flags (z.B. NEW_CHECKIN_FLOW, GUEST_PROFILE_AB_TEST)
- ~17 Tests passing, ~635 LoC

## Pattern-Ziel

`kmo_governance/kpm_feature_flag_engine/` (Welle-29 Phase-22, Trading-Domain)

- Use-Case: KPM-Trading-Strategy-Activation (DISABLED/RAMP_UP/ENABLED/EMERGENCY_OFF)
- 16 Tests passing, ~310 LoC
- KPM-Domain-spezifisch: State-Machine + Emergency-Apoptosis-Trigger + percentage_rollout-Gradient nur in RAMP_UP

## Bio-Mapping (Genexpressions-Regulation)

Wie Gene durch Promoter/Repressor-Region geregelt werden (an/aus + Gradient), schalten Feature-Flags Trading-Strategies graduell ein/aus. Der Expression-Gradient (RNA-Polymerase-Bindungs-Effizienz) entspricht dem `percentage_rollout` waehrend der RAMP_UP-Phase.

## Isomorphie-Tabelle

Die Tabelle zeigt die strikte Pattern-Isomorphie. Architekturkern bleibt identisch, nur Domaenen-Vokabular und State-Maschine wechseln:

| Konzept                     | Hotel-Domain (feature_flag_engine)        | Trading-Domain (kpm_feature_flag_engine)         | Genexpressions-Regulation             |
|-----------------------------|-------------------------------------------|--------------------------------------------------|---------------------------------------|
| **Identifier**              | `flag_id`                                 | `flag_id`                                        | Gen-ID                                |
| **Linked-Resource**         | `(implizit ueber rule_type)`              | `strategy_id`                                    | Promoter-Target-Gene                  |
| **State-Maschine-Enum**     | `FlagRuleType` (BOOLEAN/PERCENTAGE/CONTEXTUAL) | `FlagState` (DISABLED/RAMP_UP/ENABLED/EMERGENCY_OFF) | Promoter-Bindungs-Modi          |
| **State DISABLED**          | `BOOLEAN(enabled=False)`                  | `FlagState.DISABLED`                             | Repressor-bound (off, kein Transkript)|
| **State RAMP_UP**           | `PERCENTAGE(percentage=X)`                | `FlagState.RAMP_UP` + `percentage_rollout=X`     | Partial-Promoter-Activation           |
| **State ENABLED**           | `BOOLEAN(enabled=True)`                   | `FlagState.ENABLED`                              | Full-Expression                       |
| **State EMERGENCY_OFF**     | (kein Aequivalent, nur unregister_flag)   | `FlagState.EMERGENCY_OFF` (sticky bis clear)     | Apoptosis-Trigger (irreversibel)      |
| **Frozen-Definition**       | `FlagRule`                                | `FlagDefinition`                                 | Genom-Locus (Sequenz unveraenderlich) |
| **Frozen-Decision-Output**  | `FlagEvalRecord`                          | `FlagDecision` (mit Reason + state)              | Transkriptions-Event                  |
| **Audit-Trail-Klasse**      | `FlagAuditLog` (deque mit Distribution)   | embedded `_audit` deque + `FlagAuditEvent`       | Epigenetisches Histon-Acetylierungs-Log |
| **State-Change-Event**      | (implizit via `update_rule()`)            | `FlagAuditEvent` (old_state, new_state, reason)  | Histon-Modifikations-Event            |
| **Hauptklasse**             | `FeatureFlagEngine`                       | `KPMFeatureFlagEngine`                           | Transkriptions-Komplex                |
| **Determinismus-Hash**      | `md5(flag_id+user_id) % 100`              | `md5(flag_id+request_id) % 100`                  | Stochastische Promoter-Bindung        |
| **Bucket-Routing**          | `PercentageRollout.is_enabled(user_id)`   | embedded in `evaluate()` fuer RAMP_UP            | Polymerase-II-Bindungs-Wahrscheinlichkeit |
| **Multi-Variant**           | `ABTestVariantSelector` (Multi-Variant)   | (NICHT geliftet, KPM braucht binaere Activation) | Alternative-Splicing                  |
| **Contextual-Rules**        | `ContextualRule` (AND/OR ueber attrs)     | (NICHT geliftet, request_id reicht fuer Strategy)| Enhancer-Loop-Signaling               |
| **Synchronisation**         | `threading.RLock`                         | `threading.RLock`                                | Zellkern-Membran-Kontrolle            |
| **Pre-Conditions**          | `flag_id non-empty, percentage in [0,100]`| `flag_id+strategy_id non-empty, pct in [0,100], retention > 0` | DNA-Sequenz-Pflicht        |

## KPM-Domain-spezifische Erweiterungen

Vier Erweiterungen ueber die reine Pattern-Lift hinaus, die Trading-Domain-Realitaeten reflektieren:

1. **State-Machine statt Rule-Typ:**
   - Hotel: `FlagRuleType` ist Klassifikation (welche Auswertungs-Logik?)
   - Trading: `FlagState` ist State-Maschine (Lebenszyklus mit erlaubten Uebergaengen)
   - Begruendung: Trading-Strategies haben einen Lebenszyklus (Bootstrap -> Ramp -> Live -> Emergency-Stop). Rein deklarative Rules reichen nicht; State-Transitionen muessen audit-pflichtig sein.

2. **EMERGENCY_OFF-Apoptosis:**
   - Hotel: kein Aequivalent (unregister_flag faktisch endgueltig)
   - Trading: `FlagState.EMERGENCY_OFF` ist sticky (blockiert weitere `set_state`-Calls, nur via `clear_emergency()` aufzuheben)
   - Begruendung: Production-Incidents (z.B. Risk-Budget-Verletzung, Margin-Call) erfordern atomaren Stop, der nicht versehentlich durch Race-Condition rueckgaengig gemacht werden kann.

3. **percentage_rollout NUR in RAMP_UP:**
   - Hotel: PercentageRollout funktioniert immer wenn `rule_type == PERCENTAGE`
   - Trading: `set_percentage_rollout` schlaegt mit RuntimeError fehl ausserhalb von RAMP_UP
   - Begruendung: Im Trading-Kontext bedeutet RAMP_UP "Strategy laeuft graduell hoch". DISABLED+50% oder ENABLED+50% sind semantisch unsauber; explizite State-Maschine vermeidet Konfigurations-Drift.

4. **FlagAuditEvent ist erste Klasse:**
   - Hotel: `FlagAuditLog` als zentrale Klasse mit `record_evaluation`
   - Trading: jede State-Aenderung erzeugt `FlagAuditEvent` (frozen Dataclass) mit `old_state`/`new_state`/`changed_by`/`reason`/`timestamp`
   - Begruendung: MiFID-/BaFin-Audit verlangt nachvollziehbare State-Wechsel ("wer hat wann warum aktiviert"). Evaluation-Records reichen nicht; State-Change-Audit ist regulatorische Pflicht.

## Verifikation: Test-Konzepte

| Test-Konzept                            | Hotel-Domain                            | Trading-Domain                                  |
|-----------------------------------------|-----------------------------------------|-------------------------------------------------|
| Konstruktor-Validation                  | `test_init_validation`                  | `test_init_validation`                          |
| Registry-Operation                      | `test_register_flag_idempotent`         | `test_register_flag` + `test_register_duplicate_raises` |
| Lookup-Fehler                           | `test_get_unknown_returns_default`      | `test_get_flag_unknown_raises`                  |
| State-Wechsel                           | (impliz. via `update_rule`)             | `test_set_state_creates_audit_event`            |
| Constraint-Pruefung                     | -                                       | `test_set_percentage_rollout_only_ramp_up`      |
| Off-State Evaluation                    | `test_boolean_disabled`                 | `test_evaluate_disabled_returns_false`          |
| On-State Evaluation                     | `test_boolean_enabled`                  | `test_evaluate_enabled_returns_true`            |
| Determinismus                           | `test_percentage_deterministic`         | `test_evaluate_ramp_up_uses_hash_deterministic` |
| Verteilung                              | `test_percentage_distribution_~target`  | `test_evaluate_ramp_up_distribution`            |
| Sticky-State                            | -                                       | `test_emergency_off_blocks_state_change`        |
| State-Recovery                          | -                                       | `test_clear_emergency_unblocks`                 |
| Audit-Filter                            | `test_audit_log_filter`                 | `test_audit_log_filtered_by_flag`               |
| Thread-Safety                           | `test_concurrent_register`              | `test_concurrent_set_state_50_threads`          |
| Immutability Decision                   | (frozen Dataclass)                      | `test_decision_frozen`                          |
| Immutability Event                      | (frozen Dataclass)                      | `test_event_frozen`                             |

## Pattern-Lift-Bilanz

- **Wiederverwendete Architektur:** frozen Dataclasses, threading.RLock, hashlib.md5 Bucket-Routing, deque Audit-Log, Pre/Post-Conditions, stdlib-only.
- **Domaenen-Spezifika:** State-Maschine mit 4 Zustaenden, Emergency-Apoptosis, Compliance-Audit-Trail-Pflicht, RAMP_UP-only-Rollout-Gates.
- **Bio-Plausibilitaet:** Genexpressions-Regulation ist gut studiertes biologisches Pattern; die Analogie zur Strategy-Activation (DISABLED=Repressor, RAMP_UP=Partial-Activation, ENABLED=Full-Expression, EMERGENCY_OFF=Apoptosis) ist semantisch konsistent.

## Welle-29-Kontext (Plan-V7 Done-Definition)

Dieses Modul ist das **9. KPM-Bio-Pattern-Lift** und das **50. Modul** in der KMO-vNext-Plan-V7-Architektur. Es schliesst die Phase-22 Bio-Pattern-Lift-Serie und erfuellt die Done-Definition (>=50 Module operativ).

Naechste Schritte (Welle-30+):
- Cross-LLM-Audit (Codex + Gemini + Grok) fuer Promotion auf CROSS-LLM-2OF3-HARDENED
- Integration in `kmo_master_orchestrator` als Strategy-Activation-Layer
- Coupling mit `kpm_chaos_engineering` fuer Failure-Injection-Tests

[CRUX-MK]
