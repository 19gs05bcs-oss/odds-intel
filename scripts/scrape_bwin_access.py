#!/usr/bin/env python3
"""Scrape + validate Bwin x-bwin-accessid; optionally update a GitHub Actions secret.

Usage:
  python scripts/scrape_bwin_access.py
  python scripts/scrape_bwin_access.py --update-secret
  python scripts/scrape_bwin_access.py --update-secret --secret-name BWIN_ACCESS_ID

Env:
  BWIN_ACCESS_ID   optional seed / previous value (skip secret write if unchanged)
  BWIN_BASE_URL    default https://www.bwin.com
  BWIN_LANG        default en
  BWIN_COUNTRY     default US
  BWIN_USER_COUNTRY default US
  GITHUB_REPOSITORY owner/repo (set automatically in Actions)
  GH_TOKEN / GITHUB_TOKEN  required for --update-secret
  GITHUB_OUTPUT    if set, also writes id=<value> for workflow steps
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

# Allow running without install: add src/ to path
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from odds_intel.sources.bwin.access_id import discover_access_id  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("scrape_bwin_access")


def _write_github_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def _update_github_secret(name: str, value: str, repo: str) -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN or GITHUB_TOKEN required for --update-secret")
    env = {**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token}
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo, "--body", value],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"gh secret set failed: {err}")
    logger.info("updated GitHub secret %s on %s", name, repo)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Bwin access id")
    parser.add_argument(
        "--update-secret",
        action="store_true",
        help="Write secret via gh if value changed",
    )
    parser.add_argument(
        "--secret-name",
        default=os.environ.get("SECRET_NAME", "BWIN_ACCESS_ID"),
        help="GitHub secret name (default BWIN_ACCESS_ID)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/repo (default GITHUB_REPOSITORY)",
    )
    args = parser.parse_args()

    seed = os.environ.get("BWIN_ACCESS_ID", "").strip()
    aid = discover_access_id(
        base_url=os.environ.get("BWIN_BASE_URL", "https://www.bwin.com"),
        lang=os.environ.get("BWIN_LANG", "en"),
        country=os.environ.get("BWIN_COUNTRY", "US"),
        user_country=os.environ.get("BWIN_USER_COUNTRY", "US"),
        extra_candidates=[seed] if seed else [],
    )
    if not aid:
        logger.error("working access id not found")
        return 1

    # stdout = machine-readable id only
    print(aid, flush=True)
    _write_github_output("id", aid)
    _write_github_output("changed", "false" if seed and seed == aid else "true")

    if args.update_secret:
        if not args.repo:
            raise SystemExit("--repo or GITHUB_REPOSITORY required with --update-secret")
        if seed and seed == aid:
            logger.info("secret %s unchanged (len=%s)", args.secret_name, len(aid))
        else:
            _update_github_secret(args.secret_name, aid, args.repo)
            logger.info("secret %s updated (len=%s)", args.secret_name, len(aid))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
