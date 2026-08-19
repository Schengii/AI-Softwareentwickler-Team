"""
config.py – Zentrale Konfiguration für das KI-Softwareentwickler-Team (30 Spezialisten)
Multi-LLM & Tool Support: Gemini, Groq, DeepSeek, OpenRouter, Tavily, Hugging Face & Claude
"""

import os
from dotenv import load_dotenv

# Lade .env Datei
load_dotenv()

# ──────────────────────────────────────────
# API Keys
# ──────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
HUGGINGFACE_API_KEY: str = os.getenv("HUGGINGFACE_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ──────────────────────────────────────────
# Modell-Konfiguration (Multi-Provider Tiering)
# ──────────────────────────────────────────
HEAVY_MODEL: str = os.getenv("HEAVY_MODEL", "gemini-3.6-flash")
STANDARD_MODEL: str = os.getenv("STANDARD_MODEL", "gemini-3.6-flash")
LITE_MODEL: str = os.getenv("LITE_MODEL", "gemini-3.1-flash-lite")
TURBO_MODEL: str = os.getenv("TURBO_MODEL", "groq:openai/gpt-oss-120b")
REASONING_MODEL: str = os.getenv("REASONING_MODEL", "deepseek:deepseek-chat")

ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.6-flash")
DEFAULT_AGENT_MODEL: str = os.getenv("DEFAULT_AGENT_MODEL", "gemini-3.6-flash")

# Rollen- und aufgabengerechte Modell-Zuordnung (30 Spezialisten)
AGENT_MODELS: dict[str, str] = {
    # ── Phase 1: Führung, Planung & Recherche ──
    "team_lead":         os.getenv("TEAM_LEAD_MODEL",      HEAVY_MODEL),
    "planning_lead":     os.getenv("PLANNING_LEAD_MODEL",  HEAVY_MODEL),
    "dev_lead":          os.getenv("DEV_LEAD_MODEL",       HEAVY_MODEL),
    "creative_lead":     os.getenv("CREATIVE_LEAD_MODEL",  STANDARD_MODEL),
    "qa_lead":           os.getenv("QA_LEAD_MODEL",        STANDARD_MODEL),
    "governance_lead":   os.getenv("GOVERNANCE_LEAD_MODEL",HEAVY_MODEL),
    "product_owner":     os.getenv("PO_MODEL",             STANDARD_MODEL),
    "business_analyst":  os.getenv("BA_MODEL",             STANDARD_MODEL),
    "web_research":      os.getenv("WEB_RESEARCH_MODEL",   STANDARD_MODEL),

    # ── Phase 2: Architektur & FinOps (DeepSeek & Gemini) ──
    "architect":         os.getenv("ARCHITECT_MODEL",      "deepseek:deepseek-chat"),
    "finops":            os.getenv("FINOPS_MODEL",         STANDARD_MODEL),

    # ── Phase 3: Kern-Entwicklung (DeepSeek, Groq & Gemini) ──
    "backend":           os.getenv("BACKEND_MODEL",        "deepseek:deepseek-chat"),
    "frontend":          os.getenv("FRONTEND_MODEL",       STANDARD_MODEL),
    "database":          os.getenv("DATABASE_MODEL",       "deepseek:deepseek-chat"),
    "api_integration":   os.getenv("API_INTEGRATION_MODEL",STANDARD_MODEL),
    "data_engineer":     os.getenv("DATA_ENGINEER_MODEL",  STANDARD_MODEL),
    "mobile":            os.getenv("MOBILE_MODEL",         STANDARD_MODEL),
    "ml":                os.getenv("ML_MODEL",             "deepseek:deepseek-chat"),
    "prompt_engineer":   os.getenv("PROMPT_ENG_MODEL",     HEAVY_MODEL),
    "performance":       os.getenv("PERFORMANCE_MODEL",    "groq:openai/gpt-oss-120b"),

    # ── Phase 3: Design, Media, Content & Text ──
    "image_generator":   os.getenv("IMAGE_GEN_MODEL",      "huggingface:auto"),
    "copywriter":        os.getenv("COPYWRITER_MODEL",     STANDARD_MODEL),
    "ui_ux":             os.getenv("UI_UX_MODEL",          LITE_MODEL),
    "accessibility":     os.getenv("A11Y_MODEL",           LITE_MODEL),
    "i18n":              os.getenv("I18N_MODEL",           LITE_MODEL),
    "documentation":     os.getenv("DOCS_MODEL",           LITE_MODEL),
    "readme":            os.getenv("README_MODEL",         LITE_MODEL),
    "github":            os.getenv("GITHUB_MODEL",         LITE_MODEL),

    # ── Phase 3: Infrastruktur & Qualität ──
    "devops":            os.getenv("DEVOPS_MODEL",         STANDARD_MODEL),
    "tester":            os.getenv("TESTER_MODEL",         "groq:openai/gpt-oss-120b"),
    "security":          os.getenv("SECURITY_MODEL",       "deepseek:deepseek-chat"),
    "resilience_guard":  os.getenv("RESILIENCE_MODEL",     "groq:openai/gpt-oss-120b"),

    # ── Phase 4: Review, Refactoring, Compliance & Hygiene ──
    "code_reviewer":     os.getenv("CODE_REVIEWER_MODEL",  "deepseek:deepseek-chat"),
    "refactoring":       os.getenv("REFACTORING_MODEL",    "groq:openai/gpt-oss-120b"),
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
# Agentischer Werkzeug-Loop (echte Tool-Nutzung statt Ein-Schuss-Textgenerierung)
# ──────────────────────────────────────────
ENABLE_AGENT_TOOLS: bool = os.getenv("ENABLE_AGENT_TOOLS", "true").lower() in ("true", "1", "yes")
MAX_AGENT_TOOL_ITERATIONS: int = int(os.getenv("MAX_AGENT_TOOL_ITERATIONS", "6"))

# Nicht jeder Agent braucht dasselbe Iterationsbudget: Jede zusätzliche Iteration sendet
# die komplette bisherige Konversation (inkl. aller Werkzeug-Ergebnisse) erneut mit – das
# Budget wird daher pro Agenten-Rolle gestaffelt, um unnötigen Tokenverbrauch zu vermeiden,
# ohne code-schreibende Agenten einzuschränken, die echte Iteration brauchen.
AGENT_MAX_TOOL_ITERATIONS: dict[str, int] = {
    # Vorwiegend textbasierte Planungs-/Content-Rollen: meist 1-2 Dateien, wenig Iteration nötig
    "product_owner": 3, "business_analyst": 3, "web_research": 3, "finops": 3, "team_lead": 3,
    "copywriter": 3, "ui_ux": 3, "accessibility": 3, "i18n": 3, "documentation": 3,
    "readme": 3, "github": 2, "image_generator": 3,
    # Reine Prüf-/Review-Rollen: lesen viel, schreiben nichts -> weniger Iteration nötig
    "code_reviewer": 4, "compliance": 4, "project_cleaner": 3,
}

# ──────────────────────────────────────────
# Echte Verifikation (Dependency-Installation + tatsächliche Testausführung)
# ──────────────────────────────────────────
MAX_VERIFICATION_ITERATIONS: int = int(os.getenv("MAX_VERIFICATION_ITERATIONS", "2"))
DEPENDENCY_INSTALL_TIMEOUT_SECONDS: float = float(os.getenv("DEPENDENCY_INSTALL_TIMEOUT_SECONDS", "120"))
TEST_RUN_TIMEOUT_SECONDS: float = float(os.getenv("TEST_RUN_TIMEOUT_SECONDS", "60"))

# ──────────────────────────────────────────
# Fachbereichs-Teamleiter: echte Delegation & Konsolidierung per LLM-Call
# ──────────────────────────────────────────
ENABLE_DEPARTMENT_LEAD_EXECUTION: bool = os.getenv("ENABLE_DEPARTMENT_LEAD_EXECUTION", "true").lower() in ("true", "1", "yes")

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
    """Prüft ob mindestens ein API-Key vorhanden ist."""
    errors = []
    if not (GEMINI_API_KEY or GROQ_API_KEY or DEEPSEEK_API_KEY or OPENROUTER_API_KEY or HUGGINGFACE_API_KEY or ANTHROPIC_API_KEY):
        errors.append("Kein API-Key in der .env Datei gefunden")
    return errors
