# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    APP_NAME: str = "HyperionSentinel"
    API_V1_PREFIX: str = "/api/v1"
    REDIS_URL: str = "redis://localhost:6379/0"
    DEFAULT_RATE_LIMIT: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    CIRCUIT_BREAKER_THRESHOLD: int = 3

settings = Settings()
