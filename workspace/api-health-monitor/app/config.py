from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./health_monitor.db"
    CHECK_INTERVAL: int = 60  # seconds
    WEBHOOK_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"

settings = Settings()
