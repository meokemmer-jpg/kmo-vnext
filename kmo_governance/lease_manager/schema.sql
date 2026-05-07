-- KMO Lease Manager SQLite Schema [CRUX-MK]
-- KMO-Patch P-KMO-A1: Resource-Lease-System
-- Atomic lease acquisition via UNIQUE-Constraint + ON CONFLICT IGNORE.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leases (
    lease_id        TEXT PRIMARY KEY,            -- UUID4
    resource_type   TEXT NOT NULL,               -- DF | PORT | API_TOKEN | DRIVE_PATH | TUNNEL_SUBDOMAIN
    resource_id     TEXT NOT NULL,               -- e.g. "df-86", "8080", "drive:/path/x"
    holder          TEXT NOT NULL,               -- e.g. "mac.df-86.engine.pid-12345"
    acquired_at     REAL NOT NULL,               -- unix timestamp
    expires_at      REAL NOT NULL,               -- unix timestamp (acquired_at + ttl)
    last_heartbeat  REAL NOT NULL,               -- unix timestamp, refreshed via heartbeat()
    metadata_json   TEXT                         -- optional JSON blob (caller-defined)
);

-- Atomic-Acquire-Constraint: Nur ein aktiver Lease pro (resource_type, resource_id)
-- ON CONFLICT IGNORE auf INSERT macht die Akquise idempotent + race-frei.
CREATE UNIQUE INDEX IF NOT EXISTS idx_leases_resource_unique
    ON leases (resource_type, resource_id);

-- Stale-Cleanup-Index: schnelle Suche nach abgelaufenen Leases
CREATE INDEX IF NOT EXISTS idx_leases_expires_at
    ON leases (expires_at);

-- Holder-Reverse-Lookup (Diagnostik / "welche Leases haelt Holder X?")
CREATE INDEX IF NOT EXISTS idx_leases_holder
    ON leases (holder);
