import os

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./taskpulse.db")
    USE_SQLITE: bool = True
    ALLOWED_ORIGINS: list[str] = ["https://app.taskpulse.example.com"]
    ALLOWED_CHECK_HOSTS: list[str] = ["api.example.com", "status.example.com"]
    # Standardwert für Tests, in Produktion via Umgebungsvariable überschreiben
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "test_secret")
    
    model_config = ConfigDict(env_file=".env")


settings = Settings()
