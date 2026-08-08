from __future__ import annotations

import json
from pathlib import Path

from odds_intel.config import Settings
from odds_intel.db.connection import connect, migrate
from odds_intel.db.repo import Repository
from odds_intel.sources.bwin.parse import parse_fixture_view

SAMPLE = {
    "fixture": {
        "id": "2:9990001",
        "startDate": "2026-08-08T18:00:00Z",
        "stage": "PreMatch",
        "sport": {"name": {"value": "Soccer"}},
        "competition": {"name": {"value": "England - Premier League"}},
        "participants": [
            {"name": {"value": "Arsenal"}, "type": "Home", "score": None},
            {"name": {"value": "Coventry City"}, "type": "Away", "score": None},
        ],
        "scoreboard": {"score": "0:0", "period": "NotStarted", "stage": "PreMatch"},
        "optionMarkets": [
            {
                "name": {"value": "Match Result"},
                "options": [
                    {"name": {"value": "Arsenal"}, "price": {"odds": 1.40}},
                    {"name": {"value": "X"}, "price": {"odds": 4.50}},
                    {"name": {"value": "Coventry City"}, "price": {"odds": 8.00}},
                ],
            },
            {
                "name": {"value": "Multi Goal"},
                "options": [
                    {"name": {"value": "1-2 Yes"}, "price": {"odds": 2.50}},
                    {"name": {"value": "1-2 No"}, "price": {"odds": 1.00}},
                ],
            },
        ],
    }
}


def test_parse_and_change_only(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 't.db'}"
    settings = Settings(database_url=db_url, bwin_access_id="test")
    db = connect(settings)
    migrate(db, settings)
    repo = Repository(db)

    event, quotes, score = parse_fixture_view(SAMPLE)
    assert event is not None
    assert event.home_team == "Arsenal"
    assert len(quotes) >= 3
    assert score is not None

    repo.upsert_event(event)
    c1 = repo.apply_quotes(quotes)
    assert c1 == 1  # one event blob (opening)
    assert repo.apply_score(score) is True

    # second identical poll → no quote/score changes
    c2 = repo.apply_quotes(quotes)
    assert c2 == 0
    assert repo.apply_score(score) is False

    # odds move on home win
    moved = json.loads(json.dumps(SAMPLE))
    moved["fixture"]["optionMarkets"][0]["options"][0]["price"]["odds"] = 1.33
    event2, quotes2, _ = parse_fixture_view(moved)
    assert event2 is not None
    c3 = repo.apply_quotes(quotes2)
    assert c3 == 1

    history = repo.quote_history(event.id, limit=10)
    types = [h["change_type"] if isinstance(h, dict) else h["change_type"] for h in history]
    assert "opening" in types
    assert "update" in types
    latest = repo.latest_quotes(event.id)
    assert any(r.get("odds") == 1.33 for r in latest)

    # final score
    finished = json.loads(json.dumps(SAMPLE))
    finished["fixture"]["stage"] = "Finished"
    finished["fixture"]["scoreboard"] = {
        "score": "3:1",
        "period": "Finished",
        "stage": "Finished",
    }
    _, _, score_final = parse_fixture_view(finished)
    assert score_final is not None and score_final.is_final
    assert repo.apply_score(score_final) is True

    rows = db.fetches("SELECT is_closed, closing_captured_at FROM events WHERE id = ?", (event.id,))
    row = rows[0]
    closed = row["is_closed"] if not isinstance(row, dict) else row["is_closed"]
    assert int(closed) == 1
    db.close()
