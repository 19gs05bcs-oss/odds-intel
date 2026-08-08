-- Phase 1 schema: events, current quotes, change-only history, scores

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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_event_id)
);

CREATE TABLE IF NOT EXISTS selections_current (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id),
    source TEXT NOT NULL,
    market_name TEXT NOT NULL,
    market_key TEXT NOT NULL,
    selection_name TEXT NOT NULL,
    selection_key TEXT NOT NULL,
    odds REAL,
    is_suspended INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_changed_at TEXT NOT NULL,
    opening_odds REAL,
    UNIQUE (event_id, market_key, selection_key)
);

CREATE TABLE IF NOT EXISTS quote_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    selection_id TEXT NOT NULL,
    source TEXT NOT NULL,
    market_key TEXT NOT NULL,
    selection_key TEXT NOT NULL,
    odds REAL,
    prev_odds REAL,
    is_suspended INTEGER NOT NULL DEFAULT 0,
    change_type TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quote_changes_event_time
    ON quote_changes(event_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_quote_changes_selection_time
    ON quote_changes(selection_id, captured_at);

CREATE TABLE IF NOT EXISTS score_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    fixtures_polled INTEGER NOT NULL DEFAULT 0,
    quote_changes INTEGER NOT NULL DEFAULT 0,
    score_changes INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
