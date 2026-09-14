from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "DevPulse"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./devpulse.db"
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache


@lru_cache
def get_settings() -> Settings:
    return Settings()
