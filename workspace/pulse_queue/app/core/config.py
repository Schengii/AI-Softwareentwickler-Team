from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import secrets

class Settings(BaseSettings):
    PROJECT_NAME: str = "pulse_queue"
    API_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    DATABASE_URL: str = "sqlite+aiosqlite:///./queue.db"
    DEBUG: bool = False
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
