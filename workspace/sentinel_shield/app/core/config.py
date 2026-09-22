from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, List

class Settings(BaseSettings):
    PROJECT_NAME: str = "sentinel_shield"
    DEBUG: bool = False
    SECRET_KEY: str = "dev-secret-key-change-in-prod"
    RATE_LIMIT_REQUESTS: int = 10
    RATE_LIMIT_WINDOW: int = 60
    CIRCUIT_FAILURE_THRESHOLD: int = 5
    CIRCUIT_RECOVERY_TIMEOUT: int = 30
    DOWNSTREAM_URLS: Dict[str, str] = {"default": "http://localhost:8080"}
    ALLOWED_ORIGINS: List[str] = ["*"]
    ALLOWED_HOSTS: List[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()
