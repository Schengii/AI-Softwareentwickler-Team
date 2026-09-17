from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./sentinel.db"
    DEBUG: bool = False
    BUFFER_MAX_SIZE: int = 1000
    Z_SCORE_THRESHOLD: float = 3.0
    WINDOW_SIZE: int = 50
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

def get_settings() -> Settings:
    return Settings()
