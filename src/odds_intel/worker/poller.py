from __future__ import annotations

import logging
import time
from typing import Optional

from odds_intel.config import Settings, get_settings
from odds_intel.db.factory import create_repository
from odds_intel.sources.bwin import BwinClient, SOURCE, parse_fixture_view

logger = logging.getLogger(__name__)


def resolve_fixture_ids(settings: Settings, client: BwinClient) -> list[str]:
    explicit = settings.fixture_id_list()
    if explicit:
        return explicit
    ids: list[str] = []
    for sport_id in settings.sport_id_list():
        try:
            found = client.list_fixtures(sport_id, max_fixtures=settings.bwin_max_fixtures)
            logger.info("sport %s discovered %s fixtures", sport_id, len(found))
            ids.extend(found)
        except Exception:
            logger.exception("failed listing fixtures for sport %s", sport_id)
    seen: set[str] = set()
    out: list[str] = []
    for fid in ids:
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out[: settings.bwin_max_fixtures]


def poll_once(settings: Optional[Settings] = None) -> dict[str, int]:
    settings = settings or get_settings()
    repo, closable = create_repository(settings)
    run_id = repo.start_poll_run(SOURCE)

    fixtures_polled = 0
    quote_changes = 0
    score_changes = 0
    error_count = 0

    try:
        with BwinClient(settings) as client:
            fixture_ids = resolve_fixture_ids(settings, client)
            if not fixture_ids:
                logger.warning("no fixture ids to poll; set BWIN_FIXTURE_IDS or discovery")
            for fixture_id in fixture_ids:
                try:
                    payload = client.fixture_view(fixture_id)
                    event, quotes, score = parse_fixture_view(payload)
                    if not event:
                        logger.warning("could not parse fixture %s", fixture_id)
                        error_count += 1
                        continue
                    repo.upsert_event(event)
                    quote_changes += repo.apply_quotes(quotes)
                    if score and repo.apply_score(score):
                        score_changes += 1
                    stage = (event.status or "").lower()
                    if not quotes and any(t in stage for t in ("finished", "ended", "closed")):
                        repo.mark_event_closed(event.id, event.status or "Closed")
                    fixtures_polled += 1
                    logger.info(
                        "polled %s (%s vs %s) quotes=%s",
                        event.source_event_id,
                        event.home_team,
                        event.away_team,
                        len(quotes),
                    )
                except Exception:
                    error_count += 1
                    logger.exception("fixture poll failed: %s", fixture_id)
    finally:
        repo.finish_poll_run(
            run_id,
            fixtures_polled=fixtures_polled,
            quote_changes=quote_changes,
            score_changes=score_changes,
            error_count=error_count,
        )
        if closable is not None:
            closable.close()

    summary = {
        "fixtures_polled": fixtures_polled,
        "quote_changes": quote_changes,
        "score_changes": score_changes,
        "error_count": error_count,
    }
    logger.info("poll complete: %s", summary)
    return summary


def run_forever(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    backend = "supabase-rest" if settings.uses_supabase_rest else settings.database_url
    logger.info(
        "starting bwin poller interval=%ss backend=%s",
        settings.poll_interval_sec,
        backend,
    )
    while True:
        started = time.time()
        try:
            poll_once(settings)
        except Exception:
            logger.exception("poll_once crashed")
        elapsed = time.time() - started
        sleep_for = max(1.0, settings.poll_interval_sec - elapsed)
        time.sleep(sleep_for)
