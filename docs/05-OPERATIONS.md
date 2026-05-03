---
type: documentation
domain: kmo-pipeline-welle-7
phase: operations
crux_mk: true
datum: 2026-04-30T22:00+02:00
status: ACTIVE
parent: SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md
ebene: E1
---

# KMO Operations + Failure-Recovery [CRUX-MK]

Runtime-Operations, Failure-Modes, Recovery-Procedures fuer die KMO-Pipeline (Welle-7) in DEV-Stage. Komplementaer zu `04-DEPLOYMENT.md` (Setup) und `06-TESTING.md` (Verifikation).

---

## 1. Health-Endpoints + URL-Map

### 1.1 Lokal (Mac-Direct)

| Endpoint | Method | Auth | Erwartung |
|----------|--------|------|-----------|
| `http://localhost:8081/health` | GET | none | `{"status":"ok","service":"kmo-gateway-stub"}` (HTTP 200) |
| `http://localhost:8081/version` | GET | none | `{"version":"0.1.0-dev-stub","service":"...","ts":"<iso>"}` |
| `http://localhost:8081/demo` | GET | Basic-Auth | HTML Status-Dashboard (5 Patches + last action-log ts) |
| `http://localhost:8081/<other>` | GET | none | `{"error":"not_found","path":"..."}` (HTTP 404) |

### 1.2 Cloudflare-Tunnel (Public-URL)

| Endpoint | Auth | Use-Case |
|----------|------|----------|
| `https://kmo-dev.<your-domain>/health` | none | Externer Healthcheck (Monitoring) |
| `https://kmo-dev.<your-domain>/demo` | Basic-Auth | Martin-Remote-Review Yogamobil |

### 1.3 Curl-Beispiele

```bash
# Lokaler Healthcheck
curl -fsS http://localhost:8081/health
# {"status": "ok", "service": "kmo-gateway-stub"}

# Version-Info
curl -fsS http://localhost:8081/version
# {"version": "0.1.0-dev-stub", "service": "kmo-gateway-stub", "ts": "2026-04-30T20:30:00+00:00"}

# Demo-Dashboard mit Basic-Auth
curl -u martin:change-me http://localhost:8081/demo
# HTML mit <table> der 5 Patches + last action-log ts

# Public via Cloudflare
curl -u martin:change-me https://kmo-dev.kemmer-knowledge.io/demo
```

---

## 2. Log-Locations

### 2.1 Container-Logs (live)

```bash
# Pro Container (-f = follow, --tail = letzte N Zeilen)
docker logs -f --tail 50 kmo-gateway
docker logs -f --tail 50 kmo-approval-gate
docker logs -f --tail 50 kmo-lease-manager
docker logs -f --tail 50 kmo-data-class-filter
docker logs -f --tail 50 kmo-saga-engine
docker logs -f --tail 50 kmo-outbox
docker logs -f --tail 50 kmo-cloudflared

# Alle gleichzeitig (compose)
docker compose -f docker-compose.kmo-dev.yml logs -f --tail 50
```

**Format:** `2026-04-30 20:30:01 INFO kmo-gateway-stub <message>` (LogLevel via `KMO_LOG_LEVEL`).

### 2.2 Audit-Trail (persistent)

| Log | Pfad (Mac-Host) | Owner | Format |
|-----|-----------------|-------|--------|
| Action-Log | `branch-hub/audit/action-log.jsonl` | `~/.claude/rules/audit-trail.md §1` | 1 JSONL/Zeile pro Write/Edit |
| Permission-Log | `branch-hub/audit/permission-log.jsonl` | §2 | 1 JSONL/Zeile pro Tool-Permission |
| Workflow-State | `branch-hub/workflow-state/<branch>-state.json` | §3 | 1 JSON-Doc pro Branch |
| Bias-Catalog | `branch-hub/learnings/bias-catalog.jsonl` | self-discipline.md §4 | 1 JSONL/Zeile pro Eigenfehler |
| DLQ (Dead-Letter) | `dev-stage/outbox-dlq/` | A3-Pattern | 1 JSON-File pro fehlgeschlagenes Event |
| Auth-Health | `branch-hub/audit/auth-health-log.jsonl` | auth-expiry-detection.md | 1 JSONL/Zeile pro Auth-Check |

**Action-Log-Format:**
```json
{"ts":"2026-04-30T20:30:00Z","branch":"mac-instance","action":"WRITE","target":"docs/04-DEPLOYMENT.md","reason":"Subagent-B Welle-7","source":"kmo-pipeline"}
```

