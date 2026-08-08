from __future__ import annotations

import base64
import logging
import re
from typing import Iterable, Optional
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
ACCESS_RE = re.compile(
    r"x-bwin-accessid[=:\"'\s]+([A-Za-z0-9+/=_-]{20,})",
    re.I,
)
ACCESS_KEY_RE = re.compile(
    r"(?:access[_-]?id|accessId|bwinAccessId|xBwinAccessId)[\"'\s:=]+([A-Za-z0-9+/=_-]{20,})",
    re.I,
)
B64_CHUNK_RE = re.compile(r"[A-Za-z0-9+/]{40,64}={0,2}")

# Public brand access ids seen in working cds-api calls (validated before use).
KNOWN_FALLBACKS = (
    "NTZiMjk3OGMtNjU5Mi00NjA5LWI2MWItZmU4MDRhN2QxZmEz",  # base64(56b2978c-6592-4609-b61b-fe804a7d1fa3)
)

MOBILE_UA = (
    "Mozilla/5.0 (Android 13; Mobile; rv:144.0) Gecko/144.0 Firefox/144.0"
)


def validate_access_id(
    access_id: str,
    *,
    base_url: str = "https://www.bwin.com",
    lang: str = "en",
    country: str = "US",
    user_country: str = "US",
    timeout: float = 25.0,
) -> bool:
    """Return True if cds-api accepts this access id for fixtures listing."""
    aid = access_id.strip()
    if not aid:
        return False
    headers = {
        "User-Agent": MOBILE_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": lang,
        "Referer": f"{base_url.rstrip('/')}/{lang}/sports/football-4",
        "x-bwin-browser-url": f"{base_url.rstrip('/')}/{lang}/sports/football-4",
    }
    params = {
        "x-bwin-accessid": aid,
        "lang": lang,
        "country": country,
        "userCountry": user_country,
        "sportIds": 4,
    }
    try:
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
            resp = client.get(f"{base_url.rstrip('/')}/cds-api/bettingoffer/fixtures", params=params)
        if resp.status_code != 200:
            return False
        data = resp.json()
        return isinstance(data, dict) and ("fixtures" in data or "fixture" in data)
    except Exception:
        logger.debug("access id validation failed", exc_info=True)
        return False


def discover_access_id(
    base_url: str = "https://www.bwin.com",
    *,
    lang: str = "en",
    country: str = "US",
    user_country: str = "US",
    timeout: float = 25.0,
    extra_candidates: Iterable[str] = (),
) -> Optional[str]:
    """
    Find a working x-bwin-accessid.
    Order: page/JS candidates → base64-uuid candidates → known fallbacks.
    Each candidate is validated against cds-api before return.
    """
    candidates: list[str] = []

    def add(value: Optional[str]) -> None:
        if not value:
            return
        v = value.strip()
        if not v or v in candidates:
            return
        candidates.append(v)
        # also try uuid <-> base64 variants
        for alt in _variants(v):
            if alt not in candidates:
                candidates.append(alt)

    for c in extra_candidates:
        add(c)

    headers = {
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Accept-Language": f"{lang}-{country},{lang};q=0.9",
    }
    root = base_url.rstrip("/") + "/"
    try:
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
            html = client.get(urljoin(root, f"{lang}/sports")).text
            for hit in _extract_candidates(html):
                add(hit)

            asset_urls = re.findall(
                r"(?:src|href)=[\"']([^\"']+\.(?:js|json)[^\"']*)[\"']",
                html,
                flags=re.I,
            )
            asset_urls += re.findall(r"https?://[^\"'\s]+?\.(?:js|json)", html, flags=re.I)
            # Prefer ClientDist sports bundles
            asset_urls = sorted(
                set(asset_urls),
                key=lambda u: (0 if "ClientDist" in u or "sports" in u.lower() else 1, u),
            )

            seen: set[str] = set()
            for raw in asset_urls:
                url = raw
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = urljoin(root, url.lstrip("/"))
                if not url.startswith("http") or url in seen:
                    continue
                seen.add(url)
                if len(seen) > 50:
                    break
                try:
                    body = client.get(url).text
                except Exception:
                    continue
                for hit in _extract_candidates(body):
                    add(hit)
    except Exception:
        logger.exception("access id page crawl failed")

    for fb in KNOWN_FALLBACKS:
        add(fb)

    logger.info("validating %s access id candidates", len(candidates))
    for aid in candidates:
        if validate_access_id(
            aid,
            base_url=base_url,
            lang=lang,
            country=country,
            user_country=user_country,
            timeout=timeout,
        ):
            logger.info("validated access id (len=%s)", len(aid))
            return aid
    return None


def resolve_access_id(
    configured: str,
    base_url: str = "https://www.bwin.com",
    *,
    lang: str = "en",
    country: str = "US",
    user_country: str = "US",
) -> str:
    """Prefer configured id if still valid; otherwise rediscover a working one."""
    configured = configured.strip()
    if configured and validate_access_id(
        configured,
        base_url=base_url,
        lang=lang,
        country=country,
        user_country=user_country,
    ):
        return configured

    if configured:
        logger.warning("configured BWIN_ACCESS_ID invalid/expired — rediscovering")

    discovered = discover_access_id(
        base_url=base_url,
        lang=lang,
        country=country,
        user_country=user_country,
        extra_candidates=[configured] if configured else [],
    )
    if not discovered:
        raise RuntimeError(
            "Could not resolve a working BWIN_ACCESS_ID "
            f"(country={country}, lang={lang}). Check network/IP block."
        )
    return discovered


def _extract_candidates(text: str) -> list[str]:
    out: list[str] = []
    for pattern in (ACCESS_RE, ACCESS_KEY_RE):
        for m in pattern.finditer(text):
            out.append(m.group(1))
    for m in re.finditer(r".{0,80}access[_-]?id.{0,80}", text, flags=re.I):
        um = UUID_RE.search(m.group(0))
        if um:
            out.append(um.group(0))
    # base64 blobs that decode to a UUID (Entain style access ids)
    for m in B64_CHUNK_RE.finditer(text):
        chunk = m.group(0)
        decoded = _b64_to_uuid(chunk)
        if decoded:
            out.append(chunk)
            out.append(decoded)
    return out


def _variants(value: str) -> list[str]:
    out: list[str] = []
    if UUID_RE.fullmatch(value):
        raw = value.encode("ascii")
        out.append(base64.b64encode(raw).decode("ascii"))
    decoded = _b64_to_uuid(value)
    if decoded:
        out.append(decoded)
    return out


def _b64_to_uuid(value: str) -> Optional[str]:
    try:
        pad = "=" * (-len(value) % 4)
        text = base64.b64decode(value + pad, validate=False).decode("ascii")
    except Exception:
        return None
    if UUID_RE.fullmatch(text):
        return text.lower()
    return None
