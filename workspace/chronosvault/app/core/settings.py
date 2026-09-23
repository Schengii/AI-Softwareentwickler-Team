from pydantic_settings import BaseSettings, SettingsConfigDict
import secrets
from pydantic import Field

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

def get_settings() -> Settings:
    return Settings()
