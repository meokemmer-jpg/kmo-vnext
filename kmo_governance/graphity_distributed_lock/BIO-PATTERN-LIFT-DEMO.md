# Bio-Pattern-Lift Demo: Graphity-Distributed-Edit-Lock [CRUX-MK]

**Welle:** 30 Phase 23 (Wild-Code-Blindtest 3/3 — externe Verlags-Domain)
**Pattern-Quelle:** `kmo_governance/distributed_lock_manager/distributed_lock_manager.py` (Welle-21, Hotel-Domain, 373 LoC)
**Bio-Aequivalent:** Synaptische-Verbindung (Pre/Post-Synapse, TTL-Decay, Kompetition)
**Lift:** 12 von 12

## Idee

Synaptic-Pattern (TTL-Lease + Token-Validation + Auto-Release + Sweep-Reaper) wird vom
Hotel-Resource-Lock-Domain ueber KPM-Trading-Domain hinaus auf die externe Graphity-Verlag-Domain
gehoben. Lock-Granularitaet wird auf `(book_id, chapter_id, scope)` verfeinert: vier
Edit-Scopes (CHAPTER / SECTION / PARAGRAPH / ANNOTATION) auf gleichem Chapter sind
unabhaengige synaptische Verbindungen. TTL faellt nicht auf 5s wie im Trading-Fall,
sondern steigt auf 600s (10min Editor-Inactivity-Window) — Editor-Workflow ist langsamer
als Order-Placement.

## 3-Domain-Isomorphie-Tabelle

**Belegt: Bio-Pattern-Architektur ist domain-unabhaengig — Strukturkern unveraendert,
nur Domain-Vokabular adaptiert.**

| Hotel (`distributed_lock_manager`) | KPM (`kpm_distributed_lock_manager`) | Graphity (`graphity_distributed_lock`) | Synaptic-Aequivalent |
|---|---|---|---|
| `lock_id: str` | `(instrument_id, position_side)` | `(book_id, chapter_id, scope)` | Synapse-ID |
| `holder_id: str` | `holder_strategy_id: str` | `holder_author_id: str` | Pre-Synapse-Origin |
| `default_ttl_s = 30.0` | `default_ttl_s = 5.0` | `default_ttl_s = 600.0` | Neurotransmitter-Halflife |
| `sweep_interval_s = 5.0` | `sweep_interval_s = 1.0` | `sweep_interval_s = 60.0` | Reuptake-Frequenz |
| `Lease` (frozen) | `TradeLease` (frozen) | `EditLease` (frozen) | Aktive Synapse |
| `LockResult` (frozen) | `TradeLockResult` (frozen) | `EditLockResult` (frozen) | Operations-Return |
| `LockState` | `TradeLockState` | `EditLockState {FREE,LOCKED,EXPIRED,RELEASED}` | Synapse-Zustand |
| `acquire(lock_id, holder_id, ttl_s)` | `acquire(instr, side, holder, ttl)` | `acquire(book, chap, scope, holder, ttl)` | Synapse-Bildung |
| `renew` | `renew` | `renew` | Synaptic-Reinforcement |
| `release(lock_id, lease_token)` | `release(instr, side, token)` | `release(book, chap, scope, token)` | Synapse-Aufloesung (Owner) |
| `force_release(lock_id)` | `force_release(instr, side)` | `force_release(book, chap, scope)` | Admin-Cleanup |
| `is_held` | `is_held` | `is_held` | Synapse-aktiv? |
| `get_state` | `get_state` | `get_state` | Synapse-Status |
| `sweep_expired() -> int` | `sweep_expired() -> int` | `sweep_expired() -> int` | Stale-Synapse-GC |
| `list_active() -> list[Lease]` | `list_active() -> tuple[TradeLease, ...]` | `list_active() -> tuple[EditLease, ...]` | Aktiv-Synapsen-Snapshot |
| n/a | n/a | `list_active_for_book(book_id)` | Per-Buchprojekt-Filter (Editor-Dashboard) |

## 3-Domain-Spezifika-Vergleich

| Aspekt | Hotel (Welle-21) | KPM-Trading (Welle-26) | Graphity-Verlag (Welle-30) |
|---|---|---|---|
| **Default-TTL** | 30s | 5s (kurzlebig) | 600s (Editor-Inactivity-Window) |
| **Sweep-Intervall** | 5s | 1s (haeufiger) | 60s (seltener) |
| **Lock-Schluessel** | flacher String | Tupel `(instrument, side)` | Tripel `(book, chapter, scope)` |
| **Granularitaets-Achse** | n/a | LONG vs SHORT | 4 Scopes (CHAPTER/SECTION/PARAGRAPH/ANNOTATION) |
| **list_active Return** | `list[Lease]` | `tuple[...]` | `tuple[...]` |
| **Beispiel-Holder** | `"hotel-cleaner-3"` | `"kelly-0.4-strat"` | `"author_kemmer"`, `"author_lektor"` |
| **K_0-Risiko** | Resource-Konflikt | Order-Hijacking + Doppel-Trade | VG-Wort-Verlust durch Edit-Konflikt |

