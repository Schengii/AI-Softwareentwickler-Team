import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./vault.db"
    MASTER_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ALGORITHM: str = "AES-256-GCM"
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
