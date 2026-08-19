# app/core/config.py
from pydantic import BaseSettings, AnyUrl, validator
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "Jobsuche"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"
    DATABASE_URL: AnyUrl
    REDIS_URL: str = "redis://localhost:6379/0"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    ALLOWED_ORIGINS: List[AnyUrl] = ["http://localhost:3000", "https://jobsuche.example.com"]

    @validator("SECRET_KEY")
    def secret_key_must_be_set(cls, v):
        if not v:
            raise ValueError("SECRET_KEY muss gesetzt sein")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