### 2.3 Container-interne Logs (im Volume)

`kmo-data` Volume enthaelt:
- `leases.db` (SQLite-WAL): aktive Leases, Holders, Expiry-TS
- `saga-state/` (FS): pro Saga-Run ein State-File
- `outbox/` (FS): pending Events
- `outbox-ack/` (FS): acked Events
- `outbox-dlq/` (FS): failed Events (siehe Failure-Mode F4)

---

## 3. Failure-Modes (8 Klassen)

| ID | Failure-Mode | Detection | Resolution | Owner-Modul |
|----|--------------|-----------|------------|-------------|
| F1 | Lease-Conflict | LeaseManager.acquire returns None; 2. Pipeline blockiert | Warten auf Release ODER stale-lease auto-release nach `ttl_sec`; manuell: `lease.release(token)` | A1 lease-manager |
| F2 | Saga-Phase-Fail | SagaStatus != DONE; do_phase wirft Exception | Compensate-Chain laeuft auto (undo p2 -> undo p1); Lease in `finally` released | A2 saga-pattern |
| F3 | Outbox-Idempotency-Conflict | seq_num bereits vergeben; OutboxConsumer skipt | Ack-skip (no-op); kein Crash, Sequence bleibt monoton | A3 outbox-pattern |
| F4 | Approval-Gate-Tamper-Detection | HMAC-SHA256 fail; Bearer-JWT invalid | `approve()` returns False; Deploy NICHT ausgefuehrt; Audit-Log mit `decision:DENY` | A4 approval-gate |
| F5 | Crash-Recovery | DurableStateMachine instance-restart auf gleichem state_root | Resume vom letzten persistierten State; sequences kontigu; transitions repliziert | A7 durable-execution |
| F6 | Stale-Lock | Lease `ttl_sec` abgelaufen | `lock_stale_after_s` Trigger -> auto-release; neue acquire kommt durch | A1 lease-manager |
| F7 | Container-Crash | Docker `restart: unless-stopped` triggert | Auto-Restart; State-Volume bleibt; Re-Hydration aus persistenten Files | docker-compose |
| F8 | Drive-Sync-Drift | `kmo-audit`-Bind zeigt veraltete Daten | rsync push from LOCAL (Mac) nach MIRROR (Drive); Re-Mount des Volumes | OS-Level (Drive-FS) |

### 3.1 Failure-Mode-Detail

#### F1: Lease-Conflict

**Detection:**
```python
token = lease.acquire(ResourceType.DF, "shared-resource", holder="pipeline-2", ttl_sec=120)
if token is None:
    # F1 detected: Resource locked by other pipeline
```

**Resolution:**
- **Auto:** Warten bis erste Pipeline `release()` ruft (im `finally`-Block).
- **Auto-Stale:** Falls erste Pipeline crasht, `ttl_sec` (default 120s) triggert Auto-Release.
- **Manuell:** `sqlite3 leases.db "DELETE FROM leases WHERE resource_id='shared-resource'"` (NUR im Notfall — verletzt Audit-Trail).

**Falsifikations-Bedingung:** F1-Resolution ist falsifiziert wenn:
- Stress-Test (PRE-5) zeigt `ttl_sec` greift nicht bei 100 Threads.
- Manueller Cleanup notwendig in >5% der Faelle.

#### F2: Saga-Phase-Fail

**Detection:**
```python
saga_result = saga.execute("saga-001", initial_input={...})
if saga_result.status != SagaStatus.DONE:
    # F2 detected: phase failed, compensate ran
    print(f"phases_done: {saga_result.phases_done}/7")
```

**Resolution:**
- **Auto:** SagaEngine ruft `undo_<phase>` in Reverse-Reihenfolge fuer alle DONE-Phasen.
- **Lease-Release:** `try/finally` in `_run_full_pipeline` garantiert Release auch bei Fehler.

**Empirisch belegt:** PRE-3 T4 — 3 do_calls (p1,p2,p3-fail), 2 undo_calls (p2,p1 reverse), Lease released. PASS.

#### F3: Outbox-Idempotency-Conflict

**Detection:**
```python
producer.publish("mac", "kmo-pipeline", {...})
# Wenn idempotency_key bereits existiert: skip silently
```

**Resolution:**
- Kein Action erforderlich. OutboxProducer detektiert Duplikate via `state_db` und idempotency_key.
- Consumer sieht Event nur einmal.

#### F4: Approval-Gate-Tamper

