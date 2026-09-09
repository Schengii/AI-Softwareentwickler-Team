import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Standard auf SQLite für lokale Entwicklung, falls kein DATABASE_URL gesetzt ist
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./governance.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        env_file = ".env"

settings = Settings()
