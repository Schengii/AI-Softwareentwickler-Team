from typing import List
from pydantic import field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./auditlog.db"
    SECRET_KEY: str = "supersecret-fallback-key-for-dev-must-be-long-enough"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return v

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def validate_allowed_origins(cls, v: List[str], info: ValidationInfo) -> List[str]:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production":
            if "*" in v:
                raise ValueError("Wildcard '*' is not allowed in production ALLOWED_ORIGINS")
            if not v:
                raise ValueError("ALLOWED_ORIGINS must be defined in production")
        return v
