---
type: documentation
domain: kmo-pipeline-welle-7
phase: deployment
crux_mk: true
datum: 2026-04-30T22:00+02:00
status: ACTIVE
parent: SESSION-HANDOFF-MASTER-MAC-HEYLOU-OTA-KMO-PIPELINE-2026-04-30.md
ebene: E1
---

# KMO Deployment Runbook [CRUX-MK]

Deployment + Setup-Runbook fuer die KMO-Pipeline (Kemmer-Master-Orchestrator) v0.3.0 ADOPT-PILOT-ONLY. Stage: DEV-Stage Mac-Local Docker + Cloudflare-Tunnel. **NICHT FUER PRODUCTION.** K_0/Q_0-relevante Daten gehoeren NIE in diesen Stack (siehe `~/.claude/rules/df-akzeptanz-kriterien.md` K13 Pre-Action-Verification-Pflicht).

---

## 1. Voraussetzungen

### 1.1 Hardware + OS

- **Mac:** macOS 13+ (Apple Silicon getestet, Intel sollte funktionieren)
- **Linux:** Ubuntu 22.04+ / Debian 12+ (production-Migration-Pfad)
- **RAM:** mind. 8 GB frei (6 Container + Tunnel = ~1.5 GB Steady-State)
- **Disk:** mind. 5 GB frei (Image-Layer + Volume-Daten)

### 1.2 Software

| Tool | Version | Check-Command | Install-Hint |
|------|---------|---------------|--------------|
| Python | 3.11+ (3.14 lokal) | `python3 --version` | `brew install python@3.11` |
| Docker Desktop | 4.30+ | `docker --version` | https://docs.docker.com/desktop/install/mac-install/ |
| docker compose | v2 (eingebaut) | `docker compose version` | Mit Docker Desktop |
| cloudflared | latest | `cloudflared --version` | `brew install cloudflared` |
| Git | 2.40+ | `git --version` | `brew install git` |

### 1.3 Repository-Struktur

```
~/Projects/dark-factories/kmo/
|- kmo_governance/           <- 6 Module (approval-gate, lease-manager, ...)
|   |- approval-gate/        <- A4 Dual-Control + HMAC + Atomic-Pre-Deploy
|   |- lease-manager/        <- A1 SQLite-WAL Resource-Lock
|   |- data-class-filter/    <- A5 SECRET/PRIVATE/INTERNAL/PUBLIC Klassifikation
|   |- saga-pattern/         <- A2 7-Phase do/undo Compensate-Chain
|   |- outbox-pattern/       <- A3 Atomic-Write + Idempotency
|   |- durable-execution/    <- A7 Event-Sourcing State-Machine
|- dev-stage/                <- Phase-5 DEV-Stack (Docker-Compose + Cloudflare)
|- tests/                    <- E2E-Pipeline-Tests
|- docs/                     <- Diese Dokumentation
```

---

## 2. Lokal-Setup (ohne Docker)

Fuer Pytest-Runs und Modul-Entwicklung ohne Container-Overhead.

### 2.1 Python-venv + Dependencies

```bash
cd ~/Projects/dark-factories/kmo
python3.11 -m venv .venv
source .venv/bin/activate

# Install pro Modul (oder global mit pyyaml + pytest)
pip install pyyaml pytest

# Optional: Editable Install pro Modul
for mod in kmo_governance/*/; do
  if [ -f "$mod/pyproject.toml" ]; then
    pip install -e "$mod"
  fi
done
```

### 2.2 Schema-Migration (Lease-Manager)

`lease-manager` braucht eine SQLite-Schema-Initialisierung beim ersten Run. Schema-File ist `kmo_governance/lease-manager/schema.sql`:

```bash
# Auto-Init beim ersten LeaseManager()-Konstruktor wenn db_path nicht existiert.
# Manueller Init nur fuer Inspection:
sqlite3 /tmp/kmo-leases.db < kmo_governance/lease-manager/schema.sql
```

### 2.3 Test-Suite ausfuehren

```bash
# Alle Module:
pytest kmo_governance/ tests/ -v

# Einzeln:
pytest kmo_governance/lease-manager/tests/ -v
pytest tests/test_pre3_e2e_full_pipeline.py -v
```

---

## 3. Docker-Compose Deployment (DEV-Stage)

Phase-5 Mac-Local Docker mit 6 Services + Cloudflare-Tunnel-Sidecar.

### 3.1 docker-compose.kmo-dev.yml — Service-Block-fuer-Block

Datei: `~/Projects/dark-factories/kmo/dev-stage/docker-compose.kmo-dev.yml`

#### 3.1.1 Networks + Volumes

