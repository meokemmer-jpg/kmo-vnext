# KPM-Demo-Application — End-to-End-Pipeline der 9 KPM-Module

**Welle-31 Phase-24 KMO-vNext** — Beweist orchestriertes Zusammenspiel
aller 9 Bio-Pattern-Lift-Module als Trade-Admission-Pipeline. Kein
isolierter Modul-Test, sondern produktionsnaher Stack-End-to-End-Run.

[CRUX-MK]

---

## 1. Pipeline-Diagramm (textbasiert)

```
                       submit_trade()
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 1  feature_flag_engine.evaluate(flag_id, req) |
   |   not enabled? -> REJECT "strategy_disabled"         |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 2  deduplication_engine.check(client_order_id)|
   |   is_duplicate? -> REJECT "duplicate_order"          |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 3  backpressure_engine.evaluate(strategy_id)  |
   |   action=REJECT? -> REJECT "backpressure_blocked"    |
   |   action=DELAY?  -> mark "delayed=True", continue    |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 4  distributed_lock_manager.acquire(           |
   |              instrument_id, position_side, holder)   |
   |   conflict? -> REJECT "lock_held"                    |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 5  trading_failover.route()                   |
   |   -> active_strategy_id (PRIMARY oder FAILED_OVER)   |
   +------------------------------------------------------+
                              |
                              v
   +-- (optional bei chaos_mode=True) --------------------+
   |  STAGE C  chaos_engineering.inject_random(strategy)  |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 6  saga_orchestrator.execute_saga([           |
   |              VALIDATE, RESERVE, EXECUTE,             |
   |              CONFIRM, SETTLE])                       |
   |   != COMPLETED? -> _release_lock(); REJECT           |
   |                    "saga_failed"                     |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 7  homeostasis_controller.record_allocation(  |
   |              asset_class, allocation_pct)            |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 8  audit_event_bus.publish(                   |
   |              event_type, instrument, qty, price,     |
   |              compliance_tags, metadata)              |
   |   -> audit_event_id                                  |
   +------------------------------------------------------+
                              |
                              v
   +------------------------------------------------------+
   |  STAGE 9  distributed_lock_manager.release(token)    |
   +------------------------------------------------------+
                              |
                              v
                  TradeAdmissionResult(success=True, ...)
```

---

## 2. Bio-Pattern-Mapping pro Stage

| # | Stage                   | Bio-Aequivalent              | Modul                              |
|---|-------------------------|------------------------------|------------------------------------|
| 1 | feature_flag            | Genexpressions-Regulation    | kpm_feature_flag_engine            |
| 2 | deduplication           | B-Cell-Memory                | kpm_deduplication_engine           |
| 3 | backpressure            | Karotis-Sinus-Baroreflex     | kpm_backpressure_engine            |
| 4 | lock_acquire            | Synaptische-Verbindung       | kpm_distributed_lock_manager       |
| 5 | failover_route          | Kollateral-Kreislauf         | kpm_trading_failover               |
| C | chaos_inject (optional) | Innate-Immune-Stress-Test    | kpm_chaos_engineering              |
| 6 | saga_execute            | Mitose-Phasen-Sequencing     | kpm_saga_orchestrator              |
| 7 | homeostasis_record      | Thermoregulation-Setpoint    | kpm_homeostasis_controller         |
| 8 | audit_publish           | Lymphatic-System-Drainage    | kpm_audit_event_bus                |
| 9 | lock_release            | Synapse-Decay (Auto-Release) | kpm_distributed_lock_manager       |

**Insight:** Die Pipeline ist isomorph zu einer kompletten Immun-/
Kreislauf-/Stoffwechsel-Kaskade einer lebenden Zelle bei Antigen-
Exposition. Trade = Antigen, Pipeline = 9-stufige Selbstkontrolle.

---

## 3. Use-Cases

### 3.1 Happy-Path 1: Standard Long-Trade (alle 9 Stages PASS)

```python
from kmo_governance.kpm_demo_application import KPMTradeAdmissionPipeline
from kmo_governance.kpm_distributed_lock_manager import PositionSide
from kmo_governance.kpm_feature_flag_engine import FlagState

pipe = KPMTradeAdmissionPipeline(
    primary_strategy_id="kelly-0.4",
    standby_strategy_ids=["kelly-0.3", "kelly-0.2"],
)
pipe.feature_flags.set_state(
    flag_id="strategy_kelly-0.4",
    new_state=FlagState.ENABLED,
    changed_by="ops",
    reason="go-live",
)

result = pipe.submit_trade(
    strategy_id="kelly-0.4",
    instrument_id="BTCUSDT",
    side=PositionSide.LONG,
    quantity=0.5,
    price=42000.0,
    client_order_id="ord-001",
    request_id="req-001",
)
assert result.success
assert result.audit_event_id is not None
assert result.saga_id is not None
```

### 3.2 Happy-Path 2: Failover wenn Primary unprofitabel

```python
# Fuettere primary mit health_threshold (3) Verlusten
for _ in range(3):
    pipe.failover.record_trade_outcome("kelly-0.4", profitable=False)

# Standby muss aktiviert sein
pipe.feature_flags.set_state(
    flag_id="strategy_kelly-0.3",
    new_state=FlagState.ENABLED,
    changed_by="ops",
    reason="failover-pre-enabled",
)

result = pipe.submit_trade(
    strategy_id="kelly-0.4",  # Caller will primary, ...
    instrument_id="ETHUSDT",
    side=PositionSide.LONG,
    quantity=1.0, price=2500.0,
    client_order_id="ord-fo", request_id="req-fo",
)
# ... aber failover.route() entscheidet -> standby aktiv
assert result.active_strategy_id == "kelly-0.3"
```

