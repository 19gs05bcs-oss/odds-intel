from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from odds_intel.config import Settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
POSTGRES_SCHEMA_PATH = Path(__file__).with_name("schema.postgres.sql")



class DbConn(Protocol):
    def execute(self, sql: str, params: Any = ()) -> Any: ...
    def executemany(self, sql: str, seq_of_params: Any) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...
    def fetches(self, sql: str, params: Any = ()) -> list[Any]: ...


class SqliteDb:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

    def execute(self, sql: str, params: Any = ()) -> Any:
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Any) -> Any:
        return self._conn.executemany(sql, seq_of_params)

    def executescript(self, script: str) -> Any:
        return self._conn.executescript(script)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def fetches(self, sql: str, params: Any = ()) -> list[Any]:
        cur = self._conn.execute(sql, params)
        return list(cur.fetchall())


class PostgresDb:
    def __init__(self, dsn: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(normalize_database_url(dsn), row_factory=dict_row)

    def execute(self, sql: str, params: Any = ()) -> Any:
        sql = _to_postgres_sql(sql)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur

    def executemany(self, sql: str, seq_of_params: Any) -> Any:
        sql = _to_postgres_sql(sql)
        with self._conn.cursor() as cur:
            cur.executemany(sql, seq_of_params)
            return cur

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def fetches(self, sql: str, params: Any = ()) -> list[Any]:
        sql = _to_postgres_sql(sql)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def _to_postgres_sql(sql: str) -> str:
    if "?" in sql and "%s" not in sql:
        return sql.replace("?", "%s")
    return sql


def normalize_database_url(database_url: str) -> str:
    """Normalize Supabase/Postgres URIs for psycopg (ssl + scheme)."""
    url = database_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    is_supabase = "supabase.co" in host or "supabase.com" in host
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if is_supabase and "sslmode" not in query:
        query["sslmode"] = "require"

    return urlunparse(parsed._replace(query=urlencode(query)))


def _sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    parsed = urlparse(database_url)
    if parsed.scheme == "sqlite":
        return Path(parsed.path)
    raise ValueError(f"Unsupported sqlite URL: {database_url}")


def connect(settings: Settings) -> SqliteDb | PostgresDb:
    if settings.is_postgres:
        return PostgresDb(settings.database_url)
    return SqliteDb(_sqlite_path(settings.database_url))


def migrate(db: SqliteDb | PostgresDb, settings: Settings) -> None:
    if settings.is_postgres:
        if POSTGRES_SCHEMA_PATH.exists():
            raw = POSTGRES_SCHEMA_PATH.read_text(encoding="utf-8")
        else:
            raw = SCHEMA_PATH.read_text(encoding="utf-8").replace(
                "id INTEGER PRIMARY KEY AUTOINCREMENT",
                "id BIGSERIAL PRIMARY KEY",
            )
        for stmt in _split_sql_statements(raw):
            db.execute(stmt)
        db.commit()
        return

    if isinstance(db, SqliteDb):
        db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        db.commit()
        return
    raise TypeError("Unsupported db type for migrate")


def _split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        statements.append(tail)
    return statements
