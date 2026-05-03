"""CRUX-MK SQLite schema for DF-89 knowledge state."""

KNOWLEDGE_DB_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS methodik_catalog (
    claim_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('candidate','contested','canonical','deprecated','candidate-outlier')),
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    decay_score REAL NOT NULL DEFAULT 1.0,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS paper_index (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    venue TEXT NOT NULL,
    authors_json TEXT NOT NULL,
    citation_count INTEGER NOT NULL,
    year INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    abstract TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS convergence_patterns (
    pattern_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    supporting_papers_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS failure_memory (
    failure_id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    reason TEXT NOT NULL,
    dead_link INTEGER NOT NULL DEFAULT 0,
    auth_walled_domain INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS claim_relations (
    rel_id TEXT PRIMARY KEY,
    source_claim_id TEXT NOT NULL,
    target_claim_id TEXT NOT NULL,
    rel_type TEXT NOT NULL CHECK(rel_type IN ('supports','contradicts','supersedes')),
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS source_independence (
    source_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES paper_index(paper_id),
    venue_cluster TEXT NOT NULL,
    author_cluster TEXT NOT NULL,
    citation_cluster TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_methodik_status ON methodik_catalog(status);
CREATE INDEX IF NOT EXISTS idx_patterns_topic ON convergence_patterns(topic);
CREATE INDEX IF NOT EXISTS idx_papers_source_url ON paper_index(source_url);
CREATE INDEX IF NOT EXISTS idx_methodik_expires ON methodik_catalog(expires_at);
CREATE INDEX IF NOT EXISTS idx_papers_expires ON paper_index(expires_at);
CREATE INDEX IF NOT EXISTS idx_patterns_expires ON convergence_patterns(expires_at);
"""
