"""Zentrale Konfiguration für AegisMesh via Pydantic V2 BaseSettings."""

import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    """Zentrale Gateway-Einstellungen mit sicheren Dev-Defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
    )

    PROJECT_NAME: str = "AegisMesh"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Datenbank (Single-DB Async SQLite für Audit Logs)
    DATABASE_URL: str = "sqlite+aiosqlite:///./aegis_mesh.db"

    # HMAC Zero-Trust Signaturgeheimnis
    HMAC_SECRET: str = Field(
        default_factory=lambda: secrets.token_hex(32),
        description="Geheimes Signatur-Token für HMAC-SHA256 Requests",
    )
    MAX_TIMESTAMP_DRIFT_SECONDS: int = 300  # 5 Minuten Replay-Fenster

    # Rate Limiting Konfiguration (Token Bucket)
    RATE_LIMIT_CAPACITY: int = 60  # Burst-Kapazität (Tokens)
    RATE_LIMIT_REFILL_RATE: float = 1.0  # Tokens pro Sekunde
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    BURST_CAPACITY: int = 60
    REFILL_RATE: float = 1.0

    # ML Anomaly Scorer Konfiguration
    ANOMALY_THRESHOLD: float = 0.75  # Ab 0.75 Anomaly-Score Drosselung/Block
    ANOMALY_PENALTY_FACTOR: float = 2.0  # Token-Kosten Multiplikator bei hohem Risiko


@lru_cache
def get_settings() -> Settings:
    """Liefert gecachte Instanz der Einstellungen."""
    return Settings()
