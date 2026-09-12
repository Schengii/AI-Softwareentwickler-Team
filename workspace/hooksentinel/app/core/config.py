"""Zentrale Konfigurationsverwaltung via Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Anwendungsweite Einstellungen mit sicheren Entwicklungs-Defaults."""

    APP_NAME: str = "HookSentinel"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # SQLite async DSN mit WAL-Modus
    DATABASE_URL: str = "sqlite+aiosqlite:///./hooksentinel.db"
    
    # Idempotenz & Retention
    IDEMPOTENCY_TTL_SECONDS: int = 86400  # 24 Stunden Dedup-Fenster
    
    # Relay Dispatcher & Resilience
    DISPATCHER_POLL_INTERVAL: float = 1.0  # Sekunden
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 2.0  # 2s, 4s, 8s
    TARGET_TIMEOUT_SECONDS: float = 10.0
    
    # Circuit Breaker Konfiguration
    CB_FAILURE_THRESHOLD: int = 5  # Fehler bis OPEN
    CB_RECOVERY_TIMEOUT: float = 30.0  # Sekunden im OPEN-Zustand

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Liefert gecachte Instanz der Einstellungen."""
    return Settings()
