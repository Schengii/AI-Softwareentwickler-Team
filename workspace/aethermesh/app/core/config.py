"""Zentrale Konfigurationsverwaltung für AetherMesh mit Pydantic-Settings."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Anwendungs-Einstellungen mit robusten Dev-Defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "AetherMesh Engine"
    DEBUG: bool = False

    # Datenbank & Spooling
    DATABASE_URL: str = "sqlite+aiosqlite:///./jobs.db"

    # Worker-Pool Konfiguration
    MAX_WORKERS: int = Field(default=4, ge=1, le=64)

    # Queue & Backpressure
    MAX_QUEUE_SIZE: int = Field(default=1000, ge=10)
    BACKPRESSURE_HIGH_WATERMARK: float = Field(default=0.85, ge=0.1, le=1.0)
    BACKPRESSURE_LOW_WATERMARK: float = Field(default=0.50, ge=0.0, le=0.9)
    RETRY_AFTER_SECONDS: int = Field(default=5, ge=1)

    # Retry-Strategie & DLQ
    MAX_RETRIES: int = Field(default=3, ge=0)
    BASE_RETRY_DELAY_SEC: float = Field(default=0.5, ge=0.01)
    RETRY_BACKOFF_FACTOR: float = Field(default=2.0, ge=1.0)


@lru_cache
def get_settings() -> Settings:
    """Liefert gecachte Instanz der Anwendungs-Einstellungen."""
    return Settings()
