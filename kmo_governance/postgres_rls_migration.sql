-- [CRUX-MK]
-- KMO-vNext Postgres-RLS Migration V1 (Welle-37 Phase-30)
--
-- Multi-Tenant-Isolation via Row-Level-Security (RLS) Policies.
-- Per `~/.claude/skills/postgres-rls-sandbox-pilot-pattern/SKILL.md`.
-- Per `rules/env-var-gated-real-integration-default.md`:
--   ENV-VAR-gated, default-disabled, requires PHRONESIS_TICKET.
--
-- Aktivierung in Production:
--   ENV: DB_PROVIDER_VERTRAG=true + DB_TENANT_RLS_ACTIVE=true
--   PHRONESIS_TICKET: PT-2026-XX-XX-NNN

-- =============================================================================
-- PART 1: Tenant-Tabelle (Master)
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- KMO-spezifisch:
    domain TEXT NOT NULL CHECK (domain IN ('hotel', 'kpm', 'verlag', 'familien', '9dots', 'heylou_ota')),
    activation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        activation_status IN ('pending', 'active', 'paused', 'archived')
    ),
    phronesis_ticket TEXT  -- per env-var-gated-rule, NULL bei pending
);

-- =============================================================================
-- PART 2: Audit-Events Tabelle (mit RLS)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    event_type TEXT NOT NULL,
    event_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Hash-Chain (per rules/external-anchor-requirement-audit-logs.md):
    chain_hash TEXT NOT NULL,
    prev_hash TEXT,
    -- RFC3161-Anker (optional, bei Real-Production):
    rfc3161_token BYTEA
);

-- Indizes fuer Query-Performance:
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_created
    ON audit_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_event_type
    ON audit_events(event_type);

-- =============================================================================
-- PART 3: Trades Tabelle (KPM-Domain, mit RLS)
-- =============================================================================

CREATE TABLE IF NOT EXISTS kpm_trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    instrument_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    quantity NUMERIC(18, 8) NOT NULL CHECK (quantity > 0),
    price NUMERIC(18, 8) NOT NULL CHECK (price > 0),
    strategy_id TEXT NOT NULL,
    decision_path TEXT[] NOT NULL,
    success BOOLEAN NOT NULL,
    elapsed_ms NUMERIC(10, 2) NOT NULL CHECK (elapsed_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kpm_trades_tenant_strategy
    ON kpm_trades(tenant_id, strategy_id);

-- =============================================================================
-- PART 4: RLS-Aktivierung
-- =============================================================================

-- Enable RLS auf allen Multi-Tenant-Tabellen
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpm_trades ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- PART 5: RLS-Policies
-- =============================================================================

-- audit_events: nur eigener Tenant lesbar (READ + INSERT)
CREATE POLICY tenant_isolation_audit_events ON audit_events
    FOR ALL
    TO PUBLIC
    USING (tenant_id = current_setting('kmo.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('kmo.tenant_id', true));

-- kpm_trades: nur eigener Tenant lesbar (READ + INSERT)
CREATE POLICY tenant_isolation_kpm_trades ON kpm_trades
    FOR ALL
    TO PUBLIC
    USING (tenant_id = current_setting('kmo.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('kmo.tenant_id', true));

-- =============================================================================
-- PART 6: Tenant-Context-Setter (per set-local-tenant-context-pattern)
-- =============================================================================

-- Per ~/.claude/skills/set-local-tenant-context-pattern/SKILL.md:
-- SET LOCAL (NICHT SET) verhindert Tenant-Leak bei Connection-Reuse.
--
-- Application-Side Pattern (Python):
--   conn.execute("SET LOCAL kmo.tenant_id = %s", (tenant_id,))
--   # Within transaction: only this tenant's rows visible
--   conn.execute("COMMIT")  # Resets kmo.tenant_id automatically

-- =============================================================================
-- PART 7: Audit-Hash-Chain Trigger (per external-anchor-requirement)
-- =============================================================================

CREATE OR REPLACE FUNCTION compute_audit_chain_hash()
RETURNS TRIGGER AS $$
DECLARE
    last_hash TEXT;
BEGIN
    -- Find last chain_hash for this tenant
    SELECT chain_hash INTO last_hash
    FROM audit_events
    WHERE tenant_id = NEW.tenant_id
    ORDER BY created_at DESC
    LIMIT 1;

    NEW.prev_hash := COALESCE(last_hash, '');
    NEW.chain_hash := encode(
        sha256(
            (NEW.prev_hash || NEW.event_type || NEW.event_data::text || NEW.created_at::text)::bytea
        ),
        'hex'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_chain_hash
    BEFORE INSERT ON audit_events
    FOR EACH ROW
    EXECUTE FUNCTION compute_audit_chain_hash();

-- =============================================================================
-- PART 8: Verification-Queries (Manual-Audit-Hilfsmittel)
-- =============================================================================

-- Verify RLS is active:
--   SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('audit_events', 'kpm_trades');
--   -- Should return: rls=t

-- Verify tenant-isolation (negative-test):
--   SET LOCAL kmo.tenant_id = 'tenant_a';
--   INSERT INTO audit_events (tenant_id, event_type, event_data) VALUES ('tenant_a', 'test', '{}');
--   SET LOCAL kmo.tenant_id = 'tenant_b';
--   SELECT COUNT(*) FROM audit_events;  -- MUST return 0 (tenant_a-row not visible)

-- Verify chain-integrity:
--   SELECT event_id, chain_hash, prev_hash FROM audit_events WHERE tenant_id = 'tenant_a' ORDER BY created_at;
--   -- Each prev_hash should match previous row's chain_hash

-- =============================================================================
-- CRUX-MK
-- =============================================================================
