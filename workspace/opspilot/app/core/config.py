import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "OpsPilot"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "supersecret-dev-key-change-me")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DATABASE_URL: str = "sqlite+aiosqlite:///./opspilot.db"
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

settings = Settings()
