"""
config.py – Zentrale Konfiguration für das KI-Softwareentwickler-Team
"""

import os
from dotenv import load_dotenv

# Lade .env Datei
load_dotenv()

# ──────────────────────────────────────────
# API Keys
# ──────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ──────────────────────────────────────────
# Modell-Konfiguration
# ──────────────────────────────────────────
ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.6-flash")
DEFAULT_AGENT_MODEL: str = os.getenv("DEFAULT_AGENT_MODEL", "gemini-3.6-flash")

# Agenten-spezifische Modelle (kann überschrieben werden)
AGENT_MODELS: dict[str, str] = {
    "ui_ux":         os.getenv("UI_UX_MODEL",    DEFAULT_AGENT_MODEL),
    "frontend":      os.getenv("FRONTEND_MODEL", DEFAULT_AGENT_MODEL),
    "backend":       os.getenv("BACKEND_MODEL",  DEFAULT_AGENT_MODEL),
    "database":      os.getenv("DATABASE_MODEL", DEFAULT_AGENT_MODEL),
    "devops":        os.getenv("DEVOPS_MODEL",   DEFAULT_AGENT_MODEL),
    "tester":        os.getenv("TESTER_MODEL",   DEFAULT_AGENT_MODEL),
    "documentation": os.getenv("DOCS_MODEL",     DEFAULT_AGENT_MODEL),
    "security":      os.getenv("SECURITY_MODEL", DEFAULT_AGENT_MODEL),
}

# ──────────────────────────────────────────
# Sprache & Verhalten
# ──────────────────────────────────────────
AGENT_LANGUAGE: str = os.getenv("AGENT_LANGUAGE", "de")

# Maximale Token-Anzahl pro Agenten-Antwort
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "8192"))

# Temperatur (0.0 = deterministisch, 1.0 = kreativ)
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.7"))

# ──────────────────────────────────────────
# Pfade
# ──────────────────────────────────────────
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR: str = os.path.join(BASE_DIR, "prompts")
MEMORY_DIR: str = os.path.join(BASE_DIR, "memory")

# ──────────────────────────────────────────
# Validierung
# ──────────────────────────────────────────
def validate_config() -> list[str]:
    """Prüft ob alle notwendigen Konfigurationen vorhanden sind."""
    errors = []
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY fehlt in der .env Datei")
    return errors