## CRUX-Bindung (Verlag-spezifisch)

- **K_0 (Familien-Kapital, indirekt):** `lease_token` (uuid4) verhindert Edit-Hijacking
  durch fremde Authoren. Doppel-Edits auf gleichem `(book, chapter, scope)` ausgeschlossen
  — verhindert VG-Wort-Verlust durch unerkannte Plagiate / Mehrfach-Speicherung.
- **Q_0 (Qualitaet):** Auto-Release expired Leases verhindert Author-Deadlocks bei
  Editor-Crashes — verhindert "Geister-Locks" die Lektorat-Workflows blockieren.
  METIS-Compliance setzt nachvollziehbare Edit-Atomicity voraus.
- **I_min (Integritaet):** uuid.uuid4 Token kryptographisch garantiert eindeutigen
  Author-Owner-Beleg. Kein Token-Forgeing moeglich. Author-Audit-Trail erhalten.
- **W_0 (Working Capital):** Sweep-on-Acquire haelt amortisierten O(1)-Overhead auch
  bei Multi-Author-Workflow ueber 5 parallele Buchprojekte (Symbiotic Minds, AI Leadership,
  Mathematik der Macht, Die Souveraene Maschine, Welt 2050).

## Tests (~22 stueck)

**Init / Validation (1)**
- `test_init_validation` — TTL/Sweep > 0

**Acquire (4)**
- `test_acquire_free_chapter_lock` — Erfolg + Lease + Token
- `test_acquire_held_returns_conflict` — Conflict + Holder-Name in Reason
- `test_acquire_expired_auto_release` — TTL=0.05 + sleep(0.1) + Reacquire
- `test_acquire_validates_inputs` — Empty/None + falsche Scope-Type

**Renew (3)**
- `test_renew_extends` — expires_at > Original, Token+acquired_at preserved
- `test_renew_invalid_token` — Token-Mismatch -> success=False
- `test_renew_lock_not_found` — Lock nicht vorhanden

**Release (2)**
- `test_release_valid_token` — Owner-Release + State -> FREE
- `test_release_invalid_token` — Falscher Token -> success=False, Lock haelt

**Force-Release (2)**
- `test_force_release` — Admin-Override + "force-released" in Reason
- `test_force_release_not_found` — Lock-not-found

**Scope-/Chapter-/Book-Independence (4)**
- `test_different_scopes_independent` — CHAPTER vs PARAGRAPH parallel
- `test_all_four_scopes_independent` — Alle 4 EditScopes parallel
- `test_different_chapters_independent` — book_a/chap_1 vs book_a/chap_2
- `test_different_books_independent` — book_a vs book_b mit gleichem chap_id

**Inspection (5)**
- `test_is_held` — True nach acquire, False nach release
- `test_get_state` — FREE -> LOCKED -> EXPIRED -> (sweep) -> FREE
- `test_sweep_expired` — purged-Count, only-expired removed
- `test_list_active` — Tuple-Return, expired hidden
- `test_list_active_for_book_filters` — Filter auf book_id

**Concurrent (1)**
- `test_concurrent_50_threads_only_one` — Barrier + 50 Threads, exactly 1 Erfolg

**Frozen (2)**
- `test_lease_frozen` — FrozenInstanceError bei Mutation
- `test_result_frozen` — FrozenInstanceError bei Mutation

## Welle-30 Wild-Code-Blindtest-Bilanz

Welle-30 = Wild-Code-Blindtest 3/3, externe Domain (Graphity-Verlag).
Ergebnis: Pattern unveraendert in Architektur, nur Lock-Granularitaet (Tripel statt Paar)
und Verlag-Defaults (lange TTL fuer Editor-Inactivity-Window) angepasst. **Lift 12 von 12 erreicht.**

3-Domain-Vergleich (Hotel/Trading/Verlag) belegt: Synaptic-Pattern ist eine echte
Bio-Pattern-Architektur — sie ueberlebt Domain-Wechsel ohne strukturelle Modifikation.
Externe Domain (Verlag) ist genau so kompatibel wie interne Hotel/KPM-Domains.

## Pattern-Lift Verifikation

- [x] frozen Dataclasses (EditLease, EditLockResult)
- [x] threading.RLock (re-entrant lock)
- [x] stdlib only (uuid, time, threading, dataclasses, enum, typing)
- [x] CRUX-MK Header + Footer
- [x] Pre/Post-Conditions in `__post_init__`
- [x] Token-Validation in `release` und `renew`
- [x] Auto-Release im acquire (Sweep-on-Acquire)
- [x] Scope-Independence per Tripel-Schluessel
- [x] Chapter-Independence per Tripel-Schluessel
- [x] Book-Independence per Tripel-Schluessel
- [x] Bonus: `list_active_for_book(book_id)` als Editor-Dashboard-Hilfsmethode

## CRUX-MK
