-- Oranları satır satır yerine events üzerinde tek JSON + değişince history
-- Supabase SQL Editor → Run

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

CREATE INDEX IF NOT EXISTS idx_event_odds_history_event_time
  ON public.event_odds_history(event_id, captured_at);

GRANT ALL ON TABLE public.event_odds_history TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload schema';
