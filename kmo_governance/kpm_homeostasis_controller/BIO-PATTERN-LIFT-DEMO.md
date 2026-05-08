# Bio-Pattern-Lift Demo: homeostasis_controller -> kpm_homeostasis_controller [CRUX-MK]

**Welle-26 Phase-19 KMO-vNext Bio-Lift Round-2 (4/5)**
**Datum:** 2026-05-08
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Pattern-Quelle

`kmo_governance/homeostasis_controller/` (Welle-25 Phase-18, System/Hotel-Domain)

- Bio-Aequivalent: Thermoregulation (Hypothalamus-basiert, Setpoint 37C, Cooling/Heating)
- Use-Case: System-Health-Metriken (Latency / CPU / Throughput) auf Setpoint regeln
- Pattern-Inspiration: PID-Regelung + Rolling-Average-Smoothing + State-Machine
- ~341 LoC, MetricSample + CorrectiveAction + HomeostasisDecision + HomeostasisController

## Pattern-Ziel

`kmo_governance/kpm_homeostasis_controller/` (Welle-26 Phase-19, Trading-Domain)

- Use-Case: KPM-Portfolio-Drift-Setpoint-Regelung (Asset-Allocation auf Ziel halten)
- Trading-Aktionen: REDUCE_POSITION / INCREASE_POSITION / HALT (CRITICAL-Schutz K_0)
- 18 Tests (16 Pflicht + 2 Bonus: AllocationSample-Validation + Mixed-Asset-Class-Filter)
- ~340 LoC Code, KPM-Domain-spezifisch (asset_class + allocation_pct + HALT-Action)

## Bio-Mapping (Thermoregulation auf Portfolio-Drift)

| Hotel/System (homeostasis_controller) | Trading (kpm_homeostasis_controller) | Thermoregulation               |
|---------------------------------------|--------------------------------------|--------------------------------|
| `setpoint` (z.B. T=37C, Latency=200ms)| `setpoint_pct` (z.B. 60% Equities)   | Hypothalamus-Setpoint          |
| `metric_name`                         | `asset_class`                        | Body-Sensor-Type (Skin/Core)   |
| `MetricSample`                        | `AllocationSample`                   | Sensor-Reading                 |
| `CorrectiveAction`                    | `RebalanceAction`                    | Effector-Response              |
| `COOLING_ACTIVE`                      | `REDUCING_POSITION`                  | Sweat / Vasodilation           |
| `HEATING_ACTIVE`                      | `INCREASING_POSITION`                | Shiver / Vasoconstriction      |
| `MILD_DEVIATION` (informativ)         | `MILD_DEVIATION` (informativ)        | Mild Discomfort (no response)  |
| `CRITICAL` (default: critical_alarm)  | `CRITICAL` (default: HALT)           | Hyperthermia / Hypothermia     |
| `critical_threshold_pct=25.0` Default | `critical_threshold_pct=15.0` Default| Trading-Volatilitaet           |
| `history_window=50` Default           | `history_window=20` Default          | Trading-Reaktionsgeschwindigkeit|
| `register_action(state, fn)`          | `register_action(state, fn)`         | Custom Effector-Hook           |
| `record_metric(name, value)`          | `record_allocation(class, pct)`      | Sensor-Sample-Pipeline         |

## Pattern-Isomorphie

Strikte Architekturkern-Identitaet, nur Domaenen-Vokabular und Defaults wechseln:

### Identische Architekturkern-Komponenten

1. **Setpoint-basierte Feedback-Regelung**
   - System: avg(latency) gegen setpoint=200ms
   - KPM: avg(allocation_pct) gegen setpoint_pct=60.0

2. **Rolling-Average-Smoothing (Whipsaw-Schutz)**
   - System: history_window=50 glaettet Latency-Spikes
   - KPM: history_window=20 glaettet Markt-Spike-Single-Trades

3. **State-Machine ueber 5 Zustaende**
   - NORMAL -> MILD_DEVIATION -> COOLING/HEATING (oder REDUCE/INCREASE) -> CRITICAL
   - Symmetrische Schwellen-Pruefung in beide Richtungen

