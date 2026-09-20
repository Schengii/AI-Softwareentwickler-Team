"""Konfigurationsmanagement für CacheGrid Proxy."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Zentrale Anwendungseinstellungen mit sicheren Dev-Defaults."""

    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = False

    # Cache Limits
    MEMORY_MAX_ITEMS: int = Field(default=1000, description="Maximale Anzahl Einträge im RAM LRU")
    DEFAULT_TTL_SECONDS: float = Field(default=300.0, description="Standard-TTL in Sekunden")
    
    # Disk Tiering
    ENABLE_DISK_TIER: bool = Field(default=True, description="Disk-Tiering aktivieren")
    DISK_STORAGE_PATH: str = Field(default="./data/cache_disk", description="Verzeichnis für Disk-Cache")
    
    # Write Behind
    ENABLE_WRITE_BEHIND: bool = Field(default=True, description="Write-Behind Persistierung nutzen")
    WRITE_BEHIND_FLUSH_INTERVAL: float = Field(default=0.5, description="Intervall für Batch-Flushing in Sekunden")
    WRITE_BEHIND_BATCH_SIZE: int = Field(default=50, description="Maximale Batchgröße beim Schreiben")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Gibt die gecachte Konfigurationsinstanz zurück."""
    return Settings()
