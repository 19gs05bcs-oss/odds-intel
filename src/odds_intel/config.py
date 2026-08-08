from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    bwin_base_url: str = "https://www.bwin.com"
    bwin_access_id: str = Field(
        default="",
        validation_alias=AliasChoices("BWIN_ACCESS_ID", "bwin_access_id"),
    )
    bwin_lang: str = Field(default="en", validation_alias=AliasChoices("BWIN_LANG", "bwin_lang"))
    bwin_country: str = Field(
        default="US",
        validation_alias=AliasChoices("BWIN_COUNTRY", "bwin_country"),
    )
    bwin_user_country: str = Field(
        default="US",
        validation_alias=AliasChoices("BWIN_USER_COUNTRY", "bwin_user_country"),
    )
    # Optional Cookie header from a real browser session (helps some edges)
    bwin_cookie: str = ""
    # Optional HTTP(S) proxy, e.g. http://user:pass@host:8080
    # Use when cloud IPs (Koyeb) get 403 from Bwin.
    bwin_proxy_url: str = ""
    # Optional debug allow-list. Empty = discover ALL fixtures for sport ids.
    bwin_fixture_ids: str = ""
    bwin_sport_ids: str = "4"
    # 0 = no cap (all discovered fixtures)
    bwin_max_fixtures: int = 0
    bwin_fixtures_page_size: int = 100

    poll_interval_sec: float = 60.0
    request_timeout_sec: float = 25.0

    # Koyeb / acoreapi style (preferred in production)
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_URL", "supabase_url"),
    )
    supabase_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_KEY", "supabase_key"),
    )

    # Optional direct Postgres / local sqlite fallback
    database_url: str = "sqlite:///data/odds_intel.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("bwin_access_id", "supabase_url", "supabase_key")
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def fill_from_environ(self) -> "Settings":
        # Belt-and-suspenders for hosts that inject env after import quirks.
        if not self.bwin_access_id:
            self.bwin_access_id = os.environ.get("BWIN_ACCESS_ID", "").strip()
        if not self.supabase_url:
            self.supabase_url = os.environ.get("SUPABASE_URL", "").strip()
        if not self.supabase_key:
            self.supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
        return self

    def fixture_id_list(self) -> list[str]:
        if not self.bwin_fixture_ids.strip():
            return []
        return [part.strip() for part in self.bwin_fixture_ids.split(",") if part.strip()]

    def sport_id_list(self) -> list[int]:
        out: list[int] = []
        for part in self.bwin_sport_ids.split(","):
            part = part.strip()
            if part:
                out.append(int(part))
        return out

    @property
    def uses_supabase_rest(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")


@lru_cache
def get_settings() -> Settings:
    return Settings()
