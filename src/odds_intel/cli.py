from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from odds_intel.config import get_settings
from odds_intel.db.connection import connect, migrate
from odds_intel.db.factory import create_repository
from odds_intel.sources.bwin import BwinClient, parse_fixture_view
from odds_intel.worker.poller import poll_once, run_forever

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _setup_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command("migrate")
def migrate_cmd() -> None:
    """Create / update database schema (SQL path). For Supabase REST, use SQL Editor."""
    _setup_logging()
    settings = get_settings()
    if settings.uses_supabase_rest and not settings.is_postgres:
        console.print(
            "[yellow]SUPABASE_URL/KEY set — apply supabase/schema.sql in Supabase SQL Editor.[/yellow]\n"
            "Or set DATABASE_URL to the Postgres URI and re-run migrate."
        )
        raise typer.Exit(0)
    db = connect(settings)
    migrate(db, settings)
    db.close()
    console.print(f"[green]migrated[/green] {settings.database_url}")


@app.command("poll-once")
def poll_once_cmd() -> None:
    """Run a single Bwin poll cycle (change-only writes)."""
    _setup_logging()
    summary = poll_once()
    console.print(summary)


@app.command("worker")
def worker_cmd() -> None:
    """Continuous poller for Koyeb / long-running hosts."""
    _setup_logging()
    run_forever()


@app.command("show-event")
def show_event_cmd(event_id: str) -> None:
    """Show current quotes + recent changes for an event id (e.g. bwin:2:7823441)."""
    _setup_logging()
    settings = get_settings()
    repo, closable = create_repository(settings)
    try:
        quotes = repo.latest_quotes(event_id)
        history = repo.quote_history(event_id, limit=30)
    finally:
        if closable is not None:
            closable.close()

    table = Table(title=f"Current quotes — {event_id}")
    table.add_column("Market")
    table.add_column("Selection")
    table.add_column("Odds")
    table.add_column("Open")
    table.add_column("Changed")
    for row in quotes:
        get = row.get if isinstance(row, dict) else row.__getitem__
        table.add_row(
            str(get("market_name")),
            str(get("selection_name")),
            str(get("odds")),
            str(get("opening_odds")),
            str(get("last_changed_at")),
        )
    console.print(table)

    htable = Table(title="Recent quote changes")
    htable.add_column("When")
    htable.add_column("Market")
    htable.add_column("Sel")
    htable.add_column("Prev")
    htable.add_column("New")
    htable.add_column("Type")
    for row in history:
        get = row.get if isinstance(row, dict) else row.__getitem__
        htable.add_row(
            str(get("captured_at")),
            str(get("market_key")),
            str(get("selection_key")),
            str(get("prev_odds")),
            str(get("odds")),
            str(get("change_type")),
        )
    console.print(htable)


@app.command("ingest-file")
def ingest_file_cmd(
    path: Path,
    fixture_id: Optional[str] = typer.Option(None, help="Override source fixture id"),
) -> None:
    """Parse a saved fixture-view JSON (offline) and apply change-only upserts."""
    _setup_logging()
    settings = get_settings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if fixture_id and isinstance(payload, dict):
        fixture = payload.get("fixture")
        if isinstance(fixture, dict) and not fixture.get("id"):
            fixture["id"] = fixture_id

    event, quotes, score = parse_fixture_view(payload)
    if not event:
        raise typer.Exit("Could not parse fixture from file")

    repo, closable = create_repository(settings)
    try:
        repo.upsert_event(event)
        q_changes = repo.apply_quotes(quotes)
        s_changed = bool(score and repo.apply_score(score))
    finally:
        if closable is not None:
            closable.close()
    console.print(
        {
            "event_id": event.id,
            "quotes": len(quotes),
            "quote_changes": q_changes,
            "score_changed": s_changed,
            "home": event.home_team,
            "away": event.away_team,
        }
    )


@app.command("fetch-fixture")
def fetch_fixture_cmd(fixture_id: str, out: Optional[Path] = None) -> None:
    """Fetch one fixture-view from Bwin and optionally save JSON."""
    _setup_logging()
    settings = get_settings()
    with BwinClient(settings) as client:
        payload = client.fixture_view(fixture_id)
    if out:
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"wrote {out}")
    event, quotes, score = parse_fixture_view(payload)
    console.print(
        {
            "event_id": event.id if event else None,
            "quotes": len(quotes),
            "score": None
            if not score
            else {
                "home": score.home_score,
                "away": score.away_score,
                "stage": score.stage,
                "is_final": score.is_final,
            },
        }
    )


if __name__ == "__main__":
    app()
