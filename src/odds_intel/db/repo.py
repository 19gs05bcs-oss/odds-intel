from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from odds_intel.db.markets_blob import (
    build_markets_blob,
    flatten_markets_blob,
    group_quotes_by_event,
)
from odds_intel.models import EventSnapshot, ScoreSnapshot, SelectionQuote


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_get(row: Any, key: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[key]


class Repository:
    def __init__(self, db: Any) -> None:
        self.db = db

    def start_poll_run(self, source: str) -> int:
        now = _utcnow()
        # Prefer RETURNING for postgres; sqlite 3.35+ also supports it.
        try:
            rows = self.db.fetches(
                "INSERT INTO poll_runs(source, started_at) VALUES (?, ?) RETURNING id",
                (source, now),
            )
            self.db.commit()
            return int(_row_get(rows[0], "id"))
        except Exception:
            cur = self.db.execute(
                "INSERT INTO poll_runs(source, started_at) VALUES (?, ?)",
                (source, now),
            )
            row_id = getattr(cur, "lastrowid", None)
            self.db.commit()
            if row_id:
                return int(row_id)
            rows = self.db.fetches(
                "SELECT id FROM poll_runs WHERE source = ? ORDER BY id DESC LIMIT 1",
                (source,),
            )
            return int(_row_get(rows[0], "id"))

    def finish_poll_run(
        self,
        run_id: int,
        *,
        fixtures_polled: int,
        quote_changes: int,
        score_changes: int,
        error_count: int,
        notes: str = "",
    ) -> None:
        self.db.execute(
            """
            UPDATE poll_runs
            SET finished_at = ?, fixtures_polled = ?, quote_changes = ?,
                score_changes = ?, error_count = ?, notes = ?
            WHERE id = ?
            """,
            (
                _utcnow(),
                fixtures_polled,
                quote_changes,
                score_changes,
                error_count,
                notes,
                run_id,
            ),
        )
        self.db.commit()

    def upsert_event(self, event: EventSnapshot) -> None:
        now = _utcnow()
        existing = self.db.fetches(
            "SELECT id, opening_captured_at, is_closed FROM events WHERE id = ?",
            (event.id,),
        )
        if not existing:
            self.db.execute(
                """
                INSERT INTO events(
                    id, source, source_event_id, sport, competition,
                    home_team, away_team, kickoff_at, status,
                    opening_captured_at, is_closed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    event.id,
                    event.source,
                    event.source_event_id,
                    event.sport,
                    event.competition,
                    event.home_team,
                    event.away_team,
                    event.kickoff_at,
                    event.status,
                    now,
                    now,
                    now,
                ),
            )
        else:
            self.db.execute(
                """
                UPDATE events
                SET sport = ?, competition = ?, home_team = ?, away_team = ?,
                    kickoff_at = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    event.sport,
                    event.competition,
                    event.home_team,
                    event.away_team,
                    event.kickoff_at,
                    event.status,
                    now,
                    event.id,
                ),
            )
        self.db.commit()

    def apply_quotes(self, quotes: list[SelectionQuote]) -> int:
        """Store all markets for an event as one JSON blob. History only on change."""
        if not quotes:
            return 0
        now = _utcnow()
        changes = 0
        for event_id, event_quotes in group_quotes_by_event(quotes).items():
            blob, digest, selection_count = build_markets_blob(event_quotes)
            source = event_quotes[0].source
            rows = self.db.fetches(
                "SELECT markets_hash FROM events WHERE id = ?",
                (event_id,),
            )
            prev_hash = _row_get(rows[0], "markets_hash") if rows else None
            if prev_hash == digest:
                self.db.execute(
                    "UPDATE events SET updated_at = ? WHERE id = ?",
                    (now, event_id),
                )
                continue

            change_type = "opening" if not prev_hash else "update"
            payload = json.dumps(blob, ensure_ascii=False)
            self.db.execute(
                """
                UPDATE events
                SET markets_json = ?, markets_hash = ?, odds_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (payload, digest, now, now, event_id),
            )
            self.db.execute(
                """
                INSERT INTO event_odds_history(
                    event_id, source, markets_json, markets_hash,
                    change_type, selection_count, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    source,
                    payload,
                    digest,
                    change_type,
                    selection_count,
                    now,
                ),
            )
            changes += 1

        self.db.commit()
        return changes

    def apply_score(self, score: ScoreSnapshot) -> bool:
        """Write score row only if it differs from the latest stored snapshot."""
        rows = self.db.fetches(
            """
            SELECT period, home_score, away_score, clock, stage, is_final
            FROM score_changes
            WHERE event_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (score.event_id,),
        )
        if rows:
            prev = rows[0]
            same = (
                _row_get(prev, "period") == score.period
                and _row_get(prev, "home_score") == score.home_score
                and _row_get(prev, "away_score") == score.away_score
                and _row_get(prev, "clock") == score.clock
                and _row_get(prev, "stage") == score.stage
                and bool(_row_get(prev, "is_final")) == score.is_final
            )
            if same:
                return False

        now = _utcnow()
        self.db.execute(
            """
            INSERT INTO score_changes(
                event_id, source, period, home_score, away_score,
                clock, stage, is_final, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                score.event_id,
                score.source,
                score.period,
                score.home_score,
                score.away_score,
                score.clock,
                score.stage,
                int(score.is_final),
                now,
            ),
        )
        if score.is_final:
            self.db.execute(
                """
                UPDATE events
                SET status = ?, closing_captured_at = ?, is_closed = 1, updated_at = ?
                WHERE id = ?
                """,
                (score.stage or "Finished", now, now, score.event_id),
            )
        self.db.commit()
        return True

    def mark_event_closed(self, event_id: str, status: str = "Closed") -> None:
        now = _utcnow()
        self.db.execute(
            """
            UPDATE events
            SET status = ?, closing_captured_at = COALESCE(closing_captured_at, ?),
                is_closed = 1, updated_at = ?
            WHERE id = ? AND is_closed = 0
            """,
            (status, now, now, event_id),
        )
        self.db.commit()

    def latest_quotes(self, event_id: str) -> list[Any]:
        rows = self.db.fetches(
            "SELECT markets_json, odds_updated_at FROM events WHERE id = ?",
            (event_id,),
        )
        if not rows:
            return []
        flat = flatten_markets_blob(_row_get(rows[0], "markets_json"))
        updated = _row_get(rows[0], "odds_updated_at")
        for row in flat:
            row["last_changed_at"] = updated
        return flat

    def quote_history(self, event_id: str, limit: int = 50) -> list[Any]:
        return self.db.fetches(
            """
            SELECT change_type, selection_count, markets_hash, captured_at
            FROM event_odds_history
            WHERE event_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (event_id, limit),
        )
