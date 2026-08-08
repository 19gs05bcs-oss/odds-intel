from __future__ import annotations

import re
from typing import Any, Optional

from odds_intel.models import EventSnapshot, ScoreSnapshot, SelectionQuote
from odds_intel.sources.bwin.client import SOURCE

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _text(node: Any) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        value = node.get("value")
        if isinstance(value, str):
            return value
    return None


def _slug(text: str) -> str:
    s = _NON_ALNUM.sub("_", text.strip().lower()).strip("_")
    return s or "unknown"


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, dict):
        # price: {odds: 1.5} or nested
        if "odds" in value:
            return _as_float(value.get("odds"))
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_fixture(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if isinstance(payload.get("fixture"), dict):
        return payload["fixture"]
    fixtures = payload.get("fixtures")
    if isinstance(fixtures, list) and fixtures:
        first = fixtures[0]
        return first if isinstance(first, dict) else None
    # some envelopes nest under offer
    offer = payload.get("offer")
    if isinstance(offer, dict) and isinstance(offer.get("fixture"), dict):
        return offer["fixture"]
    return None


def _participants(fixture: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    parts = fixture.get("participants") or []
    home = away = None
    if isinstance(parts, list):
        for p in parts:
            if not isinstance(p, dict):
                continue
            name = _text(p.get("name")) or p.get("participantName")
            properties = p.get("properties") or {}
            ptype = (
                p.get("type")
                or p.get("participantType")
                or properties.get("type")
                or properties.get("side")
            )
            if isinstance(ptype, str):
                key = ptype.lower()
                if key in {"home", "1", "team1"}:
                    home = name
                elif key in {"away", "2", "team2"}:
                    away = name
        if home is None or away is None:
            names = [
                _text(p.get("name"))
                for p in parts
                if isinstance(p, dict) and _text(p.get("name"))
            ]
            if len(names) >= 2:
                home = home or names[0]
                away = away or names[1]
    return home, away


def parse_fixture_view(payload: dict[str, Any]) -> tuple[
    Optional[EventSnapshot],
    list[SelectionQuote],
    Optional[ScoreSnapshot],
]:
    fixture = _find_fixture(payload)
    if not fixture:
        return None, [], None

    source_event_id = str(fixture.get("id") or "")
    if not source_event_id:
        return None, [], None

    home, away = _participants(fixture)
    competition = None
    comp = fixture.get("competition") or fixture.get("league")
    if isinstance(comp, dict):
        competition = _text(comp.get("name"))
    elif isinstance(comp, str):
        competition = comp

    sport = None
    sport_node = fixture.get("sport")
    if isinstance(sport_node, dict):
        sport = _text(sport_node.get("name"))
    elif isinstance(sport_node, str):
        sport = sport_node

    event = EventSnapshot(
        source=SOURCE,
        source_event_id=source_event_id,
        sport=sport,
        competition=competition,
        home_team=home,
        away_team=away,
        kickoff_at=fixture.get("startDate") or fixture.get("startTime"),
        status=_text(fixture.get("stage")) or str(fixture.get("stage") or "") or None,
    )

    quotes = _parse_quotes(fixture, event.id)
    score = _parse_score(fixture, event.id)
    return event, quotes, score


def _parse_quotes(fixture: dict[str, Any], event_id: str) -> list[SelectionQuote]:
    out: list[SelectionQuote] = []

    option_markets = fixture.get("optionMarkets") or []
    if isinstance(option_markets, list):
        for market in option_markets:
            if not isinstance(market, dict):
                continue
            market_name = _text(market.get("name")) or "unknown_market"
            market_key = _slug(market_name)
            options = market.get("options") or market.get("results") or []
            if not isinstance(options, list):
                continue
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                sel_name = _text(opt.get("name")) or "unknown"
                odds = _as_float(opt.get("price")) or _as_float(opt.get("odds"))
                visibility = str(opt.get("visibility") or market.get("visibility") or "")
                suspended = visibility.lower() in {"suspended", "hidden", "invisible"}
                status = str(opt.get("status") or "")
                if status.lower() in {"suspended", "inactive"}:
                    suspended = True
                out.append(
                    SelectionQuote(
                        event_id=event_id,
                        source=SOURCE,
                        market_name=market_name,
                        market_key=market_key,
                        selection_name=sel_name,
                        selection_key=_slug(sel_name),
                        odds=odds,
                        is_suspended=suspended,
                    )
                )

    # alternate shape used by some CDS payloads
    games = fixture.get("games") or []
    if isinstance(games, list):
        for game in games:
            if not isinstance(game, dict):
                continue
            market_name = _text(game.get("name")) or "game_market"
            market_key = _slug(market_name)
            results = game.get("results") or []
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                sel_name = _text(result.get("name")) or "unknown"
                odds = _as_float(result.get("odds")) or _as_float(result.get("price"))
                visibility = str(result.get("visibility") or "")
                suspended = visibility.lower() in {"suspended", "hidden", "invisible"}
                out.append(
                    SelectionQuote(
                        event_id=event_id,
                        source=SOURCE,
                        market_name=market_name,
                        market_key=market_key,
                        selection_name=sel_name,
                        selection_key=_slug(sel_name),
                        odds=odds,
                        is_suspended=suspended,
                    )
                )

    return out


def _parse_score(fixture: dict[str, Any], event_id: str) -> Optional[ScoreSnapshot]:
    scoreboard = fixture.get("scoreboard") or fixture.get("liveScore") or {}
    if not isinstance(scoreboard, dict):
        scoreboard = {}

    stage = (
        _text(fixture.get("stage"))
        or str(fixture.get("stage") or "")
        or _text(scoreboard.get("stage"))
        or str(scoreboard.get("stage") or "")
        or None
    )
    period = (
        _text(scoreboard.get("period"))
        or str(scoreboard.get("period") or "")
        or _text(scoreboard.get("periodName"))
        or None
    )
    clock = None
    time_node = scoreboard.get("time") or scoreboard.get("timer")
    if isinstance(time_node, dict):
        mins = time_node.get("minutes")
        secs = time_node.get("seconds")
        if mins is not None:
            clock = f"{mins}:{int(secs or 0):02d}"
    elif isinstance(time_node, str):
        clock = time_node
    elif isinstance(scoreboard.get("clock"), str):
        clock = scoreboard.get("clock")

    home_score, away_score = _extract_scores(scoreboard, fixture)
    if home_score is None and away_score is None and not stage:
        return None

    stage_l = (stage or "").lower()
    is_final = any(
        token in stage_l
        for token in ("finished", "ended", "final", "closed", "completed", "settled")
    )

    return ScoreSnapshot(
        event_id=event_id,
        source=SOURCE,
        period=period,
        home_score=home_score,
        away_score=away_score,
        clock=clock,
        stage=stage,
        is_final=is_final,
    )


def _extract_scores(
    scoreboard: dict[str, Any], fixture: dict[str, Any]
) -> tuple[Optional[int], Optional[int]]:
    # common: score = "2:1" or score.home/away
    raw = scoreboard.get("score")
    if isinstance(raw, str) and ":" in raw:
        left, right = raw.split(":", 1)
        try:
            return int(left.strip()), int(right.strip())
        except ValueError:
            pass
    if isinstance(raw, dict):
        try:
            return int(raw.get("home")), int(raw.get("away"))
        except (TypeError, ValueError):
            pass

    for home_key, away_key in (
        ("homeScore", "awayScore"),
        ("home", "away"),
    ):
        if home_key in scoreboard or away_key in scoreboard:
            try:
                h = scoreboard.get(home_key)
                a = scoreboard.get(away_key)
                return (int(h) if h is not None else None), (int(a) if a is not None else None)
            except (TypeError, ValueError):
                break

    # participant scores
    parts = fixture.get("participants") or []
    if isinstance(parts, list) and len(parts) >= 2:
        scores: list[Optional[int]] = []
        for p in parts[:2]:
            if not isinstance(p, dict):
                scores.append(None)
                continue
            val = p.get("score") or (p.get("properties") or {}).get("score")
            try:
                scores.append(int(val) if val is not None else None)
            except (TypeError, ValueError):
                scores.append(None)
        if any(s is not None for s in scores):
            return scores[0], scores[1]

    return None, None