```yaml
networks:
  kmo-net:
    driver: bridge       # Bridge-Netzwerk, nur intra-Container-Traffic
volumes:
  kmo-data:              # Named-Volume fuer Lease-DB + Saga-State
    driver: local
  kmo-audit:             # Bind-Mount auf Drive-Sync (read-only)
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${KMO_AUDIT_HOST_PATH:-/Users/make/.../branch-hub/audit}
```

**Wichtig:** `kmo-audit` ist **read-only Bind-Mount** auf den `branch-hub/audit/`-Folder. Container koennen Audit-Logs lesen (z.B. fuer Demo-Dashboard), aber NICHT schreiben. Schutz vor Cross-Tier-Korruption.

#### 3.1.2 Service: kmo-gateway (Port 8081 → 8080)

```yaml
kmo-gateway:
  build:
    context: .
    dockerfile: Dockerfile.gateway
  container_name: kmo-gateway
  environment:
    - KMO_LOG_LEVEL=${KMO_LOG_LEVEL:-DEBUG}
    - KMO_DEMO_AUTH_USER=${KMO_DEMO_AUTH_USER:-martin}
    - KMO_DEMO_AUTH_PASS=${KMO_DEMO_AUTH_PASS:-change-me}
  ports:
    - "8081:8080"        # Host:Container — 8080 belegt von open-webui
  volumes:
    - kmo-audit:/app/audit:ro   # Audit-Read-only
    - kmo-data:/app/data        # Daten-Volume
  networks:
    - kmo-net
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health',timeout=2).status==200 else 1)"]
    interval: 15s        # Alle 15s pingen
    timeout: 5s          # Max 5s warten
    retries: 3           # 3 Fails -> unhealthy
    start_period: 5s     # Erste 5s sind Tolerance-Window
  restart: unless-stopped
```

**Endpoints:**
- `GET /health` -> JSON `{"status":"ok"}`
- `GET /version` -> JSON Version + ISO-TS
- `GET /demo` -> HTML Status-Dashboard (Basic-Auth Pflicht)

**Port-Konflikt-Hinweis:** 8080 wird oft von anderen Apps belegt (open-webui, Jenkins, ...). Daher Host-Port **8081**. Bei weiterem Konflikt: Override via `ports: - "9999:8080"`.

#### 3.1.3 Service: approval-gate (A4)

```yaml
approval-gate:
  build:
    context: ../kmo_governance/approval-gate
  container_name: kmo-approval-gate
  environment:
    - KMO_APPROVAL_SECRET=${KMO_APPROVAL_SECRET:-change-me-in-prod-32-bytes-min}
    - KMO_LOG_LEVEL=${KMO_LOG_LEVEL:-DEBUG}
  networks:
    - kmo-net
  healthcheck:
    test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
    interval: 30s
    timeout: 5s
    retries: 3
  restart: unless-stopped
```

**KMO_APPROVAL_SECRET:** HMAC-SHA256-Schluessel fuer Dual-Control-Token-Generation. **>=32 bytes empfohlen**, in DEV nur Default, in Production via Secret-Manager.

#### 3.1.4 Service: lease-manager (A1)

```yaml
lease-manager:
  build:
    context: ../kmo_governance/lease-manager
  container_name: kmo-lease-manager
  environment:
    - KMO_LOG_LEVEL=${KMO_LOG_LEVEL:-DEBUG}
  volumes:
    - kmo-data:/app/data    # SQLite-DB persistent
  networks:
    - kmo-net
  healthcheck:
    test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
    interval: 30s
    timeout: 5s
    retries: 3
  restart: unless-stopped
```

**Volume:** `kmo-data` ist Named-Volume — die `leases.db` (SQLite-WAL-Mode) ueberlebt Container-Restarts.

#### 3.1.5 Services: data-class-filter, saga-pattern, outbox-pattern

Identisches Pattern wie lease-manager (Build-Context aus Sibling-Folder, kmo-net, Healthcheck, restart unless-stopped). Keine externen Ports — Inter-Service-Kommunikation laeuft ueber `kmo-net`.

#### 3.1.6 Service: cloudflared (Tunnel-Sidecar)

```yaml
cloudflared:
  image: cloudflare/cloudflared:latest
  container_name: kmo-cloudflared
  command: tunnel --no-autoupdate run
  environment:
    - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:-}
  networks:
    - kmo-net
  depends_on:
    kmo-gateway:
      condition: service_healthy   # Wartet bis Gateway healthy
  restart: unless-stopped
```

**Pre-Bedingung:** `CLOUDFLARE_TUNNEL_TOKEN` muss in `.env` gesetzt sein (siehe Schritt 4.3).

### 3.2 Build-Step

