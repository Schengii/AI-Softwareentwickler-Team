from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEBUG: bool = False
    # Rate Limiting
    RATE_LIMIT_TOKENS: int = 100
    RATE_LIMIT_REFILL_RATE: float = 10.0 # tokens per second
    # Circuit Breaker
    CB_FAILURE_THRESHOLD: int = 5
    CB_RECOVERY_TIMEOUT: float = 30.0
    
    # Routing config: service_name -> base_url
    ROUTES: dict[str, str] = {
        "service_a": "http://localhost:8001",
        "service_b": "http://localhost:8002"
    }

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
