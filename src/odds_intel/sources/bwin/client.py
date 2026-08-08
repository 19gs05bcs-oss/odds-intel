from __future__ import annotations

from typing import Any, Optional

import httpx

from odds_intel.config import Settings

SOURCE = "bwin"


class BwinClient:
    def __init__(self, settings: Settings, client: Optional[httpx.Client] = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=settings.bwin_base_url.rstrip("/"),
            timeout=settings.request_timeout_sec,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) "
                    "Gecko/20100101 Firefox/128.0"
                ),
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "BwinClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _require_access_id(self) -> str:
        if not self.settings.bwin_access_id:
            raise RuntimeError("BWIN_ACCESS_ID is required")
        return self.settings.bwin_access_id

    def _common_params(self) -> dict[str, Any]:
        return {
            "x-bwin-accessid": self._require_access_id(),
            "lang": self.settings.bwin_lang,
            "country": self.settings.bwin_country,
            "userCountry": self.settings.bwin_user_country,
        }

    def list_fixtures(self, sport_id: int, max_fixtures: int | None = None) -> list[str]:
        params = {
            **self._common_params(),
            "sportIds": sport_id,
        }
        resp = self.client.get("/cds-api/bettingoffer/fixtures", params=params)
        resp.raise_for_status()
        payload = resp.json()
        ids = _extract_fixture_ids(payload)
        limit = max_fixtures if max_fixtures is not None else self.settings.bwin_max_fixtures
        return ids[:limit]

    def fixture_view(self, fixture_id: str) -> dict[str, Any]:
        fid = fixture_id if ":" in fixture_id or fixture_id.isdigit() else fixture_id
        params = {
            **self._common_params(),
            "offerMapping": "All",
            "scoreboardMode": "Full",
            "fixtureIds": fid,
            "state": "Latest",
            "includePrecreatedBetBuilder": "false",
            "supportVirtual": "false",
            "useRegionalisedConfiguration": "true",
            "statisticsModes": "None",
        }
        resp = self.client.get("/cds-api/bettingoffer/fixture-view", params=params)
        resp.raise_for_status()
        return resp.json()


def _extract_fixture_ids(payload: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # common shapes: {id: "2:123"} or nested fixtures arrays
            fid = node.get("id")
            if isinstance(fid, str) and (fid.startswith("2:") or fid.isdigit()):
                # prefer compound ids; skip pure market/option numeric noise by requiring stage/participants hints
                if "participants" in node or "stage" in node or "startDate" in node or "name" in node:
                    if fid not in seen:
                        seen.add(fid)
                        found.append(fid)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found
