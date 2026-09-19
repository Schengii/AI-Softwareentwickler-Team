import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "sentinedge"
    DATABASE_URL: str = "sqlite+aiosqlite:///./sentinedge.db"
    MASTER_KEY: str = Field(default_factory=lambda: secrets.token_hex(32)) # 32 bytes hex for AES-256
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache


@lru_cache
def get_settings() -> Settings:
    return Settings()
