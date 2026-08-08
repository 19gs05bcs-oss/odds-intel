from __future__ import annotations

import re
from typing import Optional

import httpx

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
ACCESS_RE = re.compile(
    r"x-bwin-accessid[=:\"'\s]+([0-9a-f-]{36})",
    re.I,
)


def discover_access_id(
    base_url: str = "https://www.bwin.com",
    timeout: float = 25.0,
) -> Optional[str]:
    """Best-effort extract of public cds-api access id from Bwin sports HTML/JS."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) "
            "Gecko/20100101 Firefox/128.0"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(
        headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        html = client.get(f"{base_url.rstrip('/')}/en/sports").text
        found = _from_text(html)
        if found:
            return found

        # follow a few script tags if HTML embeds bundles
        script_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html, flags=re.I)
        for url in script_urls[:12]:
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = base_url.rstrip("/") + url
            if not url.startswith("http"):
                continue
            try:
                js = client.get(url).text
            except Exception:
                continue
            found = _from_text(js)
            if found:
                return found
    return None


def _from_text(text: str) -> Optional[str]:
    m = ACCESS_RE.search(text)
    if m:
        return m.group(1).lower()
    # Prefer UUIDs near "access" keywords
    for m in re.finditer(r".{0,40}accessid.{0,40}", text, flags=re.I):
        um = UUID_RE.search(m.group(0))
        if um:
            return um.group(0).lower()
    return None


def resolve_access_id(configured: str, base_url: str = "https://www.bwin.com") -> str:
    """Use configured id if set; otherwise discover. Raises if neither works."""
    if configured.strip():
        return configured.strip()
    discovered = discover_access_id(base_url=base_url)
    if not discovered:
        raise RuntimeError(
            "BWIN_ACCESS_ID missing and auto-discovery failed; set secret or check Bwin HTML"
        )
    return discovered
