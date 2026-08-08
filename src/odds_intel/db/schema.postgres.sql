-- Run once in Supabase SQL Editor (or via: odds-intel migrate)
-- Events hold current markets_json; event_odds_history stores change-only snapshots

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    sport TEXT,
    competition TEXT,
    home_team TEXT,
    away_team TEXT,
    kickoff_at TEXT,
    status TEXT,
    opening_captured_at TEXT,
    closing_captured_at TEXT,
    is_closed INTEGER NOT NULL DEFAULT 0,
    markets_json jsonb,
    markets_hash TEXT,
    odds_updated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_event_id)
);

CREATE TABLE IF NOT EXISTS event_odds_history (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    source TEXT NOT NULL,
    markets_json jsonb NOT NULL,
    markets_hash TEXT NOT NULL,
    change_type TEXT NOT NULL,
    selection_count INTEGER NOT NULL DEFAULT 0,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_odds_history_event_time
    ON event_odds_history(event_id, captured_at);

CREATE TABLE IF NOT EXISTS score_changes (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    source TEXT NOT NULL,
    period TEXT,
    home_score INTEGER,
    away_score INTEGER,
    clock TEXT,
    stage TEXT,
    is_final INTEGER NOT NULL DEFAULT 0,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_score_changes_event_time
    ON score_changes(event_id, captured_at);

CREATE TABLE IF NOT EXISTS poll_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    fixtures_polled INTEGER NOT NULL DEFAULT 0,
    quote_changes INTEGER NOT NULL DEFAULT 0,
    score_changes INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_source_kickoff
    ON events(source, kickoff_at);

GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload schema';
