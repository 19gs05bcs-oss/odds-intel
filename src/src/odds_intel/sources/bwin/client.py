from __future__ import annotations

from typing import Any, Optional

import httpx

from odds_intel.config import Settings
from odds_intel.sources.bwin.access_id import resolve_access_id

SOURCE = "bwin"


class BwinClient:
    def __init__(self, settings: Settings, client: Optional[httpx.Client] = None) -> None:
        self.settings = settings
        self._access_id: Optional[str] = None
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
        if self._access_id:
            return self._access_id
        self._access_id = resolve_access_id(
            self.settings.bwin_access_id,
            base_url=self.settings.bwin_base_url,
        )
        return self._access_id

    def _common_params(self) -> dict[str, Any]:
        return {
            "x-bwin-accessid": self._require_access_id(),
            "lang": self.settings.bwin_lang,
            "country": self.settings.bwin_country,
            "userCountry": self.settings.bwin_user_country,
        }

    def list_fixtures(self, sport_id: int, max_fixtures: int | None = None) -> list[str]:
        """Discover all fixture ids for a sport (paginated). max_fixtures<=0 → no cap."""
        limit = self.settings.bwin_max_fixtures if max_fixtures is None else max_fixtures
        page_size = max(1, self.settings.bwin_fixtures_page_size)
        found: list[str] = []
        seen: set[str] = set()
        skip = 0

        while True:
            if limit > 0 and len(found) >= limit:
                break
            params = {
                **self._common_params(),
                "sportIds": sport_id,
                "fixtureTypes": "Standard",
                "state": "Latest",
                "offerMapping": "Filtered",
                "take": page_size,
                "skip": skip,
            }
            resp = self.client.get("/cds-api/bettingoffer/fixtures", params=params)
            resp.raise_for_status()
            page_ids = _extract_fixture_ids(resp.json())
            if not page_ids:
                # some regions ignore skip/take — one unpaginated call then stop
                if skip == 0:
                    params.pop("take", None)
                    params.pop("skip", None)
                    resp = self.client.get("/cds-api/bettingoffer/fixtures", params=params)
                    resp.raise_for_status()
                    page_ids = _extract_fixture_ids(resp.json())
                    for fid in page_ids:
                        if fid not in seen:
                            seen.add(fid)
                            found.append(fid)
                break

            new_on_page = 0
            for fid in page_ids:
                if fid in seen:
                    continue
                seen.add(fid)
                found.append(fid)
                new_on_page += 1
                if limit > 0 and len(found) >= limit:
                    break

            if new_on_page == 0:
                break
            skip += page_size
            # safety: avoid infinite loop if API ignores skip
            if skip > 20_000:
                break

        if limit > 0:
            return found[:limit]
        return found

    def fixture_view(self, fixture_id: str) -> dict[str, Any]:
        params = {
            **self._common_params(),
            "offerMapping": "All",
            "scoreboardMode": "Full",
            "fixtureIds": fixture_id,
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
            fid = node.get("id")
            if isinstance(fid, (int, float)):
                fid = str(int(fid))
            if isinstance(fid, str) and (fid.startswith("2:") or fid.isdigit()):
                looks_like_fixture = any(
                    key in node
                    for key in (
                        "participants",
                        "stage",
                        "startDate",
                        "startTime",
                        "competition",
                        "sport",
                        "name",
                    )
                )
                if looks_like_fixture and fid not in seen:
                    seen.add(fid)
                    found.append(fid)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found
