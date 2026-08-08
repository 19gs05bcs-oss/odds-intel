from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from odds_intel.config import Settings
from odds_intel.models import EventSnapshot, ScoreSnapshot, SelectionQuote


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _odds_changed(prev: Optional[float], new: Optional[float]) -> bool:
    if prev is None and new is None:
        return False
    if prev is None or new is None:
        return True
    return abs(float(prev) - float(new)) > 1e-9


class SupabaseRepository:
    """Change-only store over Supabase PostgREST (SUPABASE_URL + SUPABASE_KEY)."""

    def __init__(self, settings: Settings, client: Optional[httpx.Client] = None) -> None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
        self.base = settings.supabase_url.rstrip("/") + "/rest/v1"
        self._owns = client is None
        headers = {
            "apikey": settings.supabase_key,
            "Authorization": f"Bearer {settings.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self.client = client or httpx.Client(
            headers=headers,
            timeout=settings.request_timeout_sec,
        )

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def _raise_for_status(self, resp: httpx.Response, table: str) -> None:
        if resp.status_code == 404:
            raise RuntimeError(
                f"Supabase table '{table}' not found (HTTP 404). "
                "Run supabase/schema.sql once in Supabase SQL Editor, then retry."
            )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Supabase auth failed for '{table}' (HTTP {resp.status_code}). "
                "Use the service_role/secret key, not the anon key."
            )
        resp.raise_for_status()

    def _get(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        resp = self.client.get(f"{self.base}/{table}", params=params)
        self._raise_for_status(resp, table)
        data = resp.json()
        return data if isinstance(data, list) else []

    def _upsert(self, table: str, row: dict[str, Any], on_conflict: str) -> list[dict[str, Any]]:
        resp = self.client.post(
            f"{self.base}/{table}",
            params={"on_conflict": on_conflict},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json=row,
        )
        self._raise_for_status(resp, table)
        data = resp.json()
        return data if isinstance(data, list) else []

    def _insert(self, table: str, row: dict[str, Any]) -> list[dict[str, Any]]:
        resp = self.client.post(
            f"{self.base}/{table}",
            headers={"Prefer": "return=representation"},
            json=row,
        )
        self._raise_for_status(resp, table)
        data = resp.json()
        return data if isinstance(data, list) else []

    def _patch(self, table: str, match: dict[str, str], row: dict[str, Any]) -> None:
        resp = self.client.patch(f"{self.base}/{table}", params=match, json=row)
        self._raise_for_status(resp, table)

    def start_poll_run(self, source: str) -> int:
        rows = self._insert("poll_runs", {"source": source, "started_at": _utcnow()})
        return int(rows[0]["id"])

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
        self._patch(
            "poll_runs",
            {"id": f"eq.{run_id}"},
            {
                "finished_at": _utcnow(),
                "fixtures_polled": fixtures_polled,
                "quote_changes": quote_changes,
                "score_changes": score_changes,
                "error_count": error_count,
                "notes": notes,
            },
        )

    def upsert_event(self, event: EventSnapshot) -> None:
        now = _utcnow()
        existing = self._get("events", {"id": f"eq.{event.id}", "select": "id"})
        if not existing:
            self._insert(
                "events",
                {
                    "id": event.id,
                    "source": event.source,
                    "source_event_id": event.source_event_id,
                    "sport": event.sport,
                    "competition": event.competition,
                    "home_team": event.home_team,
                    "away_team": event.away_team,
                    "kickoff_at": event.kickoff_at,
                    "status": event.status,
                    "opening_captured_at": now,
                    "is_closed": 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            return
        self._patch(
            "events",
            {"id": f"eq.{event.id}"},
            {
                "sport": event.sport,
                "competition": event.competition,
                "home_team": event.home_team,
                "away_team": event.away_team,
                "kickoff_at": event.kickoff_at,
                "status": event.status,
                "updated_at": now,
            },
        )

    def apply_quotes(self, quotes: list[SelectionQuote]) -> int:
        if not quotes:
            return 0
        now = _utcnow()
        changes = 0
        for q in quotes:
            rows = self._get(
                "selections_current",
                {"id": f"eq.{q.id}", "select": "odds,is_suspended"},
            )
            if not rows:
                self._insert(
                    "selections_current",
                    {
                        "id": q.id,
                        "event_id": q.event_id,
                        "source": q.source,
                        "market_name": q.market_name,
                        "market_key": q.market_key,
                        "selection_name": q.selection_name,
                        "selection_key": q.selection_key,
                        "odds": q.odds,
                        "is_suspended": int(q.is_suspended),
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "last_changed_at": now,
                        "opening_odds": q.odds,
                    },
                )
                self._insert(
                    "quote_changes",
                    {
                        "event_id": q.event_id,
                        "selection_id": q.id,
                        "source": q.source,
                        "market_key": q.market_key,
                        "selection_key": q.selection_key,
                        "odds": q.odds,
                        "prev_odds": None,
                        "is_suspended": int(q.is_suspended),
                        "change_type": "opening",
                        "captured_at": now,
                    },
                )
                changes += 1
                continue

            prev_odds = rows[0].get("odds")
            prev_susp = bool(rows[0].get("is_suspended"))
            odds_changed = _odds_changed(prev_odds, q.odds)
            susp_changed = prev_susp != q.is_suspended
            if not odds_changed and not susp_changed:
                self._patch(
                    "selections_current",
                    {"id": f"eq.{q.id}"},
                    {"last_seen_at": now},
                )
                continue

            change_type = (
                "odds"
                if odds_changed and not susp_changed
                else "suspend"
                if susp_changed and not odds_changed
                else "odds_and_suspend"
            )
            self._patch(
                "selections_current",
                {"id": f"eq.{q.id}"},
                {
                    "odds": q.odds,
                    "is_suspended": int(q.is_suspended),
                    "last_seen_at": now,
                    "last_changed_at": now,
                    "market_name": q.market_name,
                    "selection_name": q.selection_name,
                },
            )
            self._insert(
                "quote_changes",
                {
                    "event_id": q.event_id,
                    "selection_id": q.id,
                    "source": q.source,
                    "market_key": q.market_key,
                    "selection_key": q.selection_key,
                    "odds": q.odds,
                    "prev_odds": prev_odds,
                    "is_suspended": int(q.is_suspended),
                    "change_type": change_type,
                    "captured_at": now,
                },
            )
            changes += 1
        return changes

    def apply_score(self, score: ScoreSnapshot) -> bool:
        rows = self._get(
            "score_changes",
            {
                "event_id": f"eq.{score.event_id}",
                "select": "period,home_score,away_score,clock,stage,is_final",
                "order": "id.desc",
                "limit": "1",
            },
        )
        if rows:
            prev = rows[0]
            same = (
                prev.get("period") == score.period
                and prev.get("home_score") == score.home_score
                and prev.get("away_score") == score.away_score
                and prev.get("clock") == score.clock
                and prev.get("stage") == score.stage
                and bool(prev.get("is_final")) == score.is_final
            )
            if same:
                return False

        now = _utcnow()
        self._insert(
            "score_changes",
            {
                "event_id": score.event_id,
                "source": score.source,
                "period": score.period,
                "home_score": score.home_score,
                "away_score": score.away_score,
                "clock": score.clock,
                "stage": score.stage,
                "is_final": int(score.is_final),
                "captured_at": now,
            },
        )
        if score.is_final:
            self._patch(
                "events",
                {"id": f"eq.{score.event_id}"},
                {
                    "status": score.stage or "Finished",
                    "closing_captured_at": now,
                    "is_closed": 1,
                    "updated_at": now,
                },
            )
        return True

    def mark_event_closed(self, event_id: str, status: str = "Closed") -> None:
        now = _utcnow()
        # only if not closed — best-effort patch
        rows = self._get("events", {"id": f"eq.{event_id}", "select": "is_closed,closing_captured_at"})
        if rows and int(rows[0].get("is_closed") or 0) == 1:
            return
        closing = (rows[0].get("closing_captured_at") if rows else None) or now
        self._patch(
            "events",
            {"id": f"eq.{event_id}"},
            {
                "status": status,
                "closing_captured_at": closing,
                "is_closed": 1,
                "updated_at": now,
            },
        )

    def latest_quotes(self, event_id: str) -> list[Any]:
        return self._get(
            "selections_current",
            {
                "event_id": f"eq.{event_id}",
                "select": "market_name,selection_name,odds,is_suspended,opening_odds,last_changed_at",
                "order": "market_name.asc,selection_name.asc",
            },
        )

    def quote_history(self, event_id: str, limit: int = 50) -> list[Any]:
        return self._get(
            "quote_changes",
            {
                "event_id": f"eq.{event_id}",
                "select": "market_key,selection_key,prev_odds,odds,change_type,captured_at",
                "order": "id.desc",
                "limit": str(limit),
            },
        )
