# KMO DEV-Stage [CRUX-MK]

Mac-Local KMO Development Stack mit Cloudflare-Tunnel-Public-URL fuer Martin-Remote-Review.

**Architektur:** Option C aus `branch-hub/blueprints/SPEC-KMO-DEV-STAGE-CLOUDFLARE-DOCKER-2026-04-30.md` (Mac-Local Docker + Cloudflare-Tunnel). DEV-Stage, NICHT FUER PRODUCTION. K_0/Q_0-relevante Daten gehoeren NIE in diesen Stack.

## Use-Case

- 5 KMO-Patches (approval-gate, lease-manager, data-class-filter, saga-pattern, outbox-pattern) lokal containerisiert.
- Gateway-Stub auf Port 8080 mit `/health`, `/version`, `/demo`-Endpoints.
- Cloudflare Tunnel exponiert `/demo` auf Public-URL fuer Martin-Review aus dem Yogamobil oder unterwegs.
- Demo-Page liest letzten action-log-Eintrag aus `branch-hub/audit/` (read-only mount).

## Setup (5 Schritte)

1. **cloudflared installieren** (einmalig):
   ```bash
   brew install cloudflared
   ```

2. **Tunnel einrichten:**
   ```bash
   cd /Users/make/Projects/dark-factories/kmo/dev-stage
   bash setup-cloudflared.sh
   ```
   Login-Browser oeffnet sich. Domain auswaehlen, dann Token holen:
   ```bash
   cloudflared tunnel token kmo-dev
   ```

3. **`.env` erzeugen:**
   ```bash
   cp .env.example .env
   # Editiere .env -- CLOUDFLARE_TUNNEL_TOKEN, KMO_APPROVAL_SECRET, KMO_DEMO_AUTH_PASS setzen.
   ```

4. **Stack starten:**
   ```bash
   docker compose -f docker-compose.kmo-dev.yml up -d --build
   ```

5. **Verify + URL teilen:**
   ```bash
   curl -fsS http://localhost:8080/health
   docker compose -f docker-compose.kmo-dev.yml ps
   # Demo-URL = https://${KMO_DEV_HOSTNAME aus setup-cloudflared.sh}/demo
   # Basic-Auth: KMO_DEMO_AUTH_USER / KMO_DEMO_AUTH_PASS aus .env.
   ```

## Troubleshooting

- **Port 8080 belegt:** `lsof -nP -iTCP:8080 -sTCP:LISTEN` -- Konflikt-Service stoppen oder Port in `docker-compose.kmo-dev.yml` aendern.
- **Tunnel-Auth-Expiry (~24h):** Token regenerieren mit `cloudflared tunnel token kmo-dev`, `.env` aktualisieren, `docker compose restart cloudflared`.
- **Docker-Build-Failure (deps fehlen):** `docker compose -f docker-compose.kmo-dev.yml build --no-cache` und Logs pruefen. Sibling-Module muessen `requirements.txt` + `Dockerfile` haben (Phase-5 PARTIAL bei einzelnen Patches OK).

## Production-Migration-Plan

Wenn Mac-Local nicht reicht (Lambda steigt, Always-On-Anforderung, Multi-User-Demo):

1. Cloud-DEV-Switch auf Fly.io / Railway / Render mit gleichem `docker-compose.kmo-dev.yml` als Basis.
2. Secrets ueber Cloud-Secret-Manager statt `.env`.
3. Cloudflare-Tunnel ersetzt durch Cloud-Provider-Public-URL (oder Tunnel beibehalten fuer Zero-Trust).
4. Healthchecks haerten (echte Patch-Endpoints statt `python -c "import sys"`).
5. Ent-Stub-en: `kmo_gateway_stub.py` durch echten Gateway ersetzen (FastAPI/uvicorn, vgl. `requirements.txt`).
6. K_0/Q_0-Pre-Action-Verification-Pflicht aktivieren (siehe `~/.claude/rules/df-akzeptanz-kriterien.md` K13).

## Status

- **Stage:** DEV (stub).
- **Cross-LLM-Review-Pending:** Code-Quality, docker-compose Build-Test (Architekt-spaeter).
- **Spec:** `branch-hub/blueprints/SPEC-KMO-DEV-STAGE-CLOUDFLARE-DOCKER-2026-04-30.md`.

[CRUX-MK]
