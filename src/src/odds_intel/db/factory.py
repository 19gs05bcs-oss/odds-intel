from __future__ import annotations

from typing import Any, Optional

from odds_intel.config import Settings
from odds_intel.db.connection import connect, migrate
from odds_intel.db.repo import Repository
from odds_intel.db.supabase_repo import SupabaseRepository


def create_repository(settings: Settings) -> tuple[Any, Optional[Any]]:
    """
    Returns (repo, closable).
    Prefer Supabase REST when SUPABASE_URL + SUPABASE_KEY are set (Koyeb/acoreapi style).
    """
    if settings.uses_supabase_rest:
        repo = SupabaseRepository(settings)
        return repo, repo

    db = connect(settings)
    migrate(db, settings)
    return Repository(db), db
