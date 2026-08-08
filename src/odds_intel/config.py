from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bwin_base_url: str = "https://www.bwin.com"
    bwin_access_id: str = ""
    bwin_lang: str = "en"
    bwin_country: str = "GB"
    bwin_user_country: str = "GB"
    # Optional debug allow-list. Empty = discover ALL fixtures for sport ids.
    bwin_fixture_ids: str = ""
    bwin_sport_ids: str = "4"
    # 0 = no cap (all discovered fixtures)
    bwin_max_fixtures: int = 0
    bwin_fixtures_page_size: int = 100

    poll_interval_sec: float = 30.0
    request_timeout_sec: float = 25.0

    # Koyeb / acoreapi style (preferred in production)
    supabase_url: str = ""
    supabase_key: str = ""

    # Optional direct Postgres / local sqlite fallback
    database_url: str = "sqlite:///data/odds_intel.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("bwin_access_id", "supabase_url", "supabase_key")
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return value.strip()

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