4. **Custom-Action-Hook-Mechanismus**
   - `register_action(state, fn)`-API identisch
   - fn(deviation) -> Action wird in evaluate() aufgerufen

5. **Thread-Safe Audit-Trail**
   - threading.RLock + collections.deque(maxlen=history_window)
   - get_history() + get_decisions() liefern Read-Only-Snapshots

### Domain-Differenzen (KPM-spezifisch)

| Differenz                              | Hotel/System          | KPM Trading                   | Begruendung                                   |
|----------------------------------------|-----------------------|-------------------------------|-----------------------------------------------|
| `critical_threshold_pct` Default       | 25.0                  | 15.0                          | Trading volatiler -> engerer Cliff-Schutz     |
| `history_window` Default               | 50                    | 20                            | Trading: schnellere Reaktion gewuenscht       |
| Threshold-Semantik                     | Relative %            | Absolute Prozent-Punkte (pp)  | Allocation ist bereits %, vermeidet Doppel-%  |
| `setpoint` Range                       | beliebig (any float)  | [0, 100]                      | Allocation-Prozent-Constraint                 |
| `asset_class` als Sample-Identifikator | optional              | Pflicht (Filter im evaluate)  | Multi-Asset-Portfolio braucht Filterung       |
| CRITICAL-Default-Action                | `critical_alarm`      | `HALT` (action_type)          | K_0-Schutz: Cliff-Effect-Verhinderung         |
| Action-Typ-Whitelist                   | beliebiger String     | {"REDUCE","INCREASE","HALT"}  | Stricter Typ-Sicherheit fuer Trade-Engine     |
| `target_asset_class` in Action         | nicht vorhanden       | Pflicht-Feld                  | Multi-Asset-Routing zur Trade-Engine          |

## Welle-26 Phase-19 Round-2 Slot

- Round-1 (3/3): apaleo_adapter, mock_hotel_server, chaos_engineering, pre_production_canary
- Round-2 (5/5): rate_limiter_pool, retry_strategy_engine, deduplication_engine,
  **homeostasis_controller (DIESES, 4/5)**, batch_processor

## Risk-Budget-Komplement

`kpm_homeostasis_controller` ergaenzt KPM Variante-D (rules/kpm-sizing.md):

- Variante-D regelt **WIE viel** zu allokieren (Kelly-Fraction 0.25-0.40 kontext-adaptiv)
- `kpm_homeostasis_controller` regelt **OB Drift** behoben werden muss (Setpoint-Feedback)
- Drawdown-Caps in Variante-D bleiben zentral (15%/20%/25% Soft/Hard/No-Go)
- HALT-Action auf CRITICAL-State entspricht "Trading-Pause" Hard-Cap-Verhalten

## Lieferung

- `kmo_governance/kpm_homeostasis_controller/__init__.py` (78 Zeilen)
- `kmo_governance/kpm_homeostasis_controller/kpm_homeostasis_controller.py` (~340 LoC)
- `kmo_governance/kpm_homeostasis_controller/tests/__init__.py` (5 Zeilen)
- `kmo_governance/kpm_homeostasis_controller/tests/test_kpm_homeostasis_controller.py` (18 Tests)
- `kmo_governance/kpm_homeostasis_controller/BIO-PATTERN-LIFT-DEMO.md` (diese Datei)

## CRUX-Bindung

- **K_0:** geschuetzt (HALT-Action bei CRITICAL = Cliff-Effect-Verhinderung,
  kein echtes Trading bis Architektur-Approval)
- **Q_0:** Setpoint-Disziplin verhindert Drift in widerspruechliche Allocation-Lage
- **I_min:** strukturierte 5-State-Machine + Whitelist-Action-Types
- **W_0:** Rolling-Average + history_window verhindern Whipsaw-Trading
  (= Schutz vor Token-/Capital-Verschwendung durch Over-Trading)

[CRUX-MK]
