import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "DevPulse"
    
    # Datenbank Konfiguration
    # USE_SQLITE: Wenn True, wird eine In-Memory SQLite Datenbank genutzt (für Tests/Dev)
    # Wenn False, wird DATABASE_URL verwendet (für Produktion/PostgreSQL)
    USE_SQLITE: bool = os.getenv("USE_SQLITE", "False").lower() == "true"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/devpulse")
    SQLITE_URL: str = "sqlite+aiosqlite:///:memory:"

    class Config:
        case_sensitive = True

settings = Settings()