**Detection:**
- HMAC-SHA256 mismatch -> `verify_token()` returns False.
- Hash-Chain-Bruch -> Audit-Log inkonsistent.
- Bearer-JWT expired -> 401.

**Resolution:**
- `approve()` returns False, `decision: DENY` in Audit.
- Token re-issue durch Approver-1 erforderlich.
- Hash-Chain-Recovery: nicht moeglich (Tamper-Evidence by-design).

#### F5: Crash-Recovery

**Detection:**
- Container-Restart, State-Machine-Reinstance auf gleichem `state_root`.

**Resolution:**
```python
sm = DurableStateMachine(state_root=Path("/app/data/durable-state"), lock_stale_after_s=10.0)
# Auto-Resume aus letztem persistierten Event
sm.transition_phase("wf-001", "checkpoint-3", "checkpoint-4", {...})
```

**Empirisch belegt:** PRE-3 T5 — history-len pre=3, post=3, sequences 1..3 kontigu. PASS.

#### F6: Stale-Lock (auto-release)

**Detection:** `now - lease.acquired_at > ttl_sec`

**Resolution:** SQLite-WAL-Mutex in `acquire()` checkt Stale + cleared automatisch. Atomic via `INSERT OR REPLACE`.

#### F7: Container-Crash

**Detection:** `docker compose ps` zeigt `Restarting (1) 2 seconds ago`.

**Resolution:**
- `restart: unless-stopped` Policy -> Docker-Auto-Restart.
- State persistent in Volumes -> Re-Hydration ohne Datenverlust.
- **Wenn Restart-Loop:** `docker logs <container> --tail 200` -> Root-Cause finden.

#### F8: Drive-Sync-Drift

**Detection:** Demo-Dashboard zeigt veraltete `last action-log ts`.

**Resolution:**
```bash
# rsync push from Mac-LOCAL nach Cloud-MIRROR (Drive)
rsync -avz \
  ~/Projects/dark-factories/kmo/branch-hub/audit/ \
  ~/Library/CloudStorage/.../branch-hub/audit/

# Re-Mount des Volumes (compose restart)
docker compose -f docker-compose.kmo-dev.yml restart kmo-gateway
```

---

## 4. STOP.flag Mechanik

Per `kmo_lease_manager` und `~/.claude/rules/df-akzeptanz-kriterien.md` K15 Concurrent-Spawn-Mutex.

### 4.1 Wann setzen

- **Auth-Expiry:** `branch-hub/audit/STOP-DF-XX-auth-expired.flag` (siehe `auth-expiry-detection.md`)
- **Cascade-Failure:** Wenn 2+ DFs in 10 Min versagen
- **Manuell:** Martin-Phronesis ("STOP all KMO until further notice")
- **Quota-Overrun:** K11.b Pipeline-Cost-Estimate Hard-Cap erreicht

### 4.2 Wo

```
branch-hub/audit/STOP-DF-XX-<reason>.flag    # Pro DF separate Flag
branch-hub/audit/STOP-KMO-ALL.flag           # Globaler KMO-Stop
dev-stage/STOP.flag                          # Container-Level (nicht standardisiert)
```

### 4.3 Was passiert

1. Pre-Run-Check pruft `STOP.flag`-Existence.
2. Bei Existence: `LeaseManager.acquire()` liefert `None`, `SagaEngine.execute()` exits early.
3. Audit-Log mit `decision: BLOCKED_BY_STOP_FLAG`.
4. Recovery: `rm <flag>` + naechster Run laeuft normal.

---

## 5. Monitoring

Empfohlene Metriken (DEV-Stage informell, Production formal via Prometheus/Grafana):

| Metrik | Ziel | Alert-Schwelle |
|--------|------|----------------|
| `lease_acquire_p99` | <100ms | >500ms |
| `lease_acquire_failure_rate` | <0.1% | >1% |
| `saga_phase_duration_p99` | <2s | >10s |
| `saga_compensate_rate` | <2% | >5% |
| `outbox_lag` (pending events) | <50 | >500 |
| `outbox_dlq_count` | 0 | >10 |
| `approval_deny_rate` | <0.5% | >2% |
| `gateway_health_uptime` | 99.9% | <99% |
| `container_restart_count` | <1/Tag | >5/Tag |
| `cloudflared_tunnel_latency` | <500ms | >2000ms |

**DEV-Monitoring (manuell):**
```bash
# Container-Stats
docker stats --no-stream

# Healthcheck-Status
docker compose ps --format json | jq '.[] | {name, status: .Status, health: .Health}'

# Audit-Log-Lag (last entry age)
tail -1 branch-hub/audit/action-log.jsonl | jq '.ts'
```

