"""Konfigurationseinstellungen für ChronosLedger."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Zentrale Anwendungskonfiguration."""
    PROJECT_NAME: str = Field(default="ChronosLedger")
    VERSION: str = Field(default="1.0.0")
    API_V1_STR: str = Field(default="/api/v1")
    DATABASE_URL: str = Field(default=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ledger.db"))
    SECRET_KEY: str = Field(default=os.getenv("SECRET_KEY", "chronos-ledger-super-secret-key-change-in-production"))
    API_KEY: str = Field(default=os.getenv("API_KEY", "test-api-key-12345"))
    BUFFER_CAPACITY: int = Field(default=10000)
    BATCH_SIZE: int = Field(default=100)
    FLUSH_INTERVAL: float = Field(default=0.5)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Gibt gecachte Settings-Instanz zurück."""
    return Settings()
