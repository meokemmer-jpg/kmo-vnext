# Bio-Pattern-Lift Demo: homeostasis_controller -> sae_v8_homeostasis_governance [CRUX-MK]

**Welle-34 Phase-27 KMO-vNext Bio-Lift Lift 15/N (3. SAE-v8-Modul)**
**Datum:** 2026-05-07
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Pattern-Quelle

`kmo_governance/homeostasis_controller/` (Welle-25 Phase-18, System/Hotel-Domain)

- Bio-Aequivalent: Thermoregulation (Hypothalamus-basiert, Setpoint 37C, Cooling/Heating)
- Use-Case: System-Health-Metriken (Latency / CPU / Throughput) auf Setpoint regeln
- Pattern-Inspiration: PID-Regelung + Rolling-Average-Smoothing + State-Machine
- ~341 LoC, MetricSample + CorrectiveAction + HomeostasisDecision + HomeostasisController

## Pattern-Ziel

`kmo_governance/sae_v8_homeostasis_governance/` (Welle-34 Phase-27, SAE-v8-Domain)

- Use-Case: SAE-v8 Slot-Governance-Tier-Drift-Setpoint-Regelung (q_norm auf Ziel halten)
- SAE-Aktionen: RELEGATE_SLOT / PROMOTE_SLOT / HALT (CRITICAL-Schutz K_0)
- 18 Tests (16 Pflicht + 2 Bonus: GovernanceSample-Validation + Multi-Slot-Filter)
- ~330 LoC Code, SAE-v8-Domain-spezifisch (slot_id + q_norm + HALT-Action)
- KEIN Real-SAE-v8-Production-Code-Tampering (nur Pattern-Lift-Demo)

## Bio-Mapping (3-Domain-Vergleich: Hotel/KPM/SAE-v8)

| Hotel/System (homeostasis_controller) | KPM Trading (kpm_homeostasis_controller) | SAE-v8 Governance (sae_v8_homeostasis_governance) | Thermoregulation                |
|---------------------------------------|------------------------------------------|---------------------------------------------------|---------------------------------|
| `setpoint` (Latency=200ms / T=37C)    | `setpoint_pct` (60% Equities Allocation) | `setpoint_q_norm` (0.0 = balanciert in [-2,+2])   | Hypothalamus-Setpoint           |
| `metric_name`                         | `asset_class`                            | `slot_id`                                         | Body-Sensor-Type (Skin/Core)    |
| `MetricSample`                        | `AllocationSample`                       | `GovernanceSample`                                | Sensor-Reading                  |
| `CorrectiveAction`                    | `RebalanceAction`                        | `SlotAdjustmentAction`                            | Effector-Response               |
| `COOLING_ACTIVE`                      | `REDUCING_POSITION`                      | `RELEGATING_SLOT`                                 | Sweat / Vasodilation            |
| `HEATING_ACTIVE`                      | `INCREASING_POSITION`                    | `PROMOTING_SLOT`                                  | Shiver / Vasoconstriction       |
| `MILD_DEVIATION` (informativ)         | `MILD_DEVIATION` (informativ)            | `MILD_DEVIATION` (informativ)                     | Mild Discomfort (no response)   |
| `CRITICAL` (default: critical_alarm)  | `CRITICAL` (default: HALT)               | `CRITICAL` (default: HALT)                        | Hyperthermia / Hypothermia      |
| `critical_threshold_pct=25.0` Default | `critical_threshold_pct=15.0` Default    | `critical_threshold_pct=30.0` Default             | Domain-Volatilitaet             |
| `mild_threshold_pct=5.0` Default      | `mild_threshold_pct=5.0` Default         | `mild_threshold_pct=10.0` Default                 | q-Norm-Range = 4 (broad)        |
| `history_window=50` Default           | `history_window=20` Default              | `history_window=50` Default                       | Reaktionsgeschwindigkeit        |
| `register_action(state, fn)`          | `register_action(state, fn)`             | `register_action(state, fn)`                      | Custom Effector-Hook            |
| `record_metric(name, value)`          | `record_allocation(class, pct)`          | `record_governance(slot_id, q_norm)`              | Sensor-Sample-Pipeline          |

## Threshold-Volatilitaet-Vergleich (Kerneinsicht)

| Domain    | mild_threshold_pct | critical_threshold_pct | Begruendung                                                 |
|-----------|---------------------|------------------------|-------------------------------------------------------------|
| Hotel     | 5.0                 | 25.0                   | System-Latency stabil, kleine % Schwankung schon relevant   |
| KPM       | 5.0                 | 15.0                   | Trading volatil, enger Cliff-Schutz noetig (K_0)            |
| SAE-v8    | 10.0                | 30.0                   | q_norm reagiert auf Reward-Stream stark, Range = 4 (broad)  |
| Bio-Real  | ~1%                 | ~10%                   | Koerpertemperatur sehr eng reguliert (37 +/- 0.5C)          |

## Pattern-Isomorphie

Strikte Architekturkern-Identitaet ueber 3 Domaenen, nur Vokabular und Defaults wechseln:

### Identische Architekturkern-Komponenten

1. **Setpoint-basierte Feedback-Regelung**
   - System: avg(latency) gegen setpoint=200ms
   - KPM: avg(allocation_pct) gegen setpoint_pct=60.0
   - SAE-v8: avg(q_norm) gegen setpoint_q_norm=0.0

2. **Rolling-Average-Smoothing (Whipsaw-Schutz)**
   - System: history_window=50 glaettet Latency-Spikes
   - KPM: history_window=20 glaettet Markt-Spike-Single-Trades
   - SAE-v8: history_window=50 glaettet q_norm-Spikes durch Reward-Stream-Schock

