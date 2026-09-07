from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Telemetrie-Dashboard"
    API_V1_STR: str = "/api/v1"
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "test"]
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/telemetry"
    REDIS_URL: str = "redis://localhost"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    SECRET_KEY: str = "super-secret-key-change-me"  # In Produktion per env setzen

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
