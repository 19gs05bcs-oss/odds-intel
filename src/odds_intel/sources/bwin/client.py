from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from odds_intel.config import Settings
from odds_intel.sources.bwin.access_id import resolve_access_id

SOURCE = "bwin"
logger = logging.getLogger(__name__)


def _browser_headers(settings: Settings) -> dict[str, str]:
    base = settings.bwin_base_url.rstrip("/")
    referer = f"{base}/{settings.bwin_lang}/sports/football-4"
    headers = {
        # Mobile UA matches working cds-api calls from EC2
        "User-Agent": (
            "Mozilla/5.0 (Android 13; Mobile; rv:144.0) Gecko/144.0 Firefox/144.0"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": settings.bwin_lang,
        "Origin": base,
        "Referer": referer,
        "x-bwin-browser-url": referer,
        "X-Device-Type": "phone_Android",
        "X-From-Product": "host-app",
    }
    if settings.bwin_cookie.strip():
        headers["Cookie"] = settings.bwin_cookie.strip()
    return headers


class BwinClient:
    def __init__(self, settings: Settings, client: Optional[httpx.Client] = None) -> None:
        self.settings = settings
        self._access_id: Optional[str] = None
        self._owns_client = client is None
        proxy = settings.bwin_proxy_url.strip() or None
        self.client = client or httpx.Client(
            base_url=settings.bwin_base_url.rstrip("/"),
            timeout=settings.request_timeout_sec,
            headers=_browser_headers(settings),
            proxy=proxy,
            follow_redirects=True,
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
            lang=self.settings.bwin_lang,
            country=self.settings.bwin_country,
            user_country=self.settings.bwin_user_country,
        )
        return self._access_id

    def _common_params(self) -> dict[str, Any]:
        return {
            "x-bwin-accessid": self._require_access_id(),
            "lang": self.settings.bwin_lang,
            "country": self.settings.bwin_country,
            "userCountry": self.settings.bwin_user_country,
        }

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        # Prefer access id as header too (some edges care)
        headers = {"x-bwin-accessid": self._require_access_id()}
        resp = self.client.get(path, params=params, headers=headers)
        if resp.status_code == 403:
            body = (resp.text or "")[:300].replace("\n", " ")
            raise RuntimeError(
                "Bwin returned 403 Forbidden — almost always datacenter/VPN IP block "
                "(Koyeb/cloud often blocked). Run the worker on a residential/VPS IP "
                "that can open bwin.com in a browser, or set BWIN_PROXY_URL. "
                f"body={body!r}"
            )
        resp.raise_for_status()
        return resp.json()

    def list_fixtures(self, sport_id: int, max_fixtures: int | None = None) -> list[str]:
        """Discover fixture ids for a sport. Tries simple HAR-style call first."""
        limit = self.settings.bwin_max_fixtures if max_fixtures is None else max_fixtures
        page_size = max(1, self.settings.bwin_fixtures_page_size)

        # 1) Simple request matching browser HAR (most reliable)
        simple = {
            **self._common_params(),
            "sportIds": sport_id,
        }
        payload = self._get_json("/cds-api/bettingoffer/fixtures", simple)
        found = _extract_fixture_ids(payload)
        if found:
            logger.info("fixtures simple listing returned %s ids", len(found))
            if limit > 0:
                return found[:limit]
            return found

        # 2) Paginated fallback
        found = []
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
            page_ids = _extract_fixture_ids(
                self._get_json("/cds-api/bettingoffer/fixtures", params)
            )
            if not page_ids:
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
        return self._get_json("/cds-api/bettingoffer/fixture-view", params)


def _extract_fixture_ids(payload: Any) -> list[str]:
    """Keep only real match fixtures (2 participants), not sport/comp/special ids."""
    found: list[str] = []
    seen: set[str] = set()

    fixtures = payload.get("fixtures") if isinstance(payload, dict) else None
    if not isinstance(fixtures, list):
        # rare envelopes
        fixtures = []
        if isinstance(payload, dict):
            for key in ("items", "data", "result"):
                node = payload.get(key)
                if isinstance(node, list):
                    fixtures = node
                    break
                if isinstance(node, dict) and isinstance(node.get("fixtures"), list):
                    fixtures = node["fixtures"]
                    break

    for node in fixtures:
        if not isinstance(node, dict):
            continue
        fid = node.get("id")
        if isinstance(fid, (int, float)):
            fid = str(int(fid))
        if not isinstance(fid, str) or not fid:
            continue
        # skip tiny ids (sport/region noise like "4", "6")
        if fid.isdigit() and len(fid) < 5:
            continue
        parts = node.get("participants") or []
        if not isinstance(parts, list) or len(parts) < 2:
            continue
        name = ""
        raw_name = node.get("name")
        if isinstance(raw_name, dict):
            name = str(raw_name.get("value") or "")
        elif isinstance(raw_name, str):
            name = raw_name
        lowered = name.lower()
        if any(tok in lowered for tok in ("acca", "enhanced", "special", "boost", "bet builder")):
            continue
        if fid in seen:
            continue
        seen.add(fid)
        found.append(fid)
    return found
