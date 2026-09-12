"""Konfigurationsmodul für ToggleForge."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "ToggleForge"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite+aiosqlite:///./toggleforge.db"
    API_V1_PREFIX: str = "/api/v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Liefert die gecachte Anwendungs-Konfiguration."""
    return Settings()
