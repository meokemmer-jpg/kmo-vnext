-- KMO Cell-Boundary Audit Schema [CRUX-MK]
-- Used by BoundaryAuditLog (boundary_audit.py).
-- Inline-fallback exists in Python; this file is canonical.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS boundary_events (
    event_id TEXT PRIMARY KEY,
    cell_id TEXT NOT NULL,
    hotel_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_subtype TEXT,
    timestamp REAL NOT NULL,
    payload_hash TEXT,
    details_json TEXT,
    machine_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_boundary_events_hotel
    ON boundary_events (hotel_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_boundary_events_cell
    ON boundary_events (cell_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_boundary_events_type
    ON boundary_events (event_type, timestamp);
