import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "SynapseGate"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    DEBUG: bool = False
    
    # Security
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ALLOWED_HOSTS: list[str] = ["*"]
    CORS_ORIGINS: list[str] = ["*"]
    
    # Rate Limiting
    RATE_LIMIT_TOKENS: int = 100
    RATE_LIMIT_REFILL_RATE: float = 10.0  # tokens per second
    
    # Circuit Breaker
    CB_FAILURE_THRESHOLD: int = 5
    CB_RECOVERY_TIMEOUT: float = 30.0  # seconds
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache


@lru_cache
def get_settings() -> Settings:
    return Settings()
