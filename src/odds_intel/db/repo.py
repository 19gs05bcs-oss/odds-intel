from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

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
        """Persist only real odds/status changes. Returns number of change rows written."""
        if not quotes:
            return 0
        now = _utcnow()
        changes = 0
        for q in quotes:
            if q.odds is not None and q.odds <= 1.001:
                # placeholder / void-looking prices — still track if status flips, else skip noise
                pass

            rows = self.db.fetches(
                "SELECT odds, is_suspended FROM selections_current WHERE id = ?",
                (q.id,),
            )
            if not rows:
                self.db.execute(
                    """
                    INSERT INTO selections_current(
                        id, event_id, source, market_name, market_key,
                        selection_name, selection_key, odds, is_suspended,
                        first_seen_at, last_seen_at, last_changed_at, opening_odds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        q.id,
                        q.event_id,
                        q.source,
                        q.market_name,
                        q.market_key,
                        q.selection_name,
                        q.selection_key,
                        q.odds,
                        int(q.is_suspended),
                        now,
                        now,
                        now,
                        q.odds,
                    ),
                )
                self.db.execute(
                    """
                    INSERT INTO quote_changes(
                        event_id, selection_id, source, market_key, selection_key,
                        odds, prev_odds, is_suspended, change_type, captured_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'opening', ?)
                    """,
                    (
                        q.event_id,
                        q.id,
                        q.source,
                        q.market_key,
                        q.selection_key,
                        q.odds,
                        int(q.is_suspended),
                        now,
                    ),
                )
                changes += 1
                continue

            prev_odds = _row_get(rows[0], "odds")
            prev_susp = bool(_row_get(rows[0], "is_suspended"))
            odds_changed = _odds_changed(prev_odds, q.odds)
            susp_changed = prev_susp != q.is_suspended
            if not odds_changed and not susp_changed:
                self.db.execute(
                    "UPDATE selections_current SET last_seen_at = ? WHERE id = ?",
                    (now, q.id),
                )
                continue

            change_type = "odds" if odds_changed and not susp_changed else (
                "suspend" if susp_changed and not odds_changed else "odds_and_suspend"
            )
            self.db.execute(
                """
                UPDATE selections_current
                SET odds = ?, is_suspended = ?, last_seen_at = ?, last_changed_at = ?,
                    market_name = ?, selection_name = ?
                WHERE id = ?
                """,
                (
                    q.odds,
                    int(q.is_suspended),
                    now,
                    now,
                    q.market_name,
                    q.selection_name,
                    q.id,
                ),
            )
            self.db.execute(
                """
                INSERT INTO quote_changes(
                    event_id, selection_id, source, market_key, selection_key,
                    odds, prev_odds, is_suspended, change_type, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    q.event_id,
                    q.id,
                    q.source,
                    q.market_key,
                    q.selection_key,
                    q.odds,
                    prev_odds,
                    int(q.is_suspended),
                    change_type,
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
        return self.db.fetches(
            """
            SELECT market_name, selection_name, odds, is_suspended, opening_odds, last_changed_at
            FROM selections_current
            WHERE event_id = ?
            ORDER BY market_name, selection_name
            """,
            (event_id,),
        )

    def quote_history(self, event_id: str, limit: int = 50) -> list[Any]:
        return self.db.fetches(
            """
            SELECT market_key, selection_key, prev_odds, odds, change_type, captured_at
            FROM quote_changes
            WHERE event_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (event_id, limit),
        )


def _odds_changed(prev: Optional[float], new: Optional[float]) -> bool:
    if prev is None and new is None:
        return False
    if prev is None or new is None:
        return True
    return abs(float(prev) - float(new)) > 1e-9
