from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class EventSnapshot:
    source: str
    source_event_id: str
    sport: Optional[str]
    competition: Optional[str]
    home_team: Optional[str]
    away_team: Optional[str]
    kickoff_at: Optional[str]
    status: Optional[str]

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_event_id}"


@dataclass(slots=True)
class SelectionQuote:
    event_id: str
    source: str
    market_name: str
    market_key: str
    selection_name: str
    selection_key: str
    odds: Optional[float]
    is_suspended: bool

    @property
    def id(self) -> str:
        return f"{self.event_id}|{self.market_key}|{self.selection_key}"


@dataclass(slots=True)
class ScoreSnapshot:
    event_id: str
    source: str
    period: Optional[str]
    home_score: Optional[int]
    away_score: Optional[int]
    clock: Optional[str]
    stage: Optional[str]
    is_final: bool
