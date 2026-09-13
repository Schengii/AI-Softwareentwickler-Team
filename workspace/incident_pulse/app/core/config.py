from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "IncidentPulse"
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:8000", "http://127.0.0.1:8000"])
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