---

## 6. Recovery-Procedures (Step-by-Step)

### 6.1 Recovery: Container-Restart-Loop

```bash
# 1. Detection
docker compose ps   # Zeigt "Restarting (1) X seconds ago"

# 2. Root-Cause
docker logs --tail 200 kmo-<service>
# Common: ImportError, FileNotFoundError, OSError

# 3. Fix
# - ImportError: Dockerfile dependencies fehlen
# - FileNotFoundError: Volume-Mount-Path falsch
# - OSError: Permissions (non-root user kmo)

# 4. Rebuild + Up
docker compose -f docker-compose.kmo-dev.yml build <service>
docker compose -f docker-compose.kmo-dev.yml up -d <service>

# 5. Verifikation
curl -fsS http://localhost:8081/health
docker logs --tail 50 kmo-<service>
```

### 6.2 Recovery: Lease-Deadlock

```bash
# 1. Detection
sqlite3 /tmp/kmo-leases.db "SELECT * FROM leases WHERE expires_at < strftime('%s','now')"
# Output: stale leases listed

# 2. Auto-Cleanup (sollte greifen, falls nicht):
sqlite3 /tmp/kmo-leases.db "DELETE FROM leases WHERE expires_at < strftime('%s','now')"

# 3. Audit-Log
echo '{"ts":"<iso>","branch":"mac","action":"DELETE","target":"leases.db",
       "reason":"manual stale-lease cleanup","source":"recovery-procedure"}' \
  >> branch-hub/audit/action-log.jsonl
```

### 6.3 Recovery: Approval-Gate Hash-Chain-Break

```bash
# 1. Detection
# approval-gate Audit-Log zeigt hash_prev != hash_new beim aktuellen Eintrag.

# 2. KEIN Auto-Recovery (Tamper-Evidence by-design)
# 3. Decision-Card erforderlich (Martin-Phronesis K_0)
# 4. Hash-Chain-Reset NUR durch:
#    - Backup des broken-State
#    - Genesis-Block neu schreiben
#    - Audit-Log-Eintrag mit Decision-Card-Referenz
```

### 6.4 Recovery: Cloudflare-Tunnel-Down

```bash
# 1. Detection
curl https://kmo-dev.<domain>/health   # Connection refused / timeout

# 2. Lokal funktioniert?
curl http://localhost:8081/health      # OK -> Tunnel-Problem

# 3. Tunnel-Token check
docker logs kmo-cloudflared --tail 30
# "Unauthorized" -> Token expired

# 4. Token regenerieren
cloudflared tunnel token kmo-dev
# .env updaten
docker compose restart cloudflared

# 5. Verifizieren
curl https://kmo-dev.<domain>/health
```

### 6.5 Recovery: Drive-Sync-Mount Empty

```bash
# 1. Detection
docker exec kmo-gateway ls -la /app/audit
# Empty oder old files

# 2. Host-Path check
ls -la "$KMO_AUDIT_HOST_PATH"
# Wenn da: Mount-Problem; wenn leer: Drive-Sync-Problem

# 3a. Mount-Problem: Container-Recreate
docker compose -f docker-compose.kmo-dev.yml up -d --force-recreate kmo-gateway

# 3b. Drive-Sync-Problem: Force-Resync
# Open Google Drive App -> Pause Sync -> Resume Sync
```

---

## 7. Operations-Cheatsheet

```bash
# Quick-Restart aller Services
docker compose -f docker-compose.kmo-dev.yml restart

# Force-Recreate (Image-Pull + Volume bleibt)
docker compose -f docker-compose.kmo-dev.yml up -d --force-recreate

# Logs aller Services tail
docker compose -f docker-compose.kmo-dev.yml logs --tail 100 -f

# Single-Service rebuild
docker compose -f docker-compose.kmo-dev.yml build kmo-gateway
docker compose -f docker-compose.kmo-dev.yml up -d kmo-gateway

# Volumes snapshot
docker run --rm -v dev-stage_kmo-data:/data -v $(pwd):/backup busybox \
  tar czf /backup/kmo-data-$(date +%Y%m%d).tar.gz -C /data .

# Volumes restore
docker run --rm -v dev-stage_kmo-data:/data -v $(pwd):/backup busybox \
  tar xzf /backup/kmo-data-20260430.tar.gz -C /data
```

---

[CRUX-MK]
