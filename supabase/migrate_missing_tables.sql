-- Mevcut Supabase'e JSON odds modeli + eksik tablolar
-- SQL Editor → Run (bir kez)
-- Not: eski selections_current / quote_changes varsa kalır ama worker artık yazmaz.

ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS markets_json jsonb,
  ADD COLUMN IF NOT EXISTS markets_hash text,
  ADD COLUMN IF NOT EXISTS odds_updated_at text;

CREATE TABLE IF NOT EXISTS public.event_odds_history (
  id bigserial NOT NULL,
  event_id text NOT NULL,
  source text NOT NULL,
  markets_json jsonb NOT NULL,
  markets_hash text NOT NULL,
  change_type text NOT NULL,
  selection_count integer NOT NULL DEFAULT 0,
  captured_at text NOT NULL,
  CONSTRAINT event_odds_history_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.score_changes (
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

CREATE TABLE IF NOT EXISTS public.poll_runs (
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

CREATE INDEX IF NOT EXISTS idx_event_odds_history_event_time
  ON public.event_odds_history(event_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_score_changes_event_time
    ON public.score_changes(event_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_events_source_kickoff
    ON public.events(source, kickoff_at);

GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload schema';
