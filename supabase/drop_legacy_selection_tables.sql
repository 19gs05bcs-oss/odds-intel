-- Eski satır-satır model: artık kullanılmıyor
-- Supabase SQL Editor → Run
-- Yeni veri: events.markets_json + event_odds_history

DROP TABLE IF EXISTS public.quote_changes CASCADE;
DROP TABLE IF EXISTS public.selections_current CASCADE;
