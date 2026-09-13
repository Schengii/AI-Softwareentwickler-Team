"""Konfiguration für Vortex Circuit Engine.

Zentrale Konfiguration für Anwendung, Datenbank, Circuit Breaker und Outbox.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Zentrale Anwendungseinstellungen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Basis-Konfiguration
    APP_NAME: str = "vortex_circuit"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # Datenbank-Konfiguration (ausschließlich asynchron)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./vortex_circuit.db",
    )
    DB_ECHO: bool = False

    # Outbox & DLQ Einstellungen
    OUTBOX_POLL_INTERVAL_SECONDS: float = 1.0
    OUTBOX_BATCH_SIZE: int = 50
    OUTBOX_MAX_RETRIES: int = 5
    OUTBOX_BASE_BACKOFF_SECONDS: float = 2.0
    OUTBOX_MAX_BACKOFF_SECONDS: float = 60.0
    OUTBOX_BACKOFF_FACTOR: float = 2.0
    HMAC_SECRET_KEY: str | None = None


settings = Settings()
