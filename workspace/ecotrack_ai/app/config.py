"""Zentrale Konfiguration für EcoTrack AI mittels Pydantic Settings."""

import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Anwendungsweite Einstellungen mit sicheren Dev-Defaults."""
    
    PROJECT_NAME: str = "EcoTrack AI Fleet Gateway"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Server-Konfiguration
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    
    # Sicherheit
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ALLOWED_ORIGINS: list[str] = ["*"]  # In Verbindung mit allow_credentials=False sicher
    
    # FinOps & Carbon Defaults (z. B. EUR pro Tonne CO2)
    CARBON_PRICE_EUR_PER_TONNE: float = 85.0
    DIESEL_LITER_CO2_KG: float = 2.68
    PETROL_LITER_CO2_KG: float = 2.31
    ELECTRIC_KWH_CO2_KG: float = 0.38
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Liefert die gecachte Instanz der Einstellungen."""
    return Settings()
