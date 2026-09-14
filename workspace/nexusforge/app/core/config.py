import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "NexusForge"
    DATABASE_URL: str = "sqlite+aiosqlite:///./nexusforge.db"
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache


@lru_cache
def get_settings() -> Settings:
    return Settings()
