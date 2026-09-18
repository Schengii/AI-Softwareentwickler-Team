from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "aetherqueue"
    DATABASE_URL: str = "sqlite+aiosqlite:///./aetherqueue.db"
    DEBUG: bool = False
    WORKER_POLL_INTERVAL: float = 1.0
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
