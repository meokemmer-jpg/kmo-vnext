# Bio-Pattern-Lift Demo: KPM-Distributed-Trade-Lock-Manager [CRUX-MK]

**Welle:** 26 Phase 19
**Pattern-Quelle:** `kmo_governance/distributed_lock_manager/distributed_lock_manager.py` (Welle-21, Hotel-Domain, 373 LoC)
**Bio-Aequivalent:** Synaptische-Verbindung (Pre/Post-Synapse, TTL-Decay, Kompetition)

## Idee

Synaptic-Pattern (TTL-Lease + Token-Validation + Auto-Release + Sweep-Reaper) wird vom
Hotel-Resource-Lock-Domain auf KPM-Trading-Domain gehoben. Lock-Granularitaet wird auf
`(instrument_id, position_side)` verfeinert: LONG und SHORT auf gleichem Instrument sind
unabhaengige synaptische Verbindungen. TTL faellt von 30s (Hotel) auf 5s (Trading-Default,
kurzlebig).

## Isomorphie-Tabelle

| Hotel (`distributed_lock_manager`) | Trading (`kpm_distributed_lock_manager`) | Synaptic-Aequivalent |
|---|---|---|
| `lock_id: str` | `(instrument_id: str, position_side: PositionSide)` | Synapse-ID |
| `holder_id: str` | `holder_strategy_id: str` | Pre-Synapse-Origin |
| `default_ttl_s = 30.0` | `default_ttl_s = 5.0` | Neurotransmitter-Halflife |
| `sweep_interval_s = 5.0` | `sweep_interval_s = 1.0` | Reuptake-Frequenz |
| `Lease` (frozen) | `TradeLease` (frozen) | Aktive Synapse |
| `LockResult` (frozen) | `TradeLockResult` (frozen) | Operations-Return |
| `LockState {FREE,ACQUIRED,EXPIRED,RELEASED}` | `TradeLockState {FREE,ACQUIRED,EXPIRED,RELEASED}` | Synapse-Zustand |
| `acquire(lock_id, holder_id, ttl_s)` | `acquire(instrument_id, position_side, holder_strategy_id, ttl_s)` | Synapse-Bildung |
| `renew(lock_id, lease_token, additional_ttl_s)` | `renew(instrument_id, position_side, lease_token, additional_ttl_s)` | Synaptic-Reinforcement |
| `release(lock_id, lease_token)` | `release(instrument_id, position_side, lease_token)` | Synapse-Aufloesung (Owner) |
| `force_release(lock_id)` | `force_release(instrument_id, position_side)` | Admin-Cleanup |
| `is_held(lock_id)` | `is_held(instrument_id, position_side)` | Synapse-aktiv? |
| `get_state(lock_id)` | `get_state(instrument_id, position_side)` | Synapse-Status |
| `sweep_expired() -> int` | `sweep_expired() -> int` | Stale-Synapse-GC |
| `list_active() -> list[Lease]` | `list_active() -> tuple[TradeLease, ...]` | Aktiv-Synapsen-Snapshot |

## Domain-Spezifika (KPM, Welle-26)

| Aspekt | Hotel | Trading |
|---|---|---|
| **Default-TTL** | 30s (Hotel-Resource haelt laenger) | 5s (Trading-Setup verfaellt schnell) |
| **Sweep-Intervall** | 5s | 1s (haeufigerer Reaper-Run) |
| **Lock-Schluessel** | flacher String | Tupel `(instrument_id, side)` |
| **Side-Independence** | n/a | LONG vs SHORT auf gleichem Instrument = separate Locks |
| **list_active Return** | `list[Lease]` | `tuple[TradeLease, ...]` (immutable Snapshot) |
| **Beispiel-Holder** | `"hotel-cleaner-3"` | `"kelly-0.4-strat"`, `"momentum-rsi-strat"` |

## CRUX-Bindung (Trading-spezifisch verschaerft)

- **K_0 (Familien-Kapital):** `lease_token` (uuid4) verhindert Order-Hijacking durch
  fremde Strategie. Doppel-Orders auf gleichem `(instrument, side)` ausgeschlossen.
- **Q_0 (Qualitaet):** Auto-Release expired Leases verhindert Strategy-Deadlocks bei
  Strategy-Crashes — verhindert "Geister-Locks" die echte Trade-Slots blockieren.
- **I_min (Integritaet):** uuid.uuid4 Token kryptographisch garantiert eindeutigen
  Strategy-Owner-Beleg. Kein Token-Forgeing moeglich.
- **W_0 (Working Capital):** Sweep-on-Acquire haelt amortisierten O(1)-Overhead auch
  bei hoher Order-Frequenz.

## Tests (18 stueck)

1. `test_init_validation` — TTL/Sweep > 0
2. `test_acquire_free_lock_long` — Erfolg + Lease + Token
3. `test_acquire_held_returns_conflict` — Conflict + Holder-Name in Reason
4. `test_acquire_expired_auto_release` — TTL=0.05 + sleep(0.1) + Reacquire
5. `test_acquire_validates_inputs` — Empty/None-Instrument, falsche PositionSide-Type
6. `test_renew_extends` — expires_at > Original, Token+acquired_at preserved
7. `test_renew_invalid_token` — Token-Mismatch -> success=False
8. `test_release_valid_token` — Owner-Release + State -> FREE
9. `test_release_invalid_token` — Falscher Token -> success=False, Lock haelt
10. `test_force_release` — Admin-Override + "force-released" in Reason
11. `test_long_and_short_independent` — gleiche Instrument, separate Locks/Tokens
12. `test_is_held` — True nach acquire, False nach release
13. `test_get_state` — FREE -> ACQUIRED -> EXPIRED -> (sweep) -> FREE
14. `test_sweep_expired` — purged-Count, only-expired removed
15. `test_list_active_excludes_expired` — Tuple-Return, expired hidden
16. `test_concurrent_50_threads_only_one` — Barrier + 50 Threads, exactly 1 Erfolg
17. `test_lease_frozen` + `test_result_frozen` — FrozenInstanceError bei Mutation

## Welle-26 Bio-Pattern-Lift-Bilanz

Welle-26 = Multi-Domain-Pattern-Lift KPM-Trading-Domain. Lift 3/3 Round-1 (nach
`kpm_audit_event_bus` und `kpm_trading_failover`). Pattern unveraendert in Architektur,
nur Lock-Granularitaet + Trading-Defaults angepasst.

## Pattern-Lift Verifikation

- [x] frozen Dataclasses (TradeLease, TradeLockResult)
- [x] threading.RLock (re-entrant lock)
- [x] stdlib only (uuid, time, threading, dataclasses, enum, typing)
- [x] CRUX-MK Header + Footer
- [x] Pre/Post-Conditions in `__post_init__`
- [x] Token-Validation in `release` und `renew`
- [x] Auto-Release im acquire (Sweep-on-Acquire)
- [x] LONG/SHORT-Independence per Tupel-Schluessel

## CRUX-MK
