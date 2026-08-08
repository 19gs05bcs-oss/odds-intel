-- Tüm odds verisini temizle (şema kalır)
-- Supabase SQL Editor → Run

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'event_odds_history',
    'score_changes',
    'poll_runs',
    'quote_changes',
    'selections_current',
    'events'
  ]
  LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('TRUNCATE TABLE public.%I RESTART IDENTITY CASCADE', t);
    END IF;
  END LOOP;
END $$;
