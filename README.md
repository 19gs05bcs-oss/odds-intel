# odds-intel

Phase 1: **Bwin** collector that runs continuously (Koyeb worker), stores **opening → change-only history → closing**, and captures **scoreboard/result** fields when Bwin exposes them.

## Maç sonuçları — Bwin verir mi?

**Kısmen evet — ama tek başına arşiv kaynağı değil.**

| İhtiyaç | Bwin `cds-api` | Not |
|---|---|---|
| Canlı skor | Evet | `fixture-view?scoreboardMode=Full` + live highlights |
| Bitmiş maç skoru | Evet (pencere içinde) | Fixture hâlâ API’de iken `stage=Finished` yakalanmalı |
| Market settlement (hangi seçenek kazandı) | Bazen | Offer kapanınca fixture kaybolabiliyor |
| Tarihsel sonuç arşivi | Hayır / zayıf | Bitmiş maçlar katalogdan düşer |

**Faz 1 stratejisi:** skoru Bwin’den change-only olarak yaz (`score_changes`). Fixture kaybolmadan `is_final` yakala.

**Faz 1.5 (sonraki):** settled market + kaçan maçlar için ikinci kaynak (API-Football / football-data.org vb.). Şimdilik ekstra provider şart değil; skor için Bwin yeterli başlangıç, settlement güvenilirliği için sonra eklenir.

## Change-only model

- **Opening:** selection ilk görüldüğünde `quote_changes.change_type = opening`
- **Ara hareket:** odds veya suspend değişince tek satır
- **Değişim yok:** sadece `last_seen_at` güncellenir (history şişmez)
- **Closing:** skor `is_final` veya event closed → `events.closing_captured_at`

## Storage: Supabase (Koyeb env = acoreapi stili)

Production yazımı **PostgREST** üzerinden:

```bash
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=sb_secret_...   # service_role / secret (anon değil)
```

1. Supabase proje aç  
2. **SQL Editor** → `supabase/schema.sql` çalıştır (bir kez)  
3. Koyeb worker’a `SUPABASE_URL`, `SUPABASE_KEY`, `BWIN_ACCESS_ID` ekle  

Tablolar: `events`, `selections_current`, `quote_changes`, `score_changes`, `poll_runs`

## Quick start (local → Supabase)

```bash
cd ~/Projects/odds-intel
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# fill DATABASE_URL (Supabase) + BWIN_ACCESS_ID + BWIN_FIXTURE_IDS
odds-intel migrate
odds-intel poll-once
odds-intel worker
```

Offline (EC2’deki JSON ile, yine Supabase’e yazar):

```bash
odds-intel ingest-file ./bwin_offers.json
odds-intel show-event bwin:2:7823441
```

## Koyeb

Env (acoreapi gibi):

| Key | Değer |
|---|---|
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | service_role / secret |
| `BWIN_ACCESS_ID` | Bwin `x-bwin-accessid` |
| `BWIN_FIXTURE_IDS` | başlangıçta dar tut |

Service type: **Worker**, CMD: `odds-intel worker`  
Repo’da `src/` klasörü olmak zorunda (Docker `COPY src ./src`).

## Useful endpoints (from your HAR)

- `GET /cds-api/bettingoffer/fixtures?sportIds=4`
- `GET /cds-api/bettingoffer/fixture-view?fixtureIds=...&scoreboardMode=Full`
- `GET /cds-api/bettingoffer/live/highlights` (live later)

## Phase 1 status

- [x] Canonical store + change-only quotes
- [x] Bwin fixture-view client/parser
- [x] Score change capture + final flag
- [x] Continuous worker + Docker/Koyeb stubs
- [ ] Live highlights poller
- [ ] Second results provider for settlement backfill
- [ ] Unibet / Nesine adapters
