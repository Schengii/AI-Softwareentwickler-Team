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
# Modell-Konfiguration: Claude + Gemini, nach tatsächlichem Aufgabenbedarf gestaffelt
# ──────────────────────────────────────────
# Jeder Agent bekommt nur so viel Modell, wie seine Aufgabe wirklich braucht:
# - LITE:     kleine, klar umrissene Aufgaben (Texte, Konfiguration, Übersetzung, Checklisten)
# - STANDARD: reguläre Feature-Entwicklung (Code, das funktionieren, aber keine tiefen
#             Architektur-Trade-offs abwägen muss)
# - HEAVY:    Architektur-/Sicherheits-/Review-Entscheidungen mit echten Trade-offs,
#             plus die Fachbereichs-Teamleiter, die die Qualität ihres Bereichs verantworten
# Der Hauptagent (Orchestrator) bekommt separat das stärkste Modell, da er über das
# gesamte Projekt hinweg nur 2x pro Lauf aufgerufen wird (Zerlegung + Synthese) und
# dort die höchste Qualität am meisten zählt – bei den 38 Fachrollen wäre das teuerste
# Modell für JEDEN Aufruf dagegen unnötig, wenn nur wenige Rollen es wirklich brauchen.
#
# Cross-Provider-Fallback: Ist ein Modell erschöpft (Quota/Rate-Limit) oder ein API-Key
# fehlt, springt core/llm_factory.py automatisch auf das jeweils andere Modell/den anderen
# Provider (Claude <-> Gemini) um – siehe MODEL_FALLBACKS in core/llm_factory.py.
GEMINI_LITE_MODEL: str = os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite")
GEMINI_STANDARD_MODEL: str = os.getenv("GEMINI_STANDARD_MODEL", "gemini-3.6-flash")
GEMINI_HEAVY_MODEL: str = os.getenv("GEMINI_HEAVY_MODEL", "gemini-pro-latest")

CLAUDE_LITE_MODEL: str = os.getenv("CLAUDE_LITE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_STANDARD_MODEL: str = os.getenv("CLAUDE_STANDARD_MODEL", "claude-sonnet-5")
CLAUDE_HEAVY_MODEL: str = os.getenv("CLAUDE_HEAVY_MODEL", "claude-opus-5")

# Primäre Zuordnung pro Komplexitätsstufe: Standard/Lite laufen primär über Gemini
# (schnell & günstig), Heavy primär über Claude (stärkeres Trade-off-Reasoning).
LITE_MODEL: str = GEMINI_LITE_MODEL
STANDARD_MODEL: str = GEMINI_STANDARD_MODEL
HEAVY_MODEL: str = CLAUDE_STANDARD_MODEL

ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", CLAUDE_HEAVY_MODEL)
DEFAULT_AGENT_MODEL: str = os.getenv("DEFAULT_AGENT_MODEL", STANDARD_MODEL)

# Rollen- und aufgabengerechte Modell-Zuordnung (33 Spezialisten + 5 Fachbereichsleiter)
AGENT_MODELS: dict[str, str] = {
    # ── Führung & Planung: Leads mit Architektur-/Qualitäts-Verantwortung -> HEAVY ──
    "planning_lead":     os.getenv("PLANNING_LEAD_MODEL",   HEAVY_MODEL),
    "dev_lead":          os.getenv("DEV_LEAD_MODEL",        HEAVY_MODEL),
    "governance_lead":   os.getenv("GOVERNANCE_LEAD_MODEL", HEAVY_MODEL),
    # Leads mit eher konsolidierender/koordinierender Aufgabe -> STANDARD reicht
    "creative_lead":     os.getenv("CREATIVE_LEAD_MODEL",   STANDARD_MODEL),
    "qa_lead":           os.getenv("QA_LEAD_MODEL",         STANDARD_MODEL),

    # ── Planung, Analyse & Recherche: klar umrissene Teilaufgaben -> STANDARD/LITE ──
    "team_lead":         os.getenv("TEAM_LEAD_MODEL",       STANDARD_MODEL),
    "product_owner":     os.getenv("PO_MODEL",              STANDARD_MODEL),
    "business_analyst":  os.getenv("BA_MODEL",              STANDARD_MODEL),
    "web_research":      os.getenv("WEB_RESEARCH_MODEL",    LITE_MODEL),   # fasst v.a. Suchergebnisse zusammen
    "finops":            os.getenv("FINOPS_MODEL",          LITE_MODEL),   # größtenteils Rechen-/Checklisten-Aufgabe

    # ── Architektur & Kern-Entwicklung mit echten Trade-offs -> HEAVY ──
    "architect":         os.getenv("ARCHITECT_MODEL",       HEAVY_MODEL),
    "backend":           os.getenv("BACKEND_MODEL",         HEAVY_MODEL),
    "database":          os.getenv("DATABASE_MODEL",        HEAVY_MODEL),
    "ml":                os.getenv("ML_MODEL",               HEAVY_MODEL),
    "prompt_engineer":   os.getenv("PROMPT_ENG_MODEL",      HEAVY_MODEL),

    # ── Reguläre Feature-Entwicklung -> STANDARD ──
    "frontend":          os.getenv("FRONTEND_MODEL",        STANDARD_MODEL),
    "api_integration":   os.getenv("API_INTEGRATION_MODEL", STANDARD_MODEL),
    "data_engineer":     os.getenv("DATA_ENGINEER_MODEL",   STANDARD_MODEL),
    "mobile":            os.getenv("MOBILE_MODEL",          STANDARD_MODEL),
    "devops":            os.getenv("DEVOPS_MODEL",          STANDARD_MODEL),
    "tester":            os.getenv("TESTER_MODEL",          STANDARD_MODEL),
    "resilience_guard":  os.getenv("RESILIENCE_MODEL",      STANDARD_MODEL),
    "performance":       os.getenv("PERFORMANCE_MODEL",     STANDARD_MODEL),
    "compliance":        os.getenv("COMPLIANCE_MODEL",      STANDARD_MODEL),
    "retrospective":     os.getenv("RETROSPECTIVE_MODEL",   STANDARD_MODEL),

    # ── Sicherheits-/Qualitäts-Entscheidungen mit echten Trade-offs -> HEAVY ──
    "security":          os.getenv("SECURITY_MODEL",        HEAVY_MODEL),
    "code_reviewer":     os.getenv("CODE_REVIEWER_MODEL",   HEAVY_MODEL),
    "refactoring":       os.getenv("REFACTORING_MODEL",     HEAVY_MODEL),
    "agent_trainer":     os.getenv("AGENT_TRAINER_MODEL",   HEAVY_MODEL),

    # ── Kleine, klar umrissene Aufgaben -> LITE ──
    "image_generator":   os.getenv("IMAGE_GEN_MODEL",       LITE_MODEL),
    "copywriter":        os.getenv("COPYWRITER_MODEL",      LITE_MODEL),
    "ui_ux":             os.getenv("UI_UX_MODEL",           LITE_MODEL),
    "accessibility":     os.getenv("A11Y_MODEL",            LITE_MODEL),
    "i18n":              os.getenv("I18N_MODEL",            LITE_MODEL),
    "documentation":     os.getenv("DOCS_MODEL",            LITE_MODEL),
    "readme":            os.getenv("README_MODEL",          LITE_MODEL),
    "github":            os.getenv("GITHUB_MODEL",          LITE_MODEL),
    "project_cleaner":   os.getenv("PROJECT_CLEANER_MODEL", LITE_MODEL),
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
