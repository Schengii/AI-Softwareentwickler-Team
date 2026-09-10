from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    SECRET_KEY: str = "dev-only-default-secret-key-must-be-at-least-32-chars-long"
    ALGORITHM: str = "HS256"
    API_KEY: str = "dev-only-default-api-key-must-be-at-least-40-chars-long"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "https://app.logipulse.com"]

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32: raise ValueError("SECRET_KEY too short")
        return v

    @field_validator("API_KEY")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if len(v) < 40: raise ValueError("API_KEY too short")
        return v

@lru_cache
def get_settings() -> Settings:
    return Settings()