3. **State-Machine ueber 5 Zustaende**
   - NORMAL -> MILD_DEVIATION -> COOL/HEAT (oder REDUCE/INCREASE oder
     RELEGATE/PROMOTE) -> CRITICAL
   - Symmetrische Schwellen-Pruefung in beide Richtungen
   - HALT-Action bei CRITICAL (Cliff-Effect-Schutz)

4. **Custom-Action-Hook-Mechanismus**
   - `register_action(state, fn)`-API identisch
   - fn(deviation) -> Action wird in evaluate() aufgerufen

5. **Thread-Safe Audit-Trail**
   - threading.RLock + collections.deque(maxlen=history_window)
   - get_history() + get_decisions() liefern Read-Only-Snapshots (tuple)

### Domain-Differenzen (SAE-v8-spezifisch)

| Differenz                              | Hotel/System          | KPM Trading                   | SAE-v8 Governance                    | Begruendung                                            |
|----------------------------------------|-----------------------|-------------------------------|--------------------------------------|--------------------------------------------------------|
| `critical_threshold_pct` Default       | 25.0                  | 15.0                          | 30.0                                 | Reward-Stream-Volatilitaet hoeher als Trading          |
| `mild_threshold_pct` Default           | 5.0                   | 5.0                           | 10.0                                 | q_norm-Range = 4 (vs 100% / Latency-Range)             |
| `history_window` Default               | 50                    | 20                            | 50                                   | Slot-Governance braucht Historie fuer F_CUM_DECAY-Sync |
| Threshold-Semantik                     | Relative %            | Absolute Prozent-Punkte (pp)  | Prozent-von-q-Range (Range=4)        | q-Range fest 4 -> Prozent-Mapping noetig               |
| `setpoint` Range                       | beliebig (any float)  | [0, 100]                      | [-2, +2]                             | SAE-v8 §4 Invariante 1 (q-Scale-Constraint)            |
| Sample-Identifikator                   | metric_name (string)  | asset_class (Pflicht-Filter)  | slot_id (Pflicht, optional Filter)   | SAE-v8: Multi-Slot-Audit-Trail per slot_id             |
| CRITICAL-Default-Action                | `critical_alarm`      | `HALT` (action_type)          | `HALT` (action_type)                 | K_0-Schutz: Cliff-Effect-Verhinderung                  |
| Action-Typ-Whitelist                   | beliebiger String     | {"REDUCE","INCREASE","HALT"}  | {"RELEGATE","PROMOTE","HALT"}        | Stricter Typ-Sicherheit pro Domain                     |
| Action-Target-Feld                     | nicht vorhanden       | `target_asset_class`          | `target_slot_id`                     | Trade-Routing / Slot-Routing                           |
| Filter im evaluate                     | nicht vorhanden       | Pflicht (asset_class)         | Optional (slot_id=None / slot_id=X)  | SAE-v8: aggregiert ueber alle Slots oder per slot      |

## Welle-34 Phase-27 SAE-v8-Lift-Slot

- Welle-34 = SAE-v8-Wiring-Welle (3. SAE-v8-Modul-Lift)
- Lift 15/N: 15. Bio-Pattern-Lift insgesamt im KMO-vNext-Programm
- Real-SAE-v8-Code (rules/coding.md F_CUM_DECAY=0.98, q_norm-Property) BLEIBT UNVERAENDERT
- Diese Demo lebt parallel als Bio-Pattern-Lift-Showcase, ohne Production-Code zu beruehren

## Beziehung zu SAE-v8 Governance-Mechaniken

`sae_v8_homeostasis_governance` ergaenzt SAE-v8 Trinity-Pattern (rules/coding.md §2):

- **Trinity-Slot-Voting** regelt **WER pro Slot gewinnt** (Conservative/Aggressive/Contrarian)
- **F_CUM_DECAY=0.98** regelt **Slot-Fitness-Verfall ueber Zeit** (Halbwertszeit ~34 Tage)
- **`sae_v8_homeostasis_governance`** regelt **OB Slot-Drift behoben werden muss**
  (Setpoint-Feedback ueber q_norm-Distribution)
- **HALT-Action auf CRITICAL** entspricht "Slot-Adjustment-Pause" bei Reward-Schock
  (verhindert Slot-Massaker bei Reward-Stream-Anomalie)

## Lieferung

- `kmo_governance/sae_v8_homeostasis_governance/__init__.py` (~85 Zeilen)
- `kmo_governance/sae_v8_homeostasis_governance/sae_v8_homeostasis_governance.py` (~325 LoC)
- `kmo_governance/sae_v8_homeostasis_governance/tests/__init__.py` (5 Zeilen)
- `kmo_governance/sae_v8_homeostasis_governance/tests/test_sae_v8_homeostasis_governance.py` (18 Tests)
- `kmo_governance/sae_v8_homeostasis_governance/BIO-PATTERN-LIFT-DEMO.md` (diese Datei)

## CRUX-Bindung

- **K_0:** geschuetzt (HALT-Action bei CRITICAL = Cliff-Effect-Verhinderung,
  kein Slot-Massaker bei Reward-Schock)
- **Q_0:** Setpoint-Disziplin verhindert q_norm-Drift in widerspruechliche
  Governance-Tier-Lage
- **I_min:** strukturierte 5-State-Machine + Whitelist-Action-Types + slot_id-Audit
- **W_0:** Rolling-Average + history_window verhindern Whipsaw-Promotion/Relegation
  (= Schutz vor Token-/Capital-Verschwendung durch Slot-Churn)

[CRUX-MK]
