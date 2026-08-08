"""Build a compact, stable markets JSON blob from selection quotes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from odds_intel.models import SelectionQuote


def build_markets_blob(quotes: list[SelectionQuote]) -> tuple[dict[str, Any], str, int]:
    """Return (markets_json, sha256_hex, selection_count)."""
    by_market: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for q in quotes:
        if q.market_key not in by_market:
            by_market[q.market_key] = {
                "key": q.market_key,
                "name": q.market_name,
                "selections": [],
            }
            order.append(q.market_key)
        by_market[q.market_key]["selections"].append(
            {
                "key": q.selection_key,
                "name": q.selection_name,
                "odds": q.odds,
                "suspended": bool(q.is_suspended),
            }
        )

    markets = []
    for mk in order:
        m = by_market[mk]
        m["selections"].sort(key=lambda s: s["key"])
        markets.append(m)
    markets.sort(key=lambda m: m["key"])

    blob: dict[str, Any] = {"markets": markets}
    raw = json.dumps(blob, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return blob, digest, len(quotes)


def group_quotes_by_event(quotes: list[SelectionQuote]) -> dict[str, list[SelectionQuote]]:
    grouped: dict[str, list[SelectionQuote]] = defaultdict(list)
    for q in quotes:
        grouped[q.event_id].append(q)
    return dict(grouped)


def flatten_markets_blob(blob: Any) -> list[dict[str, Any]]:
    """Flatten markets_json into row-like dicts for CLI display."""
    if not blob:
        return []
    if isinstance(blob, str):
        blob = json.loads(blob)
    out: list[dict[str, Any]] = []
    for market in blob.get("markets") or []:
        for sel in market.get("selections") or []:
            out.append(
                {
                    "market_name": market.get("name"),
                    "market_key": market.get("key"),
                    "selection_name": sel.get("name"),
                    "selection_key": sel.get("key"),
                    "odds": sel.get("odds"),
                    "is_suspended": int(bool(sel.get("suspended"))),
                }
            )
    out.sort(key=lambda r: (r.get("market_name") or "", r.get("selection_name") or ""))
    return out