```bash
cd ~/Projects/dark-factories/kmo/dev-stage
docker compose -f docker-compose.kmo-dev.yml build
```

**Was passiert:**
1. Pro Service wird der `Dockerfile`-Context gebaut (kmo-gateway lokal, sibling-Services in `../kmo_governance/<name>/`).
2. Base-Image `python:3.11-slim` wird gepullt (~50 MB).
3. Pro Sibling-Dockerfile: `apt-get install gcc` (~80 MB), `pip install pyyaml pytest`.
4. App-Code wird ge-COPY-t.
5. Non-root-User `kmo` wird erstellt.

**Zeit-Schaetzung:**
- Erst-Build (alle Layer): ~3-5 Min (Image-Pull + apt + pip)
- Inkrementell (Code-Change): <30 Sek (Layer-Cache aktiv)

**Caveats:** Sibling-Module brauchen `requirements.txt` (oder leer, dank `2>/dev/null || true` im Dockerfile). Wenn `requirements.txt` fehlt, baut der Container trotzdem — das ist Phase-5-PARTIAL OK.

### 3.3 Up-Step

```bash
docker compose -f docker-compose.kmo-dev.yml up -d
```

**Was passiert:**
1. Volumes werden erzeugt (`kmo-data`, `kmo-audit`-Bind).
2. Network `kmo-net` wird erzeugt.
3. Alle 6 Services starten parallel (`restart: unless-stopped`).
4. `cloudflared` wartet auf `kmo-gateway: service_healthy`.

### 3.4 Health-Verification

```bash
# Container-Status
docker compose -f docker-compose.kmo-dev.yml ps

# Gateway-Health (lokal)
curl -fsS http://localhost:8081/health
# Erwartung: {"status": "ok", "service": "kmo-gateway-stub"}

# Version
curl -fsS http://localhost:8081/version

# Demo-Page (Basic-Auth)
curl -u martin:change-me http://localhost:8081/demo

# Per-Container-Logs
docker logs kmo-gateway --tail 50
docker logs kmo-approval-gate --tail 20
docker logs kmo-lease-manager --tail 20
docker logs kmo-cloudflared --tail 20
```

**Erwartete Ausgabe (`docker compose ps`):**
```
NAME                   STATUS                   PORTS
kmo-gateway            Up 30 seconds (healthy)  0.0.0.0:8081->8080/tcp
kmo-approval-gate      Up 30 seconds (healthy)
kmo-lease-manager      Up 30 seconds (healthy)
kmo-data-class-filter  Up 30 seconds (healthy)
kmo-saga-engine        Up 30 seconds (healthy)
kmo-outbox             Up 30 seconds (healthy)
kmo-cloudflared        Up 25 seconds            (depends on kmo-gateway)
```

---

## 4. Cloudflare-Tunnel Setup

Public-URL fuer Martin-Remote-Review aus dem Yogamobil. Tunnel terminiert Cloudflare-Edge -> kmo-gateway:8080.

### 4.1 cloudflared installieren

```bash
brew install cloudflared
cloudflared --version
```

### 4.2 Tunnel einrichten

```bash
cd ~/Projects/dark-factories/kmo/dev-stage
bash setup-cloudflared.sh
```

**Was passiert:**
1. Pre-Check: `cloudflared` verfuegbar?
2. Falls `~/.cloudflared/cert.pem` fehlt: **OAuth-Flow** -> Browser oeffnet sich, Domain auswaehlen, einmalig zustimmen.
3. Tunnel `kmo-dev` wird angelegt (idempotent — mehrfaches Ausfuehren OK).
4. Config-File `~/.cloudflared/config.yml` mit Ingress-Rule `kmo-dev.<your-domain>` -> `http://localhost:8080`.
5. Smoke-Test `cloudflared tunnel info kmo-dev`.

**Manuell `KMO_DEV_HOSTNAME` setzen** (falls nicht example.com):
```bash
export KMO_DEV_HOSTNAME=kmo-dev.kemmer-knowledge.io
bash setup-cloudflared.sh
```

### 4.3 Tunnel-Token holen + .env setzen

```bash
# Token holen
cloudflared tunnel token kmo-dev
# Output: ey... (langer JWT-String)

# .env erzeugen aus Vorlage
cp .env.example .env

# .env editieren mit Pflicht-Vars
nano .env
```

`.env`-Inhalt (aus `.env.example`):
```bash
KMO_APPROVAL_SECRET=<32-byte-random-secret>
CLOUDFLARE_TUNNEL_TOKEN=<aus cloudflared tunnel token kmo-dev>
KMO_LOG_LEVEL=DEBUG
KMO_DEMO_AUTH_USER=martin
KMO_DEMO_AUTH_PASS=<starkes-passwort>
KMO_AUDIT_HOST_PATH=/Users/make/Library/CloudStorage/.../branch-hub/audit
```

