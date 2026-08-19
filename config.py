"""
config.py – Zentrale Konfiguration für das KI-Softwareentwickler-Team (30 Spezialisten)
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
# Modell-Konfiguration (Tiered & Multi-Provider)
# ──────────────────────────────────────────
HEAVY_MODEL: str = os.getenv("HEAVY_MODEL", "gemini-2.5-pro")
STANDARD_MODEL: str = os.getenv("STANDARD_MODEL", "gemini-2.5-flash")
LITE_MODEL: str = os.getenv("LITE_MODEL", "gemini-2.5-flash-lite")

ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", STANDARD_MODEL)
DEFAULT_AGENT_MODEL: str = os.getenv("DEFAULT_AGENT_MODEL", STANDARD_MODEL)

# Rollen- und aufgabengerechte Modell-Zuordnung (30 Spezialisten)
AGENT_MODELS: dict[str, str] = {
    # ── Phase 1: Führung, Planung & Recherche ──
    "team_lead":         os.getenv("TEAM_LEAD_MODEL",      HEAVY_MODEL),
    "product_owner":     os.getenv("PO_MODEL",             STANDARD_MODEL),
    "business_analyst":  os.getenv("BA_MODEL",             STANDARD_MODEL),
    "web_research":      os.getenv("WEB_RESEARCH_MODEL",   STANDARD_MODEL),

    # ── Phase 2: Architektur & FinOps ──
    "architect":         os.getenv("ARCHITECT_MODEL",      HEAVY_MODEL),
    "finops":            os.getenv("FINOPS_MODEL",         STANDARD_MODEL),

    # ── Phase 3: Kern-Entwicklung ──
    "backend":           os.getenv("BACKEND_MODEL",        STANDARD_MODEL),
    "frontend":          os.getenv("FRONTEND_MODEL",       STANDARD_MODEL),
    "database":          os.getenv("DATABASE_MODEL",       STANDARD_MODEL),
    "api_integration":   os.getenv("API_INTEGRATION_MODEL",STANDARD_MODEL),
    "data_engineer":     os.getenv("DATA_ENGINEER_MODEL",  STANDARD_MODEL),
    "mobile":            os.getenv("MOBILE_MODEL",         STANDARD_MODEL),
    "ml":                os.getenv("ML_MODEL",             STANDARD_MODEL),
    "performance":       os.getenv("PERFORMANCE_MODEL",    STANDARD_MODEL),

    # ── Phase 3: Design, Media, Content & Text ──
    "image_generator":   os.getenv("IMAGE_GEN_MODEL",      STANDARD_MODEL),
    "copywriter":        os.getenv("COPYWRITER_MODEL",     STANDARD_MODEL),
    "ui_ux":             os.getenv("UI_UX_MODEL",          LITE_MODEL),
    "i18n":              os.getenv("I18N_MODEL",           LITE_MODEL),
    "documentation":     os.getenv("DOCS_MODEL",           LITE_MODEL),
    "readme":            os.getenv("README_MODEL",         LITE_MODEL),
    "github":            os.getenv("GITHUB_MODEL",         LITE_MODEL),

    # ── Phase 3: Infrastruktur & Qualität ──
    "devops":            os.getenv("DEVOPS_MODEL",         STANDARD_MODEL),
    "tester":            os.getenv("TESTER_MODEL",         STANDARD_MODEL),
    "security":          os.getenv("SECURITY_MODEL",       STANDARD_MODEL),

    # ── Phase 4: Review, Refactoring, Compliance & Hygiene ──
    "code_reviewer":     os.getenv("CODE_REVIEWER_MODEL",  HEAVY_MODEL),
    "refactoring":       os.getenv("REFACTORING_MODEL",    STANDARD_MODEL),
    "compliance":        os.getenv("COMPLIANCE_MODEL",     STANDARD_MODEL),
    "project_cleaner":   os.getenv("PROJECT_CLEANER_MODEL",LITE_MODEL),

    # ── Phase 5: Ausbildung & Retrospektive ──
    "agent_trainer":     os.getenv("AGENT_TRAINER_MODEL",  HEAVY_MODEL),
    "retrospective":     os.getenv("RETROSPECTIVE_MODEL",  STANDARD_MODEL),
}

# ──────────────────────────────────────────
# Sprache & Verhalten
# ──────────────────────────────────────────
AGENT_LANGUAGE: str = os.getenv("AGENT_LANGUAGE", "de")
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "4096"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.4"))

# Iterative Review & Fix Settings
MAX_REVIEW_ITERATIONS: int = int(os.getenv("MAX_REVIEW_ITERATIONS", "1"))
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
    """Prüft ob API-Keys vorhanden sind."""
    errors = []
    if not GEMINI_API_KEY and not ANTHROPIC_API_KEY:
        errors.append("Weder GEMINI_API_KEY noch ANTHROPIC_API_KEY in der .env Datei gefunden")
    return errors
