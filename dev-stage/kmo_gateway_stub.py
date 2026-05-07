"""
KMO Gateway Stub [CRUX-MK]

Placeholder HTTP server for KMO DEV-Stage. Exposes /health, /version, /demo.
Demo-Page reads latest action-log entries from mounted audit volume to show
status of the 5 KMO patches (approval-gate, lease-manager, data-class-filter,
saga-pattern, outbox-pattern).

NOT FOR PRODUCTION. Stdlib only -- no auth beyond basic-auth on /demo.
Spec: branch-hub/blueprints/SPEC-KMO-DEV-STAGE-CLOUDFLARE-DOCKER-2026-04-30.md
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "0.1.0-dev-stub"
PORT = int(os.environ.get("KMO_GATEWAY_PORT", "8080"))
AUDIT_DIR = Path(os.environ.get("KMO_AUDIT_DIR", "/app/audit"))
LOG_LEVEL = os.environ.get("KMO_LOG_LEVEL", "INFO").upper()
DEMO_USER = os.environ.get("KMO_DEMO_AUTH_USER", "martin")
DEMO_PASS = os.environ.get("KMO_DEMO_AUTH_PASS", "change-me")

KMO_PATCHES = [
    "approval-gate",
    "lease-manager",
    "data-class-filter",
    "saga-pattern",
    "outbox-pattern",
]

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("kmo-gateway-stub")


def read_last_action_log_entry() -> dict[str, Any] | None:
    """Read last line of action-log.jsonl (read-only mount). Returns None on miss."""
    candidate = AUDIT_DIR / "action-log.jsonl"
    if not candidate.exists():
        return None
    try:
        with candidate.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            block = min(size, 4096)
            fh.seek(max(0, size - block))
            tail = fh.read().decode("utf-8", errors="replace")
        last_line = tail.strip().splitlines()[-1] if tail.strip() else ""
        return json.loads(last_line) if last_line else None
    except (OSError, ValueError) as exc:
        log.warning("audit-log read failed: %s", exc)
        return None


def patch_status_block() -> str:
    """Render HTML rows for the 5 KMO patches with stub status."""
    last = read_last_action_log_entry()
    last_ts = html.escape(last.get("ts", "n/a")) if last else "n/a"
    rows = []
    for patch in KMO_PATCHES:
        rows.append(
            f"<tr><td>{html.escape(patch)}</td>"
            f"<td>STUB-OK</td>"
            f"<td>{last_ts}</td></tr>"
        )
    return "\n".join(rows)


def basic_auth_ok(header_value: str | None) -> bool:
    if not header_value or not header_value.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header_value[6:]).decode("utf-8")
        user, _, pwd = decoded.partition(":")
        return user == DEMO_USER and pwd == DEMO_PASS
    except (ValueError, UnicodeDecodeError):
        return False


class StubHandler(BaseHTTPRequestHandler):
    server_version = f"KMO-Gateway-Stub/{VERSION}"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_auth_challenge(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="kmo-dev-stage"')
        self.end_headers()
        self.wfile.write(b"401 Unauthorized")

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok", "service": "kmo-gateway-stub"})
            return
        if self.path == "/version":
            self._send_json({
                "version": VERSION,
                "service": "kmo-gateway-stub",
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return
        if self.path == "/demo":
            if not basic_auth_ok(self.headers.get("Authorization")):
                self._send_auth_challenge()
                return
            page = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>KMO DEV-Stage Demo</title>"
                "<style>body{font-family:sans-serif;margin:2em;max-width:800px}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{border:1px solid #ccc;padding:.5em;text-align:left}"
                "th{background:#f0f0f0}</style></head><body>"
                "<h1>KMO DEV-Stage Status [CRUX-MK]</h1>"
                "<p><strong>Stage:</strong> DEV (stub). NOT FOR PRODUCTION.</p>"
                "<table><thead><tr><th>Patch</th><th>Status</th>"
                "<th>Last action-log ts</th></tr></thead><tbody>"
                f"{patch_status_block()}"
                "</tbody></table>"
                f"<p><small>Version {html.escape(VERSION)} -- "
                f"{html.escape(datetime.now(timezone.utc).isoformat())}</small></p>"
                "</body></html>"
            )
            self._send_html(page)
            return
        self._send_json({"error": "not_found", "path": self.path}, status=404)


def main() -> int:
    log.info("kmo-gateway-stub %s starting on :%d", VERSION, PORT)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), StubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutdown requested")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
