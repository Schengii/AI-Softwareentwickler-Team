from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "VaultGuard"
    ENVIRONMENT: str = "development"
    
    # Database Settings
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///:memory:",
        description="Async Database Connection String"
    )
    POSTGRES_USER: str = "vaultguard"
    POSTGRES_PASSWORD: str = "vaultguard_pass_2025"
    POSTGRES_DB: str = "vaultguard"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Security Settings
    SECRET_KEY: str = Field(
        ...,
        min_length=32,
        description="Secret key for JWT and encryption derivation"
    )
    ENCRYPTION_SALT: str = Field(
        ...,
        min_length=16,
        description="Salt for KDF key derivation"
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long for security.")
        return v


settings = Settings()
