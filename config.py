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
    # Phase 1: Planung & Produkt
    "business_analyst":  os.getenv("BA_MODEL",             DEFAULT_AGENT_MODEL),
    "product_owner":     os.getenv("PO_MODEL",             DEFAULT_AGENT_MODEL),

    # Phase 2: Architektur & FinOps
    "architect":         os.getenv("ARCHITECT_MODEL",      DEFAULT_AGENT_MODEL),
    "finops":            os.getenv("FINOPS_MODEL",         DEFAULT_AGENT_MODEL),

    # Phase 3: Entwicklung & Implementierung
    "ui_ux":             os.getenv("UI_UX_MODEL",          DEFAULT_AGENT_MODEL),
    "frontend":          os.getenv("FRONTEND_MODEL",       DEFAULT_AGENT_MODEL),
    "backend":           os.getenv("BACKEND_MODEL",        DEFAULT_AGENT_MODEL),
    "database":          os.getenv("DATABASE_MODEL",       DEFAULT_AGENT_MODEL),
    "api_integration":   os.getenv("API_INTEGRATION_MODEL",DEFAULT_AGENT_MODEL),
    "data_engineer":     os.getenv("DATA_ENGINEER_MODEL",  DEFAULT_AGENT_MODEL),
    "mobile":            os.getenv("MOBILE_MODEL",         DEFAULT_AGENT_MODEL),
    "ml":                os.getenv("ML_MODEL",             DEFAULT_AGENT_MODEL),
    "performance":       os.getenv("PERFORMANCE_MODEL",    DEFAULT_AGENT_MODEL),
    "i18n":              os.getenv("I18N_MODEL",           DEFAULT_AGENT_MODEL),

    # Phase 3: Infrastruktur & Qualität
    "devops":            os.getenv("DEVOPS_MODEL",         DEFAULT_AGENT_MODEL),
    "tester":            os.getenv("TESTER_MODEL",         DEFAULT_AGENT_MODEL),
    "documentation":     os.getenv("DOCS_MODEL",           DEFAULT_AGENT_MODEL),
    "security":          os.getenv("SECURITY_MODEL",       DEFAULT_AGENT_MODEL),

    # Phase 4: Review, Refactoring & Compliance
    "code_reviewer":     os.getenv("CODE_REVIEWER_MODEL",  DEFAULT_AGENT_MODEL),
    "refactoring":       os.getenv("REFACTORING_MODEL",    DEFAULT_AGENT_MODEL),
    "compliance":        os.getenv("COMPLIANCE_MODEL",     DEFAULT_AGENT_MODEL),

    # Utility-Agenten
    "readme":            os.getenv("README_MODEL",         DEFAULT_AGENT_MODEL),
    "github":            os.getenv("GITHUB_MODEL",         DEFAULT_AGENT_MODEL),
}

# ──────────────────────────────────────────
# Sprache & Verhalten
# ──────────────────────────────────────────
AGENT_LANGUAGE: str = os.getenv("AGENT_LANGUAGE", "de")

# Maximale Token-Anzahl pro Agenten-Antwort
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "8192"))

# Temperatur (0.0 = deterministisch, 1.0 = kreativ)
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.7"))

# Iterative Review & Fix Settings
MAX_REVIEW_ITERATIONS: int = int(os.getenv("MAX_REVIEW_ITERATIONS", "2"))
AUTO_SAVE_WORKSPACE: bool = os.getenv("AUTO_SAVE_WORKSPACE", "true").lower() in ("true", "1", "yes")

# ──────────────────────────────────────────
# Pfade
# ──────────────────────────────────────────
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR: str = os.path.join(BASE_DIR, "prompts")
MEMORY_DIR: str = os.path.join(BASE_DIR, "memory")
WORKSPACE_DIR: str = os.path.join(BASE_DIR, "workspace")

# ──────────────────────────────────────────
# Validierung
# ──────────────────────────────────────────
def validate_config() -> list[str]:
    """Prüft ob alle notwendigen Konfigurationen vorhanden sind."""
    errors = []
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY fehlt in der .env Datei")
    return errors