### 3.3 Happy-Path 3: Chaos-Mode (Pre-Saga-Inject)

```python
result = pipe.submit_trade(
    strategy_id="kelly-0.4",
    instrument_id="BTCUSDT",
    side=PositionSide.LONG,
    quantity=0.5, price=42000.0,
    client_order_id="ord-chaos", request_id="req-chaos",
    chaos_mode=True,  # <-- Test-Hook
)
assert result.success
assert "chaos_inject" in result.decision_path
```

### 3.4 Reject-Path 1: Strategy DISABLED

```python
# Ohne pipe.feature_flags.set_state(... ENABLED ...)
result = pipe.submit_trade(...)
assert result.success is False
assert "strategy_disabled" in result.reason
assert result.decision_path == ("feature_flag",)
```

### 3.5 Reject-Path 2: Duplicate Client-Order-ID

```python
first  = pipe.submit_trade(... client_order_id="ord-X" ...)
second = pipe.submit_trade(... client_order_id="ord-X" ...)
assert first.success
assert second.success is False
assert "duplicate_order" in second.reason
```

### 3.6 Reject-Path 3: Saga-Failure -> Lock-Cleanup

```python
def execute_fails(_step):
    raise RuntimeError("simulated broker reject")
pipe.saga.register_handler(SagaPhase.EXECUTE, execute_fails)

result = pipe.submit_trade(... instrument_id="DOGEUSDT" ...)
assert result.success is False
assert "saga_failed" in result.reason

# Lock muss released sein -> nochmal acquire moeglich
re = pipe.lock_manager.acquire("DOGEUSDT", PositionSide.LONG, "next-strat")
assert re.success
```

---

## 4. Verifikation — Test-Liste (21 Tests passing, 0.05s)

| #  | Test                                          | Tier         | Status |
|----|-----------------------------------------------|--------------|--------|
|  1 | test_full_pipeline_happy_path                 | Conservative | PASS   |
|  2 | test_feature_flag_disabled_rejects            | Aggressive   | PASS   |
|  3 | test_duplicate_order_rejects                  | Aggressive   | PASS   |
|  4 | test_backpressure_blocked_rejects             | Aggressive   | PASS   |
|  5 | test_lock_conflict_rejects                    | Aggressive   | PASS   |
|  6 | test_saga_failure_triggers_cleanup            | Aggressive   | PASS   |
|  7 | test_audit_event_emitted_on_success           | Conservative | PASS   |
|  8 | test_homeostasis_records_post_execute         | Conservative | PASS   |
|  9 | test_concurrent_trades_isolated               | Contrarian   | PASS   |
| 10 | test_chaos_mode_injects_fault                 | Contrarian   | PASS   |
| 11 | test_failover_uses_standby_when_primary_down  | Contrarian   | PASS   |
| 12 | test_decision_path_complete                   | Conservative | PASS   |
| 13 | test_elapsed_ms_measured                      | Conservative | PASS   |
| 14 | test_result_frozen_immutability               | Contrarian   | PASS   |
| 15 | test_invalid_inputs_rejected                  | Aggressive   | PASS   |
| 16 | test_ctor_validation                          | Aggressive   | PASS   |
| 17 | test_saga_compensation_log_on_failure         | Contrarian   | PASS   |
| 18 | test_lock_released_after_saga_fail            | Contrarian   | PASS   |
| 19 | test_repeated_trades_release_locks_correctly  | Contrarian   | PASS   |
| 20 | test_audit_metadata_contains_request_id       | Conservative | PASS   |
| 21 | test_backpressure_delay_does_not_reject       | Contrarian   | PASS   |

Run command:
```bash
cd /Users/make/Projects/dark-factories/kmo
python3 -m pytest kmo_governance/kpm_demo_application/tests/ -v
```

---

## 5. CRUX-Bindung

- **K_0 (Kapitalerhaltung):** 9-Stage-Reject-Kaskade verhindert Half-Open-
  Positions, Lock-Hijacking, Cap-Burst, Duplicate-Submits.
- **Q_0 (Qualitaetsinvarianz):** TradeAdmissionResult ist frozen
  dataclass. decision_path tuple ist immutable Audit-Trail.
- **I_min (Ordnungsminimum):** 9-Stages-Pflicht via deterministische
  Pipeline. Jeder REJECT ist reproducible.
- **W_0 (Working-Capital):** Lock-Auto-Release bei Saga-Fehler oder
  Pipeline-Exception verhindert dauerhaft-gebundenes Capital.

---

## 6. Lieferung

- `kpm_demo_application/__init__.py` (44 Zeilen)
- `kpm_demo_application/kpm_demo_application.py` (~410 Zeilen, ueber Brief-
  Schaetzung wegen vollstaendiger Try/Finally-Cleanup-Logik)
- `kpm_demo_application/tests/__init__.py` (1 Zeile)
- `kpm_demo_application/tests/test_kpm_demo_application.py` (21 Tests)
- `kpm_demo_application/END-TO-END-DEMO.md` (dieses Dokument)

[CRUX-MK]