### 4.4 Stack starten + Tunnel verifizieren

```bash
docker compose -f docker-compose.kmo-dev.yml up -d --build

# Tunnel-Status
cloudflared tunnel info kmo-dev

# Public-URL testen (mit Basic-Auth)
curl -u martin:<pass> https://kmo-dev.<your-domain>/demo
```

---

## 5. Cleanup + Rollback

### 5.1 Compose-Stack stoppen

```bash
# Sanft (Container stop, Daten bleiben)
docker compose -f docker-compose.kmo-dev.yml stop

# Hart (Container weg, Volumes bleiben)
docker compose -f docker-compose.kmo-dev.yml down --remove-orphans

# Alles weg (inkl. Volumes — DATEN VERLOREN!)
docker compose -f docker-compose.kmo-dev.yml down -v --remove-orphans
```

### 5.2 Manuelle Container-Bereinigung

```bash
# Falls compose-down haengt:
docker rm -f kmo-gateway kmo-approval-gate kmo-lease-manager \
              kmo-data-class-filter kmo-saga-engine kmo-outbox kmo-cloudflared

# Network weg
docker network rm dev-stage_kmo-net

# Volumes inspizieren
docker volume ls | grep kmo
docker volume rm dev-stage_kmo-data dev-stage_kmo-audit
```

### 5.3 Rollback-Strategie (1h-State-Restore-Pattern)

Welle-7-Spec definiert ein **1h-State-Restore-Pattern**:

1. **Pre-Action:** Vor jedem Deploy `docker compose ps` + `docker volume ls` Snapshot in `branch-hub/state/` schreiben.
2. **Bei Fehler:** Rollback durch:
   - `docker compose down --remove-orphans`
   - Letzte gute Image-Tags retaggen (`docker tag kmo-gateway:rollback kmo-gateway:latest`)
   - `docker compose up -d` (neuer Up-Step)
3. **Verifizierung:** Healthcheck + E2E-Smoke-Test (`pytest tests/test_pre3_e2e_full_pipeline.py -v`)
4. **Audit-Log:** action-log.jsonl-Eintrag mit `{action: "DEPLOY_ROLLBACK", rationale: "...", target_version: "..."}`.

**Rollback-Ziel-Latenz:** <5 Min vom Fehler-Detect bis Funktional-State.

---

## 6. Production-Migration-Pfad

Wenn Mac-Local nicht reicht (Lambda steigt, Always-On, Multi-User):

| Schritt | Beschreibung | Tool |
|---------|--------------|------|
| 1 | Cloud-DEV-Switch | Fly.io / Railway / Render mit gleichem `docker-compose.kmo-dev.yml` |
| 2 | Secrets-Migration | Cloud-Secret-Manager statt `.env` |
| 3 | Public-URL | Cloud-Provider-URL ODER Cloudflare-Tunnel weiter (Zero-Trust) |
| 4 | Healthcheck-Hardening | Echte Patch-Endpoints statt `python -c "import sys"` |
| 5 | Gateway-Ent-Stub | FastAPI/uvicorn statt `kmo_gateway_stub.py` (siehe `requirements.txt`) |
| 6 | K_0-Schutz | Pre-Action-Verification-Pflicht aktivieren (`~/.claude/rules/df-akzeptanz-kriterien.md` K13) |

---

## 7. Troubleshooting

### Port-Konflikt (8081 belegt)
```bash
lsof -nP -iTCP:8081 -sTCP:LISTEN
# Output: <pid> <process>
# Loesung: Override in docker-compose: ports: - "9999:8080"
```

### Tunnel-Auth-Expiry (~24h)
```bash
cloudflared tunnel token kmo-dev   # Neu generieren
# .env aktualisieren
docker compose restart cloudflared
```

### Docker-Build-Failure (deps fehlen)
```bash
docker compose -f docker-compose.kmo-dev.yml build --no-cache 2>&1 | tee build.log
grep -E "ERROR|fail" build.log
```

### Container Unhealthy (kein /health)
```bash
docker logs kmo-gateway --tail 100
# Stub-Server-Crash? PYTHONPATH falsch? AUDIT_DIR-Mount fehlend?
docker exec -it kmo-gateway python -c "import os; print(os.listdir('/app'))"
```

### Drive-Mount-Problem (kmo-audit empty)
```bash
# Bind-Path muss existieren auf Host
ls -la "$KMO_AUDIT_HOST_PATH"

# Wenn fehlt: Drive-Sync warten oder Path korrigieren in .env
```

---

[CRUX-MK]
