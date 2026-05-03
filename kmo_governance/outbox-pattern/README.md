# KMO Outbox Pattern [CRUX-MK]

**Patch:** P-KMO-A3 (SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30)
**Zweck:** Durable Dispatch-Queue zwischen Mac/Windows/Mobile via branch-hub/outbox/ (Drive-Sync).

## Pattern

```
Producer (Mac)        branch-hub/                    Consumer (Windows)
   |                  ├─ outbox/<m>-<topic>-<seq>.json     |
   ├─ publish() ─────>│                              ─────>│ poll_and_process()
   │  atomic-write    │                                    │  ├─ skip if processed (idempotent)
   │  (tempfile +     │                                    │  ├─ handler(event)
   │   os.replace)    │                                    │  ├─ acknowledge() -> ack/
   │                  ├─ outbox-ack/<m>-<topic>-<seq>.ack  │  └─ retry++ on fail
   │                  └─ outbox-dlq/<m>-<topic>-<seq>.dlq  │     after 3: move to dlq/
```

## Idempotency

Consumer-DB (`~/Library/Application Support/kmo/consumer-<id>.db`) trackt processed `event_id`.
Gleiches Event (gleiche UUID) = einmal verarbeitet, auch ueber Cross-Machine-Drive-Sync-Races.

## Files

- `kmo_outbox_producer.py` (~190 LoC): `OutboxProducer.publish()`, `republish_failed_acks()`
- `kmo_outbox_consumer.py` (~250 LoC): `OutboxConsumer.subscribe()`, `poll_and_process()`, `acknowledge()`, `move_to_dlq()`
- `tests/test_outbox.py` (~210 LoC): pytest 6 Tests (Atomic-Write, Happy-Path 3, Idempotency, DLQ, Cross-Machine, Topic-Filter)

## Tests

```bash
cd /Users/make/Projects/dark-factories/kmo/outbox-pattern
python -m pytest tests/ -v
```

## DLQ-Inspektion

```bash
ls branch-hub/outbox-dlq/
# Re-Inject moeglich nach Bugfix: cp dlq/<file>.dlq.json outbox/<file>.json (manuell)
```

## CRUX-Bindung

- **K_0:** geschuetzt — Atomic-Write verhindert Drive-Sync-Korruption
- **Q_0:** Idempotenz schuetzt vor Doppel-Verarbeitung (z.B. Doppel-Mail-Send)
- **W_0:** Background-Dispatch entlastet Martin-Bandbreite

[CRUX-MK]
