import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./taskpulse.db")
    USE_SQLITE: bool = True
    ALLOWED_ORIGINS: list[str] = ["https://app.taskpulse.example.com"]
    ALLOWED_CHECK_HOSTS: list[str] = ["api.example.com", "status.example.com"]
    
    class Config:
        env_file = ".env"

settings = Settings()
