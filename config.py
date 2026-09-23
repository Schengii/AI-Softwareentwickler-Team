"""
config.py – Zentrale Konfiguration für das KI-Softwareentwickler-Team (30 Spezialisten)
Multi-LLM & Tool Support: Gemini, Groq, DeepSeek, OpenRouter, Tavily, Hugging Face & Claude
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Lade .env Datei
load_dotenv()

# ──────────────────────────────────────────
# API Keys
# ──────────────────────────────────────────
def _collect_gemini_api_keys() -> list[str]:
    """Sammelt alle konfigurierten Gemini-Keys (kommagetrennt in GEMINI_API_KEY oder als GEMINI_API_KEY_1..N / GEMINI_API_KEY_FALLBACK_1..N)."""
    keys: list[str] = []
    primary = os.getenv("GEMINI_API_KEY", "").strip()
    if primary:
        for part in primary.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
    for i in range(1, 10):
        for candidate_var in (f"GEMINI_API_KEY_{i}", f"GEMINI_API_KEY_FALLBACK_{i}"):
            k = os.getenv(candidate_var, "").strip()
            if k and k not in keys:
                keys.append(k)
    return keys


GEMINI_API_KEYS: list[str] = _collect_gemini_api_keys()
GEMINI_API_KEY: str = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
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
#
# Anthropic bietet – anders als Gemini – KEIN dauerhaftes Gratis-Kontingent (nur ein
# einmaliges kleines Startguthaben für neue Accounts). Solange kein ANTHROPIC_API_KEY
# gesetzt ist, springt core/llm_factory.py bei allen HEAVY-Aufgaben deshalb zunächst auf
# GROQ_HEAVY_MODEL – ein starkes, aber tatsächlich kostenloses Open-Weight-Modell mit
# großzügigem Rate-Limit – und erst danach auf die Gemini-Standard-Stufe aus, statt
# sofort auf das schwächste verfügbare Modell abzurutschen.
# REALER FUND (2026-09-12): gemini-3.8-flash hat im kostenlosen Google AI Studio Free-Tier ein
# extrem enges Vorschau-Kontingent von nur 20 Anfragen/Tag (QuotaFailure:
# GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20). gemini-3.6-flash ist das
# voll produktive, stabile Flash-Modell mit vollem Free-Tier-Kontingent (15 RPM, 1 Mio Kontext).
# Token- & Kostenoptimierung (Gemini API Pay-As-You-Go): gemini-pro-latest verursacht das
# 15- bis 25-fache der Kosten von Flash. Im Regelbetrieb standardmäßig gemini-3.8-flash für HEAVY,
# um 85-90% der API-Kosten einzusparen.
GEMINI_LITE_MODEL: str = os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite")
GEMINI_STANDARD_MODEL: str = os.getenv("GEMINI_STANDARD_MODEL", "gemini-3.6-flash")
GEMINI_HEAVY_MODEL: str = os.getenv("GEMINI_HEAVY_MODEL", "gemini-3.8-flash")

CLAUDE_LITE_MODEL: str = os.getenv("CLAUDE_LITE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_STANDARD_MODEL: str = os.getenv("CLAUDE_STANDARD_MODEL", "claude-sonnet-5")
CLAUDE_HEAVY_MODEL: str = os.getenv("CLAUDE_HEAVY_MODEL", "claude-opus-5")

# Kostenlose Ausweich-Stufe für HEAVY-Aufgaben, falls kein ANTHROPIC_API_KEY vorhanden ist.
GROQ_HEAVY_MODEL: str = os.getenv("GROQ_HEAVY_MODEL", "groq:openai/gpt-oss-120b")

# Innerhalb-Groq-Ausweichkette (core/llm_factory.py GroqClient): `openai/gpt-oss-120b` hat auf
# Groqs kostenlosem Free-Tier nur ein hartes 8.000-Tokens-pro-Minute-Limit (TPM) - ein einzelner
# großer System-Prompt + Werkzeugkatalog reicht bereits aus, um Error 413 "Request too large"
# auszulösen (real beobachtet: 8.685 angeforderte gegen 8.000 erlaubte Tokens, logs/runs/
# 20260911_211719_chronos_queue.jsonl). `llama-3.3-70b-versatile`/`llama-3.1-8b-instant` erlauben
# auf demselben Free-Tier 30.000-60.000 TPM und sind damit deutlich robuster gegen genau diesen
# Fehler. Scheitert `GROQ_HEAVY_MODEL` an einem TPM-/Größen-Fehler (413 oder 429 "tokens per
# minute"), probiert GroqClient VOR einem Provider-Wechsel zunächst diese Modelle - alle
# weiterhin echte, kostenlose Groq-Kontingente, kein zusätzlicher API-Key nötig.
#
# BEKANNTER FUND (logs/runs/20260912_082145_sentinelgrid.jsonl): `llama-3.3-70b-versatile`
# und `llama-3.1-8b-instant` existieren auf dem aktuellen Groq-Endpoint nicht mehr
# (Error 404 "does not exist or you do not have access to it") und rissen die gesamte
# Fallback-Kette ab, statt ein TPM-Limit abzufangen. Ersetzt durch aktuell verfügbare,
# weiterhin kostenlose Groq-Modelle.
GROQ_FALLBACK_MODELS: tuple[str, ...] = tuple(
    m.strip() for m in os.getenv(
        "GROQ_FALLBACK_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-20b,qwen/qwen3.6-27b",
    ).split(",") if m.strip()
)

# Proaktive Rate-Begrenzung (core/rate_limiter.py): verhindert, dass viele parallele Agenten
# (asyncio.gather bei 3+-Mitglieder-Fachbereichen) Gemini gleichzeitig anstürmen und dessen
# Minutenlimit dadurch ERST auslösen. Bewusst konservativ unter typischen kostenlosen
# Gemini-RPM-Limits gehalten (Reserve für gleichzeitige Nutzung außerhalb dieses Frameworks).
#
# BEKANNTER FUND (logs/runs/20260912_082145_sentinelgrid.jsonl): Googles tatsächliches
# Free-Tier-Limit für Gemini Flash liegt bei 5 Requests/Minute, nicht 12 - der bisherige
# Standardwert löste massenhaft 429 RESOURCE_EXHAUSTED aus. Auf 4 gesenkt, um dem
# Sliding-Window-Limiter Reserve unter dem tatsächlichen Limit zu lassen.
GEMINI_MAX_CALLS_PER_MINUTE: int = int(os.getenv("GEMINI_MAX_CALLS_PER_MINUTE", "4"))

# Primäre Zuordnung pro Komplexitätsstufe: Standard/Lite laufen primär über Gemini
# (schnell & günstig), Heavy primär über Claude (stärkeres Trade-off-Reasoning).
#
# KRITISCHER FUND (KI-Team-Masterplan-Analyse, 09.09.2026): HEAVY_MODEL zeigte BEDINGUNGSLOS
# auf Claude - auch in Setups ohne ANTHROPIC_API_KEY. Genau das war hier der Fall, mit
# messbaren Folgen: 13 Rollen (architect, backend, database, security, code_reviewer,
# refactoring, compliance, ml, prompt_engineer, agent_trainer sowie die drei Leads) UND der
# Orchestrator hatten damit KEIN funktionierendes Primärmodell. In memory/cost_history.json
# stand über 5.368 Calls hinweg kein einziger Claude-Aufruf, während 4.380 Calls (81,6%) auf
# der SCHWÄCHSTEN Stufe `gemini-3.1-flash-lite` landeten - jene Stufe, die laut der Zuordnung
# unten ausdrücklich nur für "kleine, klar umrissene Aufgaben" wie readme/github gedacht ist.
# Auffällig konsistent dazu: Die schlechtesten Erfolgsquoten hatten exakt die HEAVY-Rollen
# (architect 68%, backend 74%), die besten die LITE-Rollen (project_cleaner 90%).
#
# Die Fallback-Kette in core/llm_factory.py fing das zwar auf - aber erst NACH einem
# vergeblichen Anlauf und ohne dass irgendwo sichtbar wurde, dass die gesamte Tier-Strategie
# zur Laufzeit wirkungslos ist. Ein Primärmodell, für das kein Schlüssel existiert, ist keine
# Konfiguration, sondern eine Fehlkonfiguration. `_first_available_model()` wählt deshalb pro
# Stufe das stärkste Modell, dessen Provider TATSÄCHLICH einen Schlüssel hat.
def _first_available_model(*candidates: tuple[str, str]) -> str:
    """
    Erstes Modell, dessen Provider-Schlüssel gesetzt ist. `candidates` ist eine Folge von
    (api_key, model_name)-Paaren in absteigender Präferenz; das letzte Paar dient als
    bedingungsloser Rückfall, damit hier nie ein leerer Modellname herauskommt (eine fehlende
    Konfiguration soll später an einer aussagekräftigen Stelle auffallen, nicht als leerer
    String durch das halbe Framework wandern).
    """
    for api_key, model_name in candidates:
        if api_key:
            return model_name
    return candidates[-1][1] if candidates else ""


LITE_MODEL: str = os.getenv("LITE_MODEL", "") or _first_available_model(
    (GEMINI_API_KEY, GEMINI_LITE_MODEL),
    (GROQ_API_KEY, GROQ_HEAVY_MODEL),
    (ANTHROPIC_API_KEY, CLAUDE_LITE_MODEL),
    ("", GEMINI_LITE_MODEL),
)
STANDARD_MODEL: str = os.getenv("STANDARD_MODEL", "") or _first_available_model(
    (GEMINI_API_KEY, GEMINI_STANDARD_MODEL),
    (GROQ_API_KEY, GROQ_HEAVY_MODEL),
    (ANTHROPIC_API_KEY, CLAUDE_STANDARD_MODEL),
    ("", GEMINI_STANDARD_MODEL),
)
# Reihenfolge für HEAVY: Claude zuerst (stärkstes Trade-off-Reasoning), sonst Groq mit einem
# starken Open-Weight-Modell und echtem kostenlosem Kontingent - dieselbe Rangfolge, die
# core/llm_factory.py.ClaudeClient._free_heavy_fallback_client() bereits als Ausweichkette
# implementiert. Der Unterschied: Sie greift jetzt VOR dem ersten vergeblichen Anlauf.
HEAVY_MODEL: str = os.getenv("HEAVY_MODEL", "") or _first_available_model(
    (ANTHROPIC_API_KEY, CLAUDE_STANDARD_MODEL),
    (GROQ_API_KEY, GROQ_HEAVY_MODEL),
    (DEEPSEEK_API_KEY, "deepseek:deepseek-chat"),
    (OPENROUTER_API_KEY, "openrouter:openrouter/auto"),
    (GEMINI_API_KEY, GEMINI_HEAVY_MODEL),
    ("", CLAUDE_STANDARD_MODEL),
)

# Der Orchestrator litt unter demselben Defekt wie HEAVY_MODEL (siehe oben): Er zeigte
# bedingungslos auf claude-opus-5, obwohl ohne ANTHROPIC_API_KEY nie ein Claude-Aufruf möglich
# war. Da JEDE Aufgabenzerlegung und JEDE Abschluss-Synthese über ihn läuft, scheiterte damit
# der wichtigste Einzelaufruf des gesamten Laufs zuverlässig im ersten Anlauf.
ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "") or _first_available_model(
    (ANTHROPIC_API_KEY, CLAUDE_HEAVY_MODEL),
    (GROQ_API_KEY, GROQ_HEAVY_MODEL),
    (DEEPSEEK_API_KEY, "deepseek:deepseek-chat"),
    (OPENROUTER_API_KEY, "openrouter:openrouter/auto"),
    (GEMINI_API_KEY, GEMINI_HEAVY_MODEL),
    ("", CLAUDE_HEAVY_MODEL),
)
DEFAULT_AGENT_MODEL: str = os.getenv("DEFAULT_AGENT_MODEL", STANDARD_MODEL)

# Rollen- und aufgabengerechte Modell-Zuordnung (33 Spezialisten + 5 Fachbereichsleiter)
AGENT_MODELS: dict[str, str] = {
    # ── Führung & Planung: Leads mit Architektur-/Qualitäts-Verantwortung -> HEAVY ──
    "planning_lead":     os.getenv("PLANNING_LEAD_MODEL",   HEAVY_MODEL),
    # KRITISCHER FUND (CertPulse, 2026-09-12): dev_lead stand hier bisher auf HEAVY_MODEL. Ohne
    # ANTHROPIC_API_KEY (dieses Setup) löste das über _free_heavy_fallback_client()
    # GROQ_HEAVY_MODEL ("openai/gpt-oss-120b") auf - dessen striktes 8.000-TPM-Limit auf Groqs
    # Free-Tier reicht für den Fachbereichs-Delegations-Prompt (3 ADRs + Interface Contract +
    # Agenten-Beschreibungen) nicht annähernd aus (real beobachtet: HTTP 413/429 "tokens per
    # minute"). Die Rolle ist rein koordinierend (delegiert/konsolidiert, siehe
    # agents/department_lead_agent.py) - dafür reicht STANDARD_MODEL (primär Gemini Flash mit
    # 1-Mio-Token-Fenster, kein 8.000-TPM-Limit) locker, ohne die Groq-TPM-Falle überhaupt zu
    # betreten. Ein expliziter DEV_LEAD_MODEL-Override (z.B. auf HEAVY_MODEL) bleibt möglich,
    # siehe get_model_for_agent()/AGENT_MODEL_ENV_KEYS.
    "dev_lead":          os.getenv("DEV_LEAD_MODEL",        STANDARD_MODEL),
    "governance_lead":   os.getenv("GOVERNANCE_LEAD_MODEL", HEAVY_MODEL),
    # Leads mit eher konsolidierender/koordinierender Aufgabe -> STANDARD reicht
    "design_lead":       os.getenv("DESIGN_LEAD_MODEL",     os.getenv("CREATIVE_LEAD_MODEL", STANDARD_MODEL)),
    "content_lead":      os.getenv("CONTENT_LEAD_MODEL",    os.getenv("CREATIVE_LEAD_MODEL", STANDARD_MODEL)),
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
    "retrospective":     os.getenv("RETROSPECTIVE_MODEL",   STANDARD_MODEL),

    # ── Sicherheits-/Qualitäts-Entscheidungen mit echten Trade-offs -> HEAVY ──
    "security":          os.getenv("SECURITY_MODEL",        HEAVY_MODEL),
    "code_reviewer":     os.getenv("CODE_REVIEWER_MODEL",   HEAVY_MODEL),
    "refactoring":       os.getenv("REFACTORING_MODEL",     HEAVY_MODEL),
    "agent_trainer":     os.getenv("AGENT_TRAINER_MODEL",   HEAVY_MODEL),
    # Nutzeranfrage (Team-Wachstums-Retrospektive 2026-09-06): compliance stand bisher bei
    # STANDARD, obwohl seine Aufgabe (DSGVO/GDPR-Audits, Lizenzprüfung GPL vs. MIT) genau
    # dieselbe Kategorie echter, konsequenzenreicher Trade-off-Entscheidungen ist wie die
    # direkt daneben bei HEAVY eingestuften security/code_reviewer - eine falsche
    # Lizenz-/DSGVO-Einschätzung ist ein reales rechtliches Risiko, kein bloßer Stilfehler.
    "compliance":        os.getenv("COMPLIANCE_MODEL",      HEAVY_MODEL),

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

# Rollen mit echten Architektur-/Sicherheits-/Qualitäts-Trade-offs. Sie dürfen bei
# Kontingent-Erschöpfung nie unbemerkt unter HEAVY_ROLE_MIN_TIER abrutschen (siehe
# core/model_capability.py) - realer Fund: bei erschöpftem Groq-Tageslimit liefen architect,
# security und backend auf gemini-flash-lite weiter und produzierten wiederholt Strukturfehler.
# Bewusst explizit statt aus AGENT_MODELS abgeleitet, da Env-Overrides die Werte verändern.
#
# KRITISCHER FUND (CertPulse, 2026-09-12): "dev_lead" stand hier bisher mit drin - ein
# provider_exhausted-Fehlschlag DIESER rein koordinierenden Delegations-/Konsolidierungs-Rolle
# (siehe agents/department_lead_agent.py) loeste denselben Sofortabbruch aus wie der Ausfall
# einer echten technischen Rolle (architect/backend/...). Ergebnis: KEIN einziger Entwickler-
# Agent (backend/frontend/database/api_integration) wurde je aufgerufen, obwohl deren Provider
# noch Kapazitaet gehabt haetten. Ein Abteilungsleiter ist organisatorisch nuetzlich, aber sein
# Ausfall ist kein Show-Stopper - agents/orchestrator/department.py behandelt einen
# fehlgeschlagenen Department-Lead jetzt separat (Graceful Degradation auf skip_lead_layer statt
# Abbruch, siehe dortigen Kommentar), unabhaengig von dieser Liste. "dev_lead" bleibt deshalb
# bewusst draussen; die tatsaechlich kritischen technischen Rollen darunter sind unveraendert.
CRITICAL_AGENT_IDS: frozenset[str] = frozenset({
    "planning_lead", "governance_lead", "architect", "backend", "database", "ml",
    "prompt_engineer", "security", "code_reviewer", "refactoring", "agent_trainer", "compliance",
})
# Mindeststufe für CRITICAL_AGENT_IDS: "lite" (keine Sperre), "standard" (Default: keine
# Lite-Modelle) oder "heavy" (nur Opus/Sonnet/Pro/gpt-oss-120b-Klasse).
HEAVY_ROLE_MIN_TIER: str = os.getenv("HEAVY_ROLE_MIN_TIER", "standard")

# Kapazitätsprüfung vor Laufstart (core/capacity_gate.py): "block" startet einen Lauf nicht,
# wenn eine eingeplante kritische Rolle kein Modell oberhalb ihrer Mindeststufe mehr erreicht;
# "warn" meldet es nur; "off" schaltet die Prüfung ab.
CAPACITY_GATE_MODE: str = os.getenv("CAPACITY_GATE_MODE", "block").strip().lower()

# Schreibrechte pro Rolle (core/write_guard.py, CODEOWNERS-Prinzip). Realer Fund auditlog_sentinel
# 2026-09-10: architect überschrieb app/config.py, frontend app/main.py, documentation
# app/models.py. Rollen OHNE Eintrag bleiben unbeschränkt (Entwicklungs-/Fix-Rollen). Muster
# sind fnmatch-Globs auf den projektrelativen Pfad (`*` umfasst dabei auch `/`).
ENABLE_ROLE_WRITE_SCOPES: bool = os.getenv("ENABLE_ROLE_WRITE_SCOPES", "true").strip().lower() in ("1", "true", "yes")
_DOC_WRITE_SCOPE: tuple[str, ...] = ("*.md", "*.rst", "docs/*", "LICENSE*", "CHANGELOG*", "CONTRIBUTING*")
_FRONTEND_WRITE_SCOPE: tuple[str, ...] = (
    "src/*", "public/*", "frontend/*", "web/*", "client/*", "static/*", "assets/*", "templates/*",
    "e2e/*", "*.html", "*.css", "*.scss", "*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs",
    "*.vue", "*.svelte", "*.svg", "package.json", "package-lock.json", "tsconfig*.json",
    "vite.config.*", "tailwind.config.*", "postcss.config.*", ".eslintrc*", ".prettierrc*",
    "playwright.config.*", "vitest.config.*", "jest.config.*",
)
AGENT_WRITE_SCOPES: dict[str, dict[str, tuple[str, ...]]] = {
    "documentation": {"allow": _DOC_WRITE_SCOPE},
    "readme": {"allow": _DOC_WRITE_SCOPE},
    "product_owner": {"allow": _DOC_WRITE_SCOPE},
    "business_analyst": {"allow": _DOC_WRITE_SCOPE},
    "web_research": {"allow": _DOC_WRITE_SCOPE},
    "finops": {"allow": _DOC_WRITE_SCOPE},
    "architect": {"allow": _DOC_WRITE_SCOPE + (
        "openapi.*", "asyncapi.*", "*.proto", "*.graphql", "contracts/*", "*schemas.py",
        "*/schemas/*", "*.puml", "*.mmd",
    )},
    "ui_ux": {"allow": _DOC_WRITE_SCOPE + _FRONTEND_WRITE_SCOPE + ("design*",), "deny": ("*.py",)},
    "accessibility": {"allow": _DOC_WRITE_SCOPE + _FRONTEND_WRITE_SCOPE, "deny": ("*.py",)},
    "frontend": {"allow": _DOC_WRITE_SCOPE + _FRONTEND_WRITE_SCOPE, "deny": ("*.py",)},
    # Realer Fund cloudpulse 2026-09-16 (foreign_changes): der security-Agent hatte keinen
    # Eintrag und damit freie Hand - er ueberschrieb `app/main.py` und `app/api/endpoints.py`
    # (Eigentuemer: backend), um Middleware zu injizieren. Ergebnis: ein Import landete mitten
    # im Modulrumpf, und sein EIGENER Bericht (docs/SECURITY_AUDIT.md) liess sich wegen des
    # dadurch ausgeloesten Dateikonflikts nicht mehr speichern. Er darf weiterhin alles anlegen,
    # was ihm selbst gehoert (Audit-Berichte, eigene Security-Module, Secrets-Vorlagen,
    # Abhaengigkeiten) - Aenderungen an fremden Backend-Dateien beschreibt er ab jetzt im
    # Bericht, statt sie parallel zum Eigentuemer hineinzuschreiben.
    # `*__init__.py` bleibt bewusst erlaubt: ein reiner Paket-Marker/Re-Export gehoert zum
    # eigenen Security-Modul und ist keine fremde Implementierung.
    "security": {"allow": _DOC_WRITE_SCOPE + (
        "*security*", "*/security/*", "*auth*", "*/auth/*", "*__init__.py",
        "*.env.example", ".env.example",
        "requirements*.txt", "*.cfg", "*.ini", "*.toml", "*.yml", "*.yaml",
        "tests/*security*", "tests/*auth*",
    )},
}

# Fachbereichs-Zuweisungen für bereichsweite Modell-Konfiguration
DEPARTMENT_PLANNING_AGENTS = {"planning_lead", "team_lead", "product_owner", "business_analyst", "web_research", "architect", "finops"}
DEPARTMENT_DESIGN_AGENTS = {"design_lead", "image_generator", "copywriter", "ui_ux"}
DEPARTMENT_DEV_AGENTS = {"dev_lead", "backend", "frontend", "database", "api_integration", "data_engineer", "mobile", "ml", "prompt_engineer", "performance"}
DEPARTMENT_CONTENT_AGENTS = {"content_lead", "accessibility", "i18n", "documentation", "readme"}
DEPARTMENT_CREATIVE_AGENTS = DEPARTMENT_DESIGN_AGENTS | DEPARTMENT_CONTENT_AGENTS | {"creative_lead"}
DEPARTMENT_QA_AGENTS = {"qa_lead", "devops", "tester", "security", "resilience_guard", "github"}
DEPARTMENT_GOVERNANCE_AGENTS = {"governance_lead", "code_reviewer", "refactoring", "compliance", "project_cleaner", "agent_trainer", "retrospective"}

DEPARTMENT_MODELS: dict[str, str] = {
    "planning": os.getenv("DEPARTMENT_PLANNING_MODEL", ""),
    "design": os.getenv("DEPARTMENT_DESIGN_MODEL", os.getenv("DEPARTMENT_CREATIVE_MODEL", "")),
    "dev": os.getenv("DEPARTMENT_DEV_MODEL", ""),
    "content": os.getenv("DEPARTMENT_CONTENT_MODEL", os.getenv("DEPARTMENT_CREATIVE_MODEL", "")),
    "creative": os.getenv("DEPARTMENT_CREATIVE_MODEL", ""),
    "qa": os.getenv("DEPARTMENT_QA_MODEL", ""),
    "governance": os.getenv("DEPARTMENT_GOVERNANCE_MODEL", ""),
}


# Umgebungsvariablen-Namen je Rolle, SOWEIT sie von der Konvention `<AGENT_ID>_MODEL`
# abweichen. Realer Fund (KI-Team-Masterplan-Analyse): get_model_for_agent() prüfte in Schritt 1
# hart `f"{agent_id.upper()}_MODEL"` - für sieben Rollen heißt die tatsächlich ausgewertete
# Variable aber anders (siehe AGENT_MODELS oben). Folge: Bei genau diesen Rollen wurde ein
# ausdrücklich gesetzter Rollen-Override still von einem Fachbereichs-Override überstimmt -
# die Vorrang-Regel, die Schritt 1 herstellen soll, kehrte sich also ins Gegenteil um.
# tests/test_agent_model_env_keys.py hält dieses Dict mit den echten os.getenv-Namen synchron.
AGENT_MODEL_ENV_KEYS: dict[str, str] = {
    "product_owner":    "PO_MODEL",
    "business_analyst": "BA_MODEL",
    "prompt_engineer":  "PROMPT_ENG_MODEL",
    "resilience_guard": "RESILIENCE_MODEL",
    "image_generator":  "IMAGE_GEN_MODEL",
    "accessibility":    "A11Y_MODEL",
    "documentation":    "DOCS_MODEL",
}


def get_model_env_key(agent_id: str) -> str:
    """Name der Umgebungsvariable, die das Modell dieser Rolle überschreibt."""
    return AGENT_MODEL_ENV_KEYS.get(agent_id, f"{agent_id.upper()}_MODEL")


def get_model_for_agent(agent_id: str, include_ab_trial: bool = True) -> str:
    """
    Ermittelt das konfigurierte LLM-Modell für einen Agenten unter Berücksichtigung von Overrides.

    `include_ab_trial=False` klammert Schritt 3b (den Zufallsarm eines laufenden A/B-Tests) aus
    und liefert damit die STABILE Zuweisung dieser Rolle. Genau die braucht
    core/optimization_advisor.py als Vergleichsbasis: Mit dem Zufallsarm wäre die "aktuelle"
    Zuweisung bei jedem Aufruf eine andere und die Auswertung nicht reproduzierbar.
    """
    # 1. Spezifischer Rollen-Override
    if agent_id in AGENT_MODELS and os.getenv(get_model_env_key(agent_id)):
        return AGENT_MODELS[agent_id]

    # 2. Fachbereichsweiter Override
    if agent_id in DEPARTMENT_PLANNING_AGENTS and DEPARTMENT_MODELS["planning"]:
        return DEPARTMENT_MODELS["planning"]
    if agent_id in DEPARTMENT_DESIGN_AGENTS and DEPARTMENT_MODELS["design"]:
        return DEPARTMENT_MODELS["design"]
    if agent_id in DEPARTMENT_DEV_AGENTS and DEPARTMENT_MODELS["dev"]:
        return DEPARTMENT_MODELS["dev"]
    if agent_id in DEPARTMENT_CONTENT_AGENTS and DEPARTMENT_MODELS["content"]:
        return DEPARTMENT_MODELS["content"]
    if agent_id in DEPARTMENT_CREATIVE_AGENTS and DEPARTMENT_MODELS["creative"]:
        return DEPARTMENT_MODELS["creative"]
    if agent_id in DEPARTMENT_QA_AGENTS and DEPARTMENT_MODELS["qa"]:
        return DEPARTMENT_MODELS["qa"]
    if agent_id in DEPARTMENT_GOVERNANCE_AGENTS and DEPARTMENT_MODELS["governance"]:
        return DEPARTMENT_MODELS["governance"]

    # 3. Datenbasierte Selbstoptimierung - NUR wenn weder ein Rollen- noch ein
    # Fachbereichs-Override explizit gesetzt ist, greift eine zuvor von
    # core/optimization_advisor.py empirisch ermittelte, bessere Modellzuweisung. Ein Eintrag
    # greift, wenn ENABLE_AUTO_MODEL_TUNING global aktiv ist (opt-in, siehe oben) ODER wenn er
    # ausdrücklich als "manual" markiert ist - das ist der Fall für einzeln per `/apply-tuning
    # <agent_id>` bestätigte Vorschläge (core/optimization_advisor.py.apply_single_suggestion()):
    # eine explizite, einzelne Bestätigung soll auch dann wirken, wenn der globale
    # Alles-oder-nichts-Schalter aus bleibt.
    auto_tuned_entry = _read_auto_tuned_entry(agent_id)
    # `ab_promoted`: durch einen bestandenen A/B-Test (core/model_ab_trials.py) übernommen - das
    # ist bereits eine gemessene, keine spekulative Umstellung und gilt deshalb ohne globalen Schalter.
    if auto_tuned_entry and (
        ENABLE_AUTO_MODEL_TUNING or auto_tuned_entry.get("manual") or auto_tuned_entry.get("ab_promoted")
    ):
        model = auto_tuned_entry.get("model", "")
        if model:
            # Realer Fund (Token-Analyse 2026-09-17): der Selbstoptimierer misst Erfolgsquote
            #/Tokenverbrauch GEMITTELT über alle Projekte und stuft Rollen wie tester/frontend
            # auf ein Lite-Modell ab, sobald das im Durchschnitt bessere Zahlen liefert - ein
            # Durchschnitt, der einfache Wegwerf-Projekte genauso gewichtet wie anspruchsvolle.
            # core/task_manager.is_complex_task() markiert anspruchsvolle Läufe (mehrere
            # Architektur-/Sicherheits-Signale oder ein breiter Plan); für deren Dauer darf eine
            # Auto-Tuning-Abstufung NICHT stillschweigend greifen - eine Aufwertung (z.B. durch
            # einen bestandenen A/B-Test) bleibt dagegen erlaubt, ist ja kein Risiko.
            if ENABLE_TASK_COMPLEXITY_SCALING:
                from core.model_capability import current_run_is_complex, model_capability_tier

                baseline_model = AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)
                is_downgrade = model_capability_tier(model) < model_capability_tier(baseline_model)
                if is_downgrade and current_run_is_complex():
                    return baseline_model
            return model

    # 3b. Laufender A/B-Test: ein Anteil der Läufe nutzt das Kandidatenmodell.
    if not include_ab_trial:
        return AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)
    try:
        from core.model_ab_trials import trial_model_for_agent

        trial_model = trial_model_for_agent(agent_id)
    except Exception:  # noqa: BLE001 - optionale Optimierung darf die Modellauflösung nie brechen
        trial_model = None
    if trial_model:
        return trial_model

    # 4. Standard-Zuordnung aus AGENT_MODELS oder Fallback
    return AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)


def _read_auto_tuned_entry(agent_id: str) -> dict:
    """Liest den zuvor (automatisch oder manuell per `/apply-tuning`) vorgeschlagenen
    Selbstoptimierungs-Eintrag für `agent_id` aus AUTO_TUNED_MODELS_FILE - leeres Dict, falls
    keiner existiert oder die Datei fehlt/beschädigt ist (nie ein Absturz nur wegen dieser rein
    optionalen Optimierung)."""
    path = Path(AUTO_TUNED_MODELS_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entry = data.get(agent_id) if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) else {}


# ──────────────────────────────────────────
# Sprache & Verhalten
# ──────────────────────────────────────────
AGENT_LANGUAGE: str = os.getenv("AGENT_LANGUAGE", "de")
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "4096"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.4"))

AUTO_SAVE_WORKSPACE: bool = os.getenv("AUTO_SAVE_WORKSPACE", "true").lower() in ("true", "1", "yes")

# ──────────────────────────────────────────
# Agentischer Werkzeug-Loop (echte Tool-Nutzung statt Ein-Schuss-Textgenerierung)
# ──────────────────────────────────────────
ENABLE_AGENT_TOOLS: bool = os.getenv("ENABLE_AGENT_TOOLS", "true").lower() in ("true", "1", "yes")
MAX_AGENT_TOOL_ITERATIONS: int = int(os.getenv("MAX_AGENT_TOOL_ITERATIONS", "8"))

# Nicht jeder Agent braucht dasselbe Iterationsbudget: Jede zusätzliche Iteration sendet
# die komplette bisherige Konversation (inkl. aller Werkzeug-Ergebnisse) erneut mit – das
# Budget wird daher pro Agenten-Rolle gestaffelt, um unnötigen Tokenverbrauch zu vermeiden,
# ohne code-schreibende Agenten einzuschränken, die echte Iteration brauchen.
# Tokenoptimierung (2026-09-23): Gestrafft auf max. 8 Runden für Code-Rollen, um Prompt-Explosion zu verhindern.
AGENT_MAX_TOOL_ITERATIONS: dict[str, int] = {
    # Führung & Fachbereichsleiter: rein koordinierend/delegierend -> 2-3 Iterationen genügen völlig
    "planning_lead": 3, "dev_lead": 3, "governance_lead": 3, "qa_lead": 3,
    "design_lead": 3, "content_lead": 3, "creative_lead": 3,
    # Vorwiegend textbasierte Planungs-/Content-Rollen: meist 1-2 Dateien, wenig Iteration nötig
    "product_owner": 3, "business_analyst": 3, "web_research": 3, "finops": 3, "team_lead": 3,
    "copywriter": 3, "ui_ux": 3, "accessibility": 3, "i18n": 3, "documentation": 3,
    "readme": 3, "github": 2, "image_generator": 3, "retrospective": 2,
    # Architektur & technische Spezialisten: schreiben fokussierte Artefakte.
    "architect": 5, "devops": 5, "security": 5, "resilience_guard": 5, "tester": 8,
    # Code-Entwickler: gestrafft von 10-14 auf 6-8, um Multi-Turn Prompt-Explosion zu verhindern
    "backend": 8, "database": 6, "frontend": 8, "api_integration": 6, "data_engineer": 6,
    "ml": 6, "mobile": 8, "performance": 5, "refactoring": 6, "prompt_engineer": 5,
    # Reine Prüf-/Review-Rollen: lesen viel, schreiben nichts -> 3 Iterationen
    "code_reviewer": 3, "compliance": 3, "project_cleaner": 3,
}

# ──────────────────────────────────────────
# Echte Verifikation (Dependency-Installation + tatsächliche Testausführung)
# ──────────────────────────────────────────
MAX_VERIFICATION_ITERATIONS: int = int(os.getenv("MAX_VERIFICATION_ITERATIONS", "3"))
DEPENDENCY_INSTALL_TIMEOUT_SECONDS: float = float(os.getenv("DEPENDENCY_INSTALL_TIMEOUT_SECONDS", "120"))
TEST_RUN_TIMEOUT_SECONDS: float = float(os.getenv("TEST_RUN_TIMEOUT_SECONDS", "60"))
# Realer Fund: die Verifikation misst bisher nur Pass/Fail, keine Abdeckung - ein Projekt mit
# 3 bestandenen Tests bei 500 Zeilen ungetestetem Code gilt genauso als "verifiziert" wie eines
# mit echter Abdeckung. MIN_TEST_COVERAGE=0 (Standard) deaktiviert die Prüfung, bestehende
# Läufe bleiben unangetastet. Gesetzt (z.B. 70 = 70%), misst core/verifier.py.check_coverage()
# die echte Abdeckung per pytest-cov (nur wenn das Projekt es selbst installiert hat - siehe
# CoverageReport-Docstring) und setzt agents/orchestrator.py._run_verification_loop()s
# verification_ok explizit auf False, wenn die Schwelle unterschritten wird - anders als ein
# Lint-Fund (rein informativ) ist eine EXPLIZIT konfigurierte Schwelle als echte Anforderung
# gemeint, kein bloßes FYI.
#
# KI-Team-Optimierungs-Session, echter Fund: ein von 0 abweichender Standardwert wurde hier
# testweise gesetzt und brach dabei 57 bestehende Tests (u.a. test_lint_integration.py,
# test_sast_integration.py, test_docker_build_integration.py) mit
# "TypeError: '>=' not supported between instances of 'MagicMock' and 'float'" - diese Tests
# mocken den Verifier ohne `check_coverage()` zu konfigurieren, weil sie zu Recht davon
# ausgehen, dass der Zweig bei deaktivierter Schwelle nie erreicht wird. Ein risikoloser
# Default ist damit nicht möglich, ohne alle betroffenen Test-Doubles anzufassen - bleibt
# daher bewusst opt-in (0), wie ursprünglich entschieden. Einzelne Projekte/Umgebungen können
# die Schwelle weiterhin gezielt per MIN_TEST_COVERAGE-Umgebungsvariable aktivieren.
MIN_TEST_COVERAGE: float = float(os.getenv("MIN_TEST_COVERAGE", "0"))
# Realer Fund: der performance-Agent schreibt vollständige k6-/Locust-Lastentest-Skripte, die
# aber NIE ausgeführt werden - anders als run_tests() landen sie ungeprüft im Projekt, niemand
# (Mensch oder Team) weiß, ob sie überhaupt laufen oder was sie ergeben. check_load_test()
# startet die generierte App auf einem freien Port und führt einen kurzen, wenige Sekunden
# dauernden SMOKE-Lasttest aus (wenige virtuelle Nutzer) - kein vollständiger Lasttest (würde
# Minuten dauern und echte Ressourcen binden), nur eine Prüfung, ob die App unter minimaler
# gleichzeitiger Last überhaupt fehlerfrei antwortet. Läuft nur, wenn ein Skript unter
# tests/load/ (locustfile.py oder *.js) UND das jeweilige Tool (locust/k6) lokal installiert
# sind UND die App tatsächlich startet - in der Praxis für die meisten Projekte ein No-Op.
ENABLE_LOAD_TEST_CHECK: bool = os.getenv("ENABLE_LOAD_TEST_CHECK", "true").lower() in ("true", "1", "yes")
LOAD_TEST_DURATION_SECONDS: float = float(os.getenv("LOAD_TEST_DURATION_SECONDS", "5"))
LOAD_TEST_TIMEOUT_SECONDS: float = float(os.getenv("LOAD_TEST_TIMEOUT_SECONDS", "60"))

# Realer Fund (Bestandsaufnahme cloudvault-Projekt, siehe core/verifier/completeness.py): eine
# Testsuite kann vollständig grün sein, obwohl der geprüfte Code selbst nur ein Platzhalter ist
# (z.B. "Hier würde die AES-256-GCM Verschlüsselung ... erfolgen" statt echter Verschlüsselung)
# - keiner der bisherigen Checks erkennt das, weil sie alle nur prüfen, ob vorhandener Code
# FUNKTIONIERT, nicht ob er tatsächlich das tut, was die Aufgabe verlangt. ENABLE_COMPLETENESS_
# CHECK=true (Standard) lässt den Orchestrator nach Stub-/Platzhalter-Markern im generierten
# Code UND nach im README referenzierten, aber fehlenden Dateien (z.B. requirements.txt) suchen
# und blockiert verification_ok bei einem Fund - wie ein echter Testfehler, nicht nur informativ
# wie ein Lint-Fund, weil ein Stub-Kommentar eine nicht erfüllte fachliche Anforderung ist.
ENABLE_COMPLETENESS_CHECK: bool = os.getenv("ENABLE_COMPLETENESS_CHECK", "true").lower() in ("true", "1", "yes")

# ──────────────────────────────────────────
# Smoke-Test-Gate vor der Testschleife (agents/orchestrator/verification.py)
# ──────────────────────────────────────────
# Der Runtime-Smoke-Test lief bisher ERST NACH der kompletten Testschleife. Realer Befund
# (KI-Team-Masterplan-Analyse): Der `tester` ist mit 78 Aufrufen der meistgerufene und mit
# 65,4% der schwaechste Kern-Agent - und ein grosser Teil dieser Fehlschlaege entsteht, weil
# die Anwendung gar nicht erst startet. Dann scheitert JEDER Test an derselben Ursache, und die
# Fix-Schleife arbeitet an Symptomen statt an der Wurzel (opspilot: 1.038.910 Tokens ohne
# bestandene Verifikation). Das Gate prueft den Start VORHER und laesst nur diesen einen Fehler
# beheben.
ENABLE_SMOKE_TEST_GATE: bool = os.getenv("ENABLE_SMOKE_TEST_GATE", "true").lower() in ("true", "1", "yes")

# ──────────────────────────────────────────
# Nischen-Rollen bedarfsgerecht einblenden (core/task_manager.py)
# ──────────────────────────────────────────
# Realer Befund ueber die letzten 30 Laeufe: `mobile` wurde 0-mal aufgerufen, `i18n`/`finops`/
# `team_lead` je 1-mal, `prompt_engineer` 2-mal. Sie standen trotzdem mit Name UND Beschreibung
# in JEDEM Zerlegungs-Prompt - das kostet Tokens (Prompt-zu-Completion-Verhaeltnis 25:1) und
# verwaessert die Auswahl. Die Rollen bleiben vollwertig erhalten und werden eingeblendet,
# sobald die Anfrage inhaltlich zu ihnen passt oder sie ausdruecklich nennt.
ENABLE_NICHE_AGENT_FILTER: bool = os.getenv("ENABLE_NICHE_AGENT_FILTER", "true").lower() in ("true", "1", "yes")

# Realer Fund (Bestandsaufnahme cloudvault-Projekt): 13 ruff-Lint-Funde standen im
# Verifikations-Protokoll, wurden aber nie behoben - Lint ist rein informativ (siehe
# core/verifier/lint.py.LintReport-Docstring), kein Agent war je beauftragt, sie zu fixen.
# ENABLE_AUTO_LINT_FIX=true (Standard) lässt core/verifier/lint.py._lint_python() vor dem
# eigentlichen Check-Lauf `ruff check --fix` (NUR sichere Autofixes, kein `--unsafe-fixes`)
# ausführen - unsortierte/ungenutzte Importe, veraltete Typannotationen u.Ä. verschwinden so
# automatisch, ohne einen Agenten-Auftrag zu brauchen, analog zu `black`/`prettier` im
# Pre-Commit-Hook eines echten Teams.
ENABLE_AUTO_LINT_FIX: bool = os.getenv("ENABLE_AUTO_LINT_FIX", "true").lower() in ("true", "1", "yes")

# P0-6 Teil 2 (ROADMAP_TEMP.md): die real übrig bleibenden Regeln nach dem sicheren Autofix
# (SIM102, SIM103, RUF013, RUF059, F841 u.Ä.) sind fast alle nur per `--unsafe-fixes` behebbar -
# das kann in seltenen Fällen Verhalten ändern (deshalb trennt ruff diese Kategorie überhaupt).
# ENABLE_AUTO_LINT_UNSAFE_FIX=false (Standard: AUS, bewusst konservativer als der sichere Fix)
# lässt core/verifier/lint.py._lint_python() bei true einen ZWEITEN, separat protokollierten
# `ruff check --fix --unsafe-fixes`-Durchlauf ausführen - aber NUR, wenn das Projekt eine eigene
# Testsuite hat, und NUR dauerhaft, wenn diese danach weiterhin grün ist; andernfalls wird die
# Änderung sofort verworfen (Datei-Snapshot vorher, Wiederherstellung bei rotem Testlauf).
ENABLE_AUTO_LINT_UNSAFE_FIX: bool = os.getenv("ENABLE_AUTO_LINT_UNSAFE_FIX", "false").lower() in ("true", "1", "yes")

# ──────────────────────────────────────────
# Governance-Kritisch-Fix-Schleife (core/review_gate.py, agents/orchestrator.py._run_governance_fix_loop)
# ──────────────────────────────────────────
# Realer Fund: code_reviewer/security/compliance (REVIEW_ONLY_AGENT_IDS) kategorisieren Befunde
# selbst nach Schweregrad ("Kritisch") - das löste bisher NIE einen Korrekturauftrag aus, nur
# echte Testfehler taten das (siehe MAX_VERIFICATION_ITERATIONS oben). Ein "Kritisch" im
# Code-Review ist bei einem echten Team ein Blocker, kein FYI im Abschlussbericht.
# ENABLE_GOVERNANCE_FIX_LOOP=true (Standard) lässt den Orchestrator kritische Befunde per
# Text-Heuristik erkennen (core/review_gate.py) und gezielt an den Datei-Owner zur Korrektur
# zurückspielen, BEVOR die echte Testverifikation läuft.
ENABLE_GOVERNANCE_FIX_LOOP: bool = os.getenv("ENABLE_GOVERNANCE_FIX_LOOP", "true").lower() in ("true", "1", "yes")
# MAX_REVIEW_ITERATIONS war früher ein nie verdrahteter Rest aus einer früheren Version dieses
# Features (stand unter "Sprache & Verhalten", ohne dass irgendein Code ihn je gelesen hätte -
# echter Fund bei einer Bestandsaufnahme). Steuert jetzt tatsächlich, wie oft die Schleife
# läuft: Standard 1 = genau EIN Fix-Dispatch, OHNE die Review-Rollen danach erneut aufzurufen
# (die anschließende echte Testverifikation deckt technische Regressionen ab, nicht aber die
# qualitative Review-Aussage selbst). Ein höherer Wert ruft die ursprünglich meldenden
# Review-Rollen nach jedem Fix-Versuch frisch erneut auf, um zu prüfen, ob noch kritische
# Befunde bestehen - kostet entsprechend mehr LLM-Aufrufe pro zusätzlicher Runde.
# Auf 2 angehoben (vormals 1): ein echter Lauf (omnichat-Projekt) zeigte, dass ein einziger
# Fix-Dispatch kritische Sicherheits-/Technical-Debt-Funde (Pydantic-v2-Migration, CORS-
# Härtung) nicht zuverlässig vollständig behebt - der Testverifikations-Loop direkt darunter
# bekommt bereits standardmäßig 2 Versuche (MAX_VERIFICATION_ITERATIONS), Governance-Funde
# hatten strukturell schlechtere Chancen auf echte Behebung als ein simpler Testfehler, obwohl
# ein "Kritisch" im Review potenziell schwerwiegender ist als ein rotes Unit-Test.
MAX_REVIEW_ITERATIONS: int = int(os.getenv("MAX_REVIEW_ITERATIONS", "2"))

# MAX_TASK_TOKENS: harte Obergrenze für den Token-Verbrauch EINER EINZELNEN Agenten-Teilaufgabe
# (nicht des gesamten Laufs - siehe MAX_RUN_TOKENS in core/token_guard.py). Bisher gab es nur
# ein Lauf-weites Budget: ein einzelner hängender/ausufernder Fix-Task (z.B. eine
# Governance-Fix-Schleife, die an derselben Datei wiederholt viele Tool-Iterationen braucht)
# konnte dadurch unbemerkt einen unverhältnismäßig großen Teil des GESAMTEN Lauf-Budgets
# verbrauchen, bevor spätere, u.U. wichtigere Fachbereiche überhaupt an der Reihe waren.
# 0 = deaktiviert (kein Task-Limit, nur das bestehende Lauf-Budget gilt). Absichtlich nur als
# Warnsignal in den Fix-Schleifen verdrahtet (agents/orchestrator/verification.py), nicht als
# harter Abbruch mitten in einem laufenden LLM-Aufruf (technisch nicht sauber möglich) - stoppt
# aber zuverlässig WEITERE Fix-Versuche für denselben Befund in derselben Schleife.
MAX_TASK_TOKENS: int = int(os.getenv("MAX_TASK_TOKENS", "40000"))

# ──────────────────────────────────────────
# Echtes lokales Deployment: Docker Compose (core/deployment.py, manuell per /deploy ausgelöst)
# ──────────────────────────────────────────
# core/verifier.py.check_docker_build() prüfte bisher NUR, ob ein generiertes Dockerfile
# überhaupt baut - nie einen echten Deploy. core/deployment.py kennt jetzt ein konkretes
# Ziel: Docker Compose lokal/self-hosted (kein Cloud-Account/API-Token nötig). Bewusst NICHT
# automatisch nach Push/Merge ausgelöst - echte Container-Ausführung startet einen laufenden
# Prozess und belegt Ports, verdient dieselbe Bestätigungs-Gate-Philosophie wie /push.
DEPLOY_TIMEOUT_SECONDS: float = float(os.getenv("DEPLOY_TIMEOUT_SECONDS", "300"))

# ──────────────────────────────────────────
# Circuit Breaker bei Massen-Ausfall der Provider (core/provider_exhaustion.py)
# ──────────────────────────────────────────
# Realer Fund (workspace/event_ticket_api, 09.09.2026): 19 von 21 Agenten-Aufrufen scheiterten
# an erschöpften Kontingenten, `files_written_count: 0` - und der Lauf lief trotzdem komplett
# durch: Verifikation gestartet, Fix-Auftrag dispatcht, PROJECT_STATE.md mit "In Entwicklung"
# geschrieben, obwohl kein Agent auch nur eine Zeile produziert hatte. Das erzeugt irreführende
# Projektzustände und Backlog-Tickets für Probleme, die es gar nicht gibt.
# Anteil (0.0-1.0) infrastrukturbedingt gescheiterter Aufrufe EINER Welle, ab dem der Lauf
# sauber beendet wird. 0 schaltet den Breaker ab (altes Verhalten).
PROVIDER_EXHAUSTION_ABORT_RATIO: float = float(os.getenv("PROVIDER_EXHAUSTION_ABORT_RATIO", "0.6"))

# Laufanalyse 2026-09-16: Die Wellenschwelle oben und PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT unten
# haben denselben blinden Fleck - beide sehen nur einen AUSSCHNITT. Verteilen sich die
# Kontingent-Ausfälle gleichmäßig und von Erfolgen durchsetzt über viele kleine Wellen, bleibt
# jede Welle unter 60% und keine zwei Fehlschläge stehen hintereinander. Im Lauf `sentinelgrid`
# scheiterten so 5 von 15 Aufrufen (33%), ohne dass ein Breaker ansprach: 105.972 Tokens für
# einen Lauf, der rot endete. Diese dritte Sicht kumuliert über den GESAMTEN Lauf.
# Anteil (0.0-1.0) infrastrukturbedingt gescheiterter Aufrufe seit Laufbeginn; 0 schaltet ab.
# 0.30: knapp unter den 33% aus `sentinelgrid`, damit genau dieses Muster erfasst wird. Ein Lauf,
# dem fast ein Drittel aller Agenten-Aufrufe an der Infrastruktur wegbricht, hat effektiv ein
# Drittel des Teams verloren - weiterzulaufen kostet dann nur noch Tokens.
PROVIDER_EXHAUSTION_RUN_ABORT_RATIO: float = float(os.getenv("PROVIDER_EXHAUSTION_RUN_ABORT_RATIO", "0.30"))
# Mindestzahl aufgezeichneter Aufrufe, bevor die laufweite Quote überhaupt zählt - bei 2
# Aufrufen ist ein einzelner 429er bereits 50% und trotzdem keine Aussage (realer Fall
# `ai_team_framework`: 1 von 2 Aufrufen, ein Abbruch wäre dort falsch gewesen).
PROVIDER_EXHAUSTION_RUN_MIN_SAMPLE: int = int(os.getenv("PROVIDER_EXHAUSTION_RUN_MIN_SAMPLE", "6"))

# Team-Optimierung (chronos_queue-Retrospektive, 20260911): PROVIDER_EXHAUSTION_ABORT_RATIO oben
# greift nur INNERHALB einer einzelnen parallelen Welle (asyncio.gather, siehe
# agents/orchestrator/dispatch.py) und stoppt danach nur noch die spätere Verifikation - die
# restlichen Fachbereichs-PHASEN liefen bislang unverändert weiter. Realer Fund: obwohl bereits
# beim 2. und 3. Agenten (architect, backend) feststand, dass KEIN Provider mehr Kapazität hatte,
# lief der Orchestrator noch 25 Minuten lang blind weiter und rief 8 weitere Agenten nacheinander
# auf, die alle in Timeouts/Quota-Fehlern liefen. Dieser Schwellwert gilt SEQUENZIELL über die
# gesamte Fachbereichs-Hierarchie hinweg (agents/orchestrator/department.py.
# _run_department_hierarchy) und bricht den KOMPLETTEN Lauf sofort ab (keine weiteren Phasen
# mehr), sobald so viele Agenten IN FOLGE mit failure_class="provider_exhausted" scheitern - oder
# sobald eine einzelne kritische Rolle (CRITICAL_AGENT_IDS, z.B. architect/backend) so scheitert,
# da ohne sie kein tragfähiges Fundament entstehen kann.
PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT: int = int(os.getenv("PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT", "2"))

# Realer Fund (logs/runs/20260912_082145_sentinelgrid.jsonl): `_run_agents_parallel()`
# (agents/orchestrator/dispatch.py) startete alle Mitglieder eines Fachbereichs (bis zu 6
# Agenten) vollkommen ungebremst per `asyncio.gather` - ein klassischer Thundering-Herd-Effekt.
# Die Agenten sprengten gemeinsam sowohl Groqs TPM- als auch Geminis RPM-Free-Tier-Limit
# innerhalb derselben Sekunde, sodass 9 von 15 Aufrufen mit `provider_exhausted: true`
# abbrachen, obwohl die Provider insgesamt genug Kontingent für den Lauf gehabt hätten - nur
# nicht gleichzeitig. Ein Semaphore begrenzt, wie viele Agenten-Aufrufe INNERHALB einer Welle
# wirklich gleichzeitig laufen (weitere warten, statt sofort auf ein bereits ausgeschöpftes
# Minutenlimit zu treffen). 2 ist bewusst konservativ für kostenlose Provider-Kontingente;
# bei bezahlten/großzügigeren Kontingenten kann der Wert erhöht werden.
MAX_CONCURRENT_AGENTS: int = int(os.getenv("MAX_CONCURRENT_AGENTS", "2"))

# ──────────────────────────────────────────
# Fachbereichs-Teamleiter: echte Delegation & Konsolidierung per LLM-Call
# ──────────────────────────────────────────
ENABLE_DEPARTMENT_LEAD_EXECUTION: bool = os.getenv("ENABLE_DEPARTMENT_LEAD_EXECUTION", "true").lower() in ("true", "1", "yes")

# Realer Fund aus einem echten End-to-End-Testlauf: eine triviale Ein-Endpunkt-Aufgabe
# (1 Datei Code + 1 Testdatei) verbrauchte 66.000 Tokens, weil JEDES der 3 beteiligten
# Fachbereiche (dev/qa/governance) trotz jeweils nur EINES einzigen Mitglieds die volle
# Teamleiter-Delegation+Konsolidierung durchlief - der Lauf diagnostizierte sich in seiner
# eigenen Retrospektive selbst als "Token-Inflation"/"Over-Engineering". Bei aktivem Flag
# überspringt core/task_manager.py._is_micro_task() (rein deterministisch aus dem bereits
# erstellten Aufgabenplan, KEIN zusätzlicher LLM-Aufruf) Delegation+Konsolidierung für
# Fachbereiche mit GENAU EINEM Mitglied, wenn die Gesamtaufgabe als klein eingestuft wurde -
# Fachbereiche mit mehreren Mitgliedern behalten die Teamleiter-Koordination immer, da dort
# echter Abstimmungsbedarf besteht (z.B. doppelte Parallel-Implementierungen vermeiden).
ENABLE_TASK_COMPLEXITY_SCALING: bool = os.getenv("ENABLE_TASK_COMPLEXITY_SCALING", "true").lower() in ("true", "1", "yes")

# Teamleiter-Koordination nur, wo sie echten Abstimmungsbedarf gibt: Delegation+Konsolidierung
# kosten pro Fachbereich zwei LLM-Aufrufe ohne eigenen Code. Fachbereiche mit weniger Mitgliedern
# als diesem Wert arbeiten direkt (die Aufgabe steht bereits im Plan). 1 = früheres Verhalten.
DEPARTMENT_LEAD_MIN_MEMBERS: int = int(os.getenv("DEPARTMENT_LEAD_MIN_MEMBERS", "2"))

# ──────────────────────────────────────────
# Arbeitsweise wie ein echtes Entwicklerteam
# ──────────────────────────────────────────
# Übergabe-Regel: Code-Entwickler prüfen ihre Dateien vor der Abgabe (core/handoff_check.py).
ENABLE_DEVELOPER_HANDOFF_GATE: bool = os.getenv("ENABLE_DEVELOPER_HANDOFF_GATE", "true").lower() in ("true", "1", "yes")
MAX_HANDOFF_RETRIES: int = int(os.getenv("MAX_HANDOFF_RETRIES", "2"))

# Deterministisches Projektgerüst nach der Planung (core/project_scaffold.py).
ENABLE_PROJECT_SCAFFOLD: bool = os.getenv("ENABLE_PROJECT_SCAFFOLD", "true").lower() in ("true", "1", "yes")

# Integrations-Checkpoint direkt nach der Entwicklungsphase: Pre-Flight + deterministische
# Autofixes + eine gezielte Fix-Runde, BEVOR Content/QA/Governance auf kaputtem Code aufbauen.
ENABLE_INTEGRATION_CHECKPOINT: bool = os.getenv("ENABLE_INTEGRATION_CHECKPOINT", "true").lower() in ("true", "1", "yes")

# Test-First: der tester arbeitet in der Entwicklungsphase parallel zu den Entwicklern gegen
# Akzeptanzkriterien und interface_contract.json, statt nachträglich in der QA-Phase.
ENABLE_TEST_FIRST: bool = os.getenv("ENABLE_TEST_FIRST", "true").lower() in ("true", "1", "yes")

# Reihenfolge wie in einer echten CI: erst echte Verifikation (Tests/Build), dann LLM-Review.
# Review-Funde werden danach behoben und durch einen kurzen Regressionstest bestätigt.
ENABLE_REVIEW_AFTER_VERIFICATION: bool = os.getenv("ENABLE_REVIEW_AFTER_VERIFICATION", "true").lower() in ("true", "1", "yes")

# Abnahme gegen die ursprüngliche Anforderung (P4-2, ROADMAP_TEMP.md, core/acceptance_check.py):
# der product_owner-Agent destilliert den Auftragstext zu Beginn in eine Anforderungsliste und
# prüft sie am Ende read-only gegen den tatsächlichen Code - die Definition of Done prüft sonst
# nur technische Eigenschaften (Tests grün, App startet), nie ob geliefert wurde, was bestellt
# war. Zwei zusätzliche product_owner-LLM-Aufrufe je Lauf mit geschriebenem Code.
ENABLE_ACCEPTANCE_CHECK: bool = os.getenv("ENABLE_ACCEPTANCE_CHECK", "true").lower() in ("true", "1", "yes")

# Budget-Anteile der Generierungsphase je Fachbereich (Summe <= 1.0). Ein Fachbereich, der seinen
# Anteil nicht braucht, gibt ihn an die folgenden ab; ein optionaler Fachbereich (Design/Content)
# wird übersprungen, wenn sonst Entwicklung/QA nicht mehr ihren Mindestanteil erreichen würden.
PHASE_TOKEN_SHARES: dict[str, float] = {
    "planning_lead": float(os.getenv("PHASE_SHARE_PLANNING", "0.12")),
    "design_lead": float(os.getenv("PHASE_SHARE_DESIGN", "0.06")),
    "dev_lead": float(os.getenv("PHASE_SHARE_DEV", "0.45")),
    "content_lead": float(os.getenv("PHASE_SHARE_CONTENT", "0.07")),
    "qa_lead": float(os.getenv("PHASE_SHARE_QA", "0.18")),
    "governance_lead": float(os.getenv("PHASE_SHARE_GOVERNANCE", "0.12")),
}
OPTIONAL_PHASE_IDS: frozenset[str] = frozenset({"design_lead", "content_lead"})

# ──────────────────────────────────────────
# Hartes Lauf-Budget (echter Abbruch statt nur Reporting)
# ──────────────────────────────────────────
# core/quota_estimator.py zeigt den Tokenverbrauch nur an – ohne Obergrenze kann ein
# einzelner Lauf (z.B. durch mehrere Verifikations-Fixversuche mit dem kostenpflichtigen
# ORCHESTRATOR_MODEL/Heavy-Agenten) unbegrenzt weiterlaufen. MAX_RUN_TOKENS=0 deaktiviert
# das Budget vollständig; setze z.B. MAX_RUN_TOKENS=300000 in der .env, um
# agents/orchestrator.py nach Erreichen dieses Werts die verbleibenden Fachbereichs-Phasen,
# Verifikations-Fixversuche sowie Retrospektive/Selbstoptimierung übersprungen ausliefern
# zu lassen (die bis dahin erarbeiteten Ergebnisse werden trotzdem synthetisiert).
#
# Nutzeranfrage (Token-Effizienz-/Budget-Flexibilisierung, 2026-09-22): der bisherige
# Standardwert (300.000) brach komplexe Projekte real vorzeitig mit `budget_aborted: true`
# ab, bevor Verifikation/Fix-Schleifen überhaupt liefen. Der Fallback-Wert hier entspricht
# jetzt der "standard"-Stufe aus TASK_COMPLEXITY_TOKEN_BUDGETS unten - agents/orchestrator/
# department.py._run_department_hierarchy() ersetzt ihn zur Laufzeit ohnehin durch die zur
# jeweiligen Aufgabe passende Stufe (micro/standard/complex), solange kein expliziter
# `--max-tokens`-Aufruf (main.py `--goal`, `/goal`-Befehl) das Budget fest vorgibt.
MAX_RUN_TOKENS: int = int(os.getenv("MAX_RUN_TOKENS", "1500000"))

# Komplexitäts-basierte Lauf-Budgets: core/task_manager.is_micro_task()/is_complex_task()
# klassifizieren einen Aufgabenplan bereits deterministisch (ohne Zusatz-LLM-Aufruf) in
# micro/standard/complex - agents/orchestrator/department.py nutzt dieselbe Klassifikation,
# um das Lauf-Budget passend zu wählen, statt EIN starres Limit für triviale Einzeiler UND
# breite Mehr-Fachbereichs-Projekte gleichermaßen anzuwenden. Greift nur, wenn
# ENABLE_TASK_COMPLEXITY_SCALING aktiv ist UND kein expliziter `--max-tokens`-Override
# vorliegt (agents/orchestrator/__init__.py._max_run_tokens_overridden).
TASK_COMPLEXITY_TOKEN_BUDGETS: dict[str, int] = {
    "micro": int(os.getenv("MICRO_TASK_TOKEN_BUDGET", "800000")),
    "standard": int(os.getenv("STANDARD_TASK_TOKEN_BUDGET", "1500000")),
    "complex": int(os.getenv("COMPLEX_TASK_TOKEN_BUDGET", "2500000")),
}

# Mindestreserve für die Verifikations-/Fix-Phasen in ABSOLUTEN Tokens, zusätzlich zum
# anteiligen VERIFICATION_TOKEN_RESERVE_RATIO unten - bei einem kleinen MAX_RUN_TOKENS
# (z.B. der micro-Stufe, 800.000) ergäbe der Standard-Anteil von 15% nur 120.000 Tokens
# Reserve, was für eine echte Fix-Iteration (Testlauf + LLM-Korrektur + erneuter Testlauf)
# oft nicht reicht. agents/orchestrator/budget.py._generation_budget_exceeded() nimmt
# deshalb das Maximum aus Anteils- und Mindestreserve.
MIN_VERIFICATION_TOKEN_RESERVE: int = int(os.getenv("MIN_VERIFICATION_TOKEN_RESERVE", "200000"))

# Team-Retrospektive (Verbesserungsvorschlag "Budget-Reserve für Verifikation"): mehrere reale
# Läufe (u.a. incidentpilot) erschöpften MAX_RUN_TOKENS bereits in der Code-Generierungsphase
# ("🚫 Lauf-Budget erreicht – Verifikation nach Versuch 0 abgebrochen") - der Teil, der Tests
# tatsächlich ausführt und echte Fehler zurückspielt (also Autonomie überhaupt erst beweist),
# bekam dadurch nie eine Chance zu laufen. VERIFICATION_TOKEN_RESERVE_RATIO reserviert einen
# Anteil von MAX_RUN_TOKENS exklusiv für die Verifikations-/Fix-Phasen: die Generierungsphase
# (agents/orchestrator/department.py._run_department_hierarchy) bricht bereits bei
# MAX_RUN_TOKENS * (1 - RESERVE) ab, während die Verifikations-/Governance-Fix-Schleifen
# (agents/orchestrator/verification.py) weiterhin gegen das volle MAX_RUN_TOKENS prüfen. 0.0
# deaktiviert die Reserve (früheres Verhalten, gesamtes Budget für Generierung verfügbar).
VERIFICATION_TOKEN_RESERVE_RATIO: float = float(os.getenv("VERIFICATION_TOKEN_RESERVE_RATIO", "0.15"))

# ──────────────────────────────────────────
# Plan-Freigabe-Gate (Vorschau + Bestätigung VOR Tokenverbrauch)
# ──────────────────────────────────────────
# Bisher sah der Nutzer den zerlegten Aufgabenplan (welche Spezialisten, welche Teilaufgabe)
# erst im FERTIGEN Ergebnis – bei einer größeren, vom Modell großzügig interpretierten
# Anfrage gab es keine Möglichkeit, vor dem eigentlichen (kostenpflichtigen) Lauf gegenzu-
# steuern. interface/cli.py zeigt den Plan jetzt vorab und lässt ihn bestätigen, WENN er
# mindestens PLAN_CONFIRMATION_MIN_TASKS Teilaufgaben umfasst – kleinere, klar umrissene
# Aufgaben (z.B. "aktualisiere die README") laufen weiterhin ohne Zusatz-Klick durch, um den
# Alltagsfall nicht mit unnötiger Rückfrage zu belasten. Rein CLI-seitig (siehe
# Orchestrator.process(plan_confirmation_callback=...)) – Dashboard/MCP-Aufrufe reichen
# keinen Callback durch und bleiben dadurch unverändert nicht-interaktiv.
ENABLE_PLAN_CONFIRMATION: bool = os.getenv("ENABLE_PLAN_CONFIRMATION", "true").lower() in ("true", "1", "yes")
PLAN_CONFIRMATION_MIN_TASKS: int = int(os.getenv("PLAN_CONFIRMATION_MIN_TASKS", "3"))

# ──────────────────────────────────────────
# Start-Preflight in der interaktiven CLI (KI-Team-Gesamtanalyse, Sicherheitsmaßnahme)
# ──────────────────────────────────────────
# core/model_preflight.py (bisher nur über `python main.py --check-models` manuell abrufbar)
# pingt jetzt automatisch EINMAL beim Start jeder interaktiven CLI-Sitzung (interface/cli.py
# CLIInterface.run()) alle Komplexitätsstufen an, BEVOR der Nutzer die erste Aufgabe tippen
# kann - inkl. einer Ampel-Empfehlung (core/model_preflight.assess_run_readiness()), ob sich
# ein Projektlauf gerade lohnt. Bewusst EINMAL pro Sitzung, nicht vor jeder einzelnen Aufgabe:
# jeder Preflight-Ping ist ein echter, budgetzählender API-Call gegen bis zu 6 Modellstufen -
# das vor JEDER Chat-Nachricht zu wiederholen würde genau das knappe Tageskontingent
# verbrauchen, vor dessen Erschöpfung gewarnt werden soll. Ein manueller Re-Check mitten in
# der Sitzung bleibt über `/modelle` möglich (z.B. nach einer Quota-Reset-Wartezeit).
# Default AN, da die Warnung genau den Fall abdeckt, der beim CertPulse-Lauf (12.09.2026) einen
# von vornherein aussichtslosen, 319k-Token-Lauf verursachte - abschaltbar für Automatisierung/
# Tests, die keinen wartenden Nutzer vor dem Bildschirm haben.
ENABLE_STARTUP_MODEL_PREFLIGHT: bool = os.getenv("ENABLE_STARTUP_MODEL_PREFLIGHT", "true").lower() in ("true", "1", "yes")
STARTUP_MODEL_PREFLIGHT_TIMEOUT_SECONDS: float = float(os.getenv("STARTUP_MODEL_PREFLIGHT_TIMEOUT_SECONDS", "20"))

# ──────────────────────────────────────────
# PR-Workflow: Feature-Branch + Pull Request statt Direct-Push auf einen Hauptbranch
# ──────────────────────────────────────────
# Bisher committete/pushte agents/github_agent.py IMMER direkt auf den gerade ausgecheckten
# Branch – bei einem frischen/geladenen Projekt i.d.R. "main". Ein echtes Team committet
# nicht direkt auf den Hauptbranch: eigener Feature-Branch pro Aufgabe, Pull Request, Merge
# erst nach grüner CI und Freigabe. ENABLE_PR_WORKFLOW=true (Standard) lässt
# interface/cli.py._ask_for_git_push() automatisch einen Feature-Branch anlegen und einen PR
# per `gh pr create` öffnen, WENN der aktuelle Branch einer der GIT_PROTECTED_BRANCHES ist –
# ist bereits ein Feature-Branch aktiv (z.B. manuell ausgecheckt oder ein isolierter
# Selbstverbesserungs-Worktree, siehe core/git_isolation.py), wird ganz normal direkt darauf
# committet/gepusht, da das ohnehin schon kein Hauptbranch ist. Ohne installierte/eingeloggte
# `gh`-CLI (agents/github_agent.py.gh_ready()) fällt der Ablauf automatisch auf das bisherige
# Direct-Push-Verhalten zurück (Graceful Degradation) – der Nutzer wird darüber informiert,
# PUSHT aber trotzdem, statt komplett zu blockieren.
ENABLE_PR_WORKFLOW: bool = os.getenv("ENABLE_PR_WORKFLOW", "true").lower() in ("true", "1", "yes")
GIT_PROTECTED_BRANCHES: tuple[str, ...] = tuple(
    b.strip() for b in os.getenv("GIT_PROTECTED_BRANCHES", "main,master").split(",") if b.strip()
)
# `/protect-branch` (interface/cli.py) aktiviert echte GitHub-Branch-Protection (Pflicht-
# Reviews vor dem Merge, kein Force-Push/Löschen) für den Hauptbranch – der PR-Workflow oben
# verhindert nur, dass DIESES Tool direkt auf den Hauptbranch pusht, nicht dass ein Mensch (oder
# ein anderes Tool) es weiterhin tut. Bewusst ein manueller, einmaliger CLI-Befehl statt eines
# automatischen Laufs beim Start – eine Repo-Einstellungsänderung mit echten
# Admin-API-Rechten verdient dieselbe bewusste Bestätigung wie `/deploy`, nicht ein
# stillschweigender Seiteneffekt.
BRANCH_PROTECTION_REQUIRED_REVIEWS: int = int(os.getenv("BRANCH_PROTECTION_REQUIRED_REVIEWS", "1"))

# ──────────────────────────────────────────
# Autonome, getriggerte Arbeit: GitHub-Issues als Backlog (core/issue_watcher.py)
# ──────────────────────────────────────────
# Ergänzt den PR-Workflow oben um die Trigger-Seite: `python main.py --check-issues` (von
# außen z.B. per Cron/Windows-Taskplaner/GitHub-Actions-Schedule alle 10-15 Min aufgerufen)
# sucht eigenständig nach offenen Issues mit ISSUE_TRIGGER_LABEL und arbeitet sie über den
# bestehenden Orchestrator + PR-Workflow ab – OHNE dass jemand manuell die CLI bedient. Nur
# Issues mit einem EXPLIZITEN Opt-in-Label werden aufgegriffen (kein wahlloses Abarbeiten
# JEDES offenen Issues) – ein echtes Team arbeitet auch einen triagierten Backlog ab, nicht
# den kompletten, ungefilterten Issue-Tracker. Die drei weiteren Label dienen als
# Zustandsmaschine gegen Doppelbearbeitung bei überlappenden Poll-Zyklen (siehe
# core/issue_watcher.py: ISSUE_IN_PROGRESS_LABEL wird VOR dem Lauf gesetzt, nicht danach).
ISSUE_TRIGGER_LABEL: str = os.getenv("ISSUE_TRIGGER_LABEL", "ai-team")
ISSUE_IN_PROGRESS_LABEL: str = os.getenv("ISSUE_IN_PROGRESS_LABEL", "ai-team-in-progress")
ISSUE_DONE_LABEL: str = os.getenv("ISSUE_DONE_LABEL", "ai-team-done")
ISSUE_BLOCKED_LABEL: str = os.getenv("ISSUE_BLOCKED_LABEL", "ai-team-blocked")
# Konservativ auf 1 Issue pro Poll-Zyklus begrenzt (Standard) – verhindert, dass ein einzelner
# Cron-Tick nach längerer Pause gleich eine ganze Batch teurer Läufe lostritt; der nächste
# Zyklus greift das nächste Issue auf.
ISSUE_POLL_MAX_PER_CYCLE: int = int(os.getenv("ISSUE_POLL_MAX_PER_CYCLE", "1"))

# ──────────────────────────────────────────
# Dependency-Watch: automatischer Update-PR statt reiner Warnung (core/dependency_updater.py)
# ──────────────────────────────────────────
# core/dependency_watch.py (`python main.py --check-dependencies`) fand bekannte CVEs in
# Workspace-Projekten bisher nur und meldete sie als blockiertes Ticket – ein echtes Team hat
# einen Dependabot-/Renovate-artigen Mechanismus, der direkt einen fertigen Update-PR öffnet.
# ENABLE_DEPENDENCY_AUTO_UPDATE=true (Standard) hebt betroffene Python-Pakete (requirements.txt,
# nur wenn pip-audit eine `fix_versions`-Angabe liefert) automatisch an und öffnet dafür über
# denselben agents/github_agent.py-PR-Mechanismus wie core/issue_watcher.py einen Pull Request –
# OHNE menschliche Bestätigung (unbeaufsichtigter Poll-Zyklus, ein Mensch reviewt/merged den PR
# anschließend ganz normal über GitHub, siehe /protect-branch oben für einen erzwungenen
# Review vor dem Merge). Node/Rust/Go bleiben bewusst bei der reinen Meldung (siehe
# core/dependency_updater.py-Modul-Docstring für die Begründung).
ENABLE_DEPENDENCY_AUTO_UPDATE: bool = os.getenv("ENABLE_DEPENDENCY_AUTO_UPDATE", "true").lower() in ("true", "1", "yes")

# ──────────────────────────────────────────
# Backlog: Priorität, Schätzung & WIP-Limit (core/backlog_store.py)
# ──────────────────────────────────────────
# core/backlog_store.py hielt bisher nur eine flache Ticket-Liste ohne Priorisierung oder
# Kapazitätsbegriff - ausreichend für Einzelaufträge, aber ohne jede Steuerungsmöglichkeit,
# sobald mehrere Tickets gleichzeitig anstehen (z.B. `/backlog-add` für mehrere geplante
# Aufgaben). BACKLOG_WIP_LIMIT_IN_PROGRESS=0 (Standard) deaktiviert die Warnung vollständig -
# bewusst nur eine WARNUNG (`/backlog` in interface/cli.py), kein Hard-Block: ein echtes
# Kanban-WIP-Limit ist eine Team-Disziplin-Regel, keine technische Zwangsbeschränkung, die
# einen bereits laufenden Auftrag verhindern dürfte.
BACKLOG_WIP_LIMIT_IN_PROGRESS: int = int(os.getenv("BACKLOG_WIP_LIMIT_IN_PROGRESS", "0"))

# ──────────────────────────────────────────
# Selbstgesteuertes Backlog-Abarbeiten (core/backlog_worker.py)
# ──────────────────────────────────────────
# Realer Fund: core/issue_watcher.py reagiert nur auf NEU gelabelte GitHub-Issues - "todo"-
# Tickets aus `/backlog-add` (interface/cli.py) oder dem Dashboard wurden bisher laut eigenem
# Docstring ("Führt selbst nichts aus") NIE automatisch angegangen, ein Mensch musste die
# Aufgabe irgendwann erneut manuell in den Chat schreiben. Ein echtes Team wartet nicht auf ein
# Label, um den nächsten Backlog-Punkt zu beginnen. `python main.py --work-backlog` (analog zu
# --check-issues) greift eigenständig das höchstpriorisierte, abhängigkeitsfreie "todo"-Ticket
# auf (core/backlog_store.py.is_ticket_ready()) und arbeitet es über denselben Orchestrator +
# PR-Workflow ab. BACKLOG_WORKER_MAX_PER_CYCLE=1 (Standard) - dieselbe konservative Begrenzung
# wie ISSUE_POLL_MAX_PER_CYCLE, aus demselben Grund (kein Cron-Tick soll nach einer Pause gleich
# eine ganze Batch teurer Läufe lostreten).
BACKLOG_WORKER_MAX_PER_CYCLE: int = int(os.getenv("BACKLOG_WORKER_MAX_PER_CYCLE", "1"))
# Anders als die reine WIP-Anzeige-Warnung oben (bewusst kein Hard-Block für einen MENSCHEN,
# der bewusst trotzdem eine weitere Aufgabe startet): hier gibt es NIEMANDEN, der übersteuern
# könnte - ein erreichtes WIP-Limit blockiert den autonomen Worker deshalb hart, bis laufende
# Arbeit abgeschlossen ist. 0 (Standard) = deaktiviert, dieselbe Konvention wie oben.
BACKLOG_WORKER_WIP_LIMIT: int = int(os.getenv("BACKLOG_WORKER_WIP_LIMIT", "0"))
# Team-Optimierung (Retrospektive 2026-09-03): ein von der Governance-/Verifikations-Fix-
# Schleife (agents/orchestrator/verification.py) eröffnetes "blocked"-Ticket zu einem
# ungelösten kritischen Befund (z.B. unresolved-governance-critical-<slug>) blieb bisher für
# immer liegen - core/backlog_worker.py griff nur "todo"-Tickets aus den Quellen "cli"/
# "dashboard" auf. Ein solches Ticket wird jetzt selbst als eigenständig aufgreifbare Arbeit
# behandelt (siehe core/backlog_worker.py._governance_retry_pool()), aber begrenzt auf
# MAX_GOVERNANCE_TICKET_RETRIES automatische Wiederholungsversuche - ein Befund, den das Team
# nachweislich wiederholt nicht lösen kann, soll nicht endlos Budget in identischen
# Fehlversuchen verbrennen, sondern nach Erreichen der Grenze sichtbar für eine menschliche
# Prüfung liegen bleiben (retries auf dem Ticket selbst, siehe core/backlog_store.py.Ticket).
MAX_GOVERNANCE_TICKET_RETRIES: int = int(os.getenv("MAX_GOVERNANCE_TICKET_RETRIES", "2"))

# ──────────────────────────────────────────
# Produktions-Monitoring nach dem Deploy (core/production_monitor.py)
# ──────────────────────────────────────────
# Realer Fund: core/cloud_deployment.py kann ein Projekt echt live deployen (Fly.io/Vercel),
# aber danach schaute niemand mehr hin - kein echtes On-Call/SRE-Verhalten. `python main.py
# --check-deployments` (analog zu --check-issues/--work-backlog) prüft periodisch jede per
# `/deploy-cloud --real` deployte URL (core/deployment_status.py) auf echte Erreichbarkeit und
# eröffnet bei einem Ausfall automatisch ein Backlog-Ticket, statt dass ein Ausfall unbemerkt
# bleibt, bis ein Mensch zufällig selbst nachschaut.
DEPLOYMENT_HEALTH_CHECK_TIMEOUT_SECONDS: float = float(os.getenv("DEPLOYMENT_HEALTH_CHECK_TIMEOUT_SECONDS", "10.0"))

# ──────────────────────────────────────────
# Externe Benachrichtigung bei Vorfällen, die menschliche Aufmerksamkeit brauchen (core/notifier.py)
# ──────────────────────────────────────────
# core/issue_watcher.py (Cron-Poll-Zyklus) und interface/web_dashboard.py (Hintergrund-Jobs)
# laufen unbeaufsichtigt - anders als interface/cli.py sieht dort in dem Moment niemand aktiv
# zu, in dem etwas menschliche Aufmerksamkeit braucht (blockiertes Issue, rote CI, erreichtes
# Lauf-Budget, fehlgeschlagener Dashboard-Job). NOTIFY_WEBHOOK_URL="" (Standard) deaktiviert
# das Feature komplett - gesetzt, schickt core/notifier.py einen einfachen JSON-POST
# ({"text": "..."}, Slack-Incoming-Webhook-kompatibel) dorthin. Best-effort: ein Fehlschlag
# beim Senden darf NIE einen sonst erfolgreichen Lauf zum Scheitern bringen.
NOTIFY_WEBHOOK_URL: str = os.getenv("NOTIFY_WEBHOOK_URL", "")

# ──────────────────────────────────────────
# Web-Dashboard: sichere Standardwerte (nur lokal, optionaler Token für Netzwerkzugriff)
# ──────────────────────────────────────────
# Standardmäßig NUR auf localhost erreichbar (siehe interface/web_dashboard.py). Wer das
# Dashboard im Netzwerk erreichbar machen will (DASHBOARD_HOST auf eine nicht-lokale
# Adresse oder "0.0.0.0" setzen), MUSS zusätzlich DASHBOARD_AUTH_TOKEN setzen – sonst
# verweigert run_dashboard() bewusst den Start, weil sonst jeder im Netzwerk über
# POST /api/run einen vollen Agentenlauf mit echtem Datei-/Kommandozugriff auslösen könnte.
DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_AUTH_TOKEN: str = os.getenv("DASHBOARD_AUTH_TOKEN", "")

# Läuft in EINEM persistenten Event-Loop (siehe interface/web_dashboard.py) – mehrere Jobs
# können dadurch gefahrlos nebeneinander laufen (jeder mit einer FRISCHEN, isolierten
# Orchestrator-Instanz, damit sich Gesprächsverläufe nicht mischen), ohne die
# Thread-Sicherheits-Risiken echter OS-Thread-Parallelität für geteilte globale Zustände
# (token_guard, agent_knowledge_base, memory/cost_history.json, ...) einzugehen. Konservativer
# Standardwert (2), um kostenlose Provider-Rate-Limits nicht durch zu viele gleichzeitige
# Läufe unnötig zu strapazieren – bei Bedarf über .env erhöhen.
DASHBOARD_MAX_CONCURRENT_JOBS: int = int(os.getenv("DASHBOARD_MAX_CONCURRENT_JOBS", "2"))

# ── Ausführungs-Sandbox für Agenten-Code (core/docker_sandbox.py) ─────────────────────────
# "local" (Standard): Tests/pip/npm von Agenten-Code laufen direkt auf dem Host.
# "docker": dieselben Schritte laufen in einem Container, der NUR das Projektverzeichnis sieht -
# kein Zugriff auf die .env des Frameworks. Ohne erreichbaren Docker-Daemon wird gewarnt und
# lokal ausgeführt.
SANDBOX_BACKEND: str = os.getenv("SANDBOX_BACKEND", "local").strip().lower()
SANDBOX_PYTHON_IMAGE: str = os.getenv("SANDBOX_PYTHON_IMAGE", "python:3.12-slim")
SANDBOX_NODE_IMAGE: str = os.getenv("SANDBOX_NODE_IMAGE", "node:20-slim")
SANDBOX_MEMORY: str = os.getenv("SANDBOX_MEMORY", "2g")
SANDBOX_CPUS: str = os.getenv("SANDBOX_CPUS", "2")

# ──────────────────────────────────────────
# Autonomer Ziel- & Iterations-Loop (core/goal_loop.py)
# ──────────────────────────────────────────
# Maximale Anzahl aufeinanderfolgender Entwicklungsrunden, die der autonome
# Ziel-Loop (/goal, python main.py --goal) standardmäßig durchläuft, bis das
# Projektziel erreicht ist und alle Tests grün sind.
GOAL_LOOP_DEFAULT_MAX_ITERATIONS: int = int(os.getenv("GOAL_LOOP_DEFAULT_MAX_ITERATIONS", "5"))
GOAL_LOOP_EVAL_MODEL: str = os.getenv("GOAL_LOOP_EVAL_MODEL", GEMINI_STANDARD_MODEL)
# Kumulatives Token-Budget ÜBER ALLE Iterationen eines Ziel-Loops hinweg (0 = deaktiviert).
# MAX_RUN_TOKENS begrenzt nur einen einzelnen orchestrator.process()-Aufruf; ohne dieses
# zusätzliche Limit könnte der Loop dieses Budget bis zu max_iterations-mal hintereinander
# ausschöpfen, bevor er überhaupt abbricht.
GOAL_LOOP_MAX_TOTAL_TOKENS: int = int(os.getenv("GOAL_LOOP_MAX_TOTAL_TOKENS", "0"))

# ──────────────────────────────────────────
# Pfade
# ──────────────────────────────────────────
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR: str = os.path.join(BASE_DIR, "prompts")
MEMORY_DIR: str = os.path.join(BASE_DIR, "memory")
WORKSPACE_DIR: str = os.path.join(BASE_DIR, "workspace")

# ──────────────────────────────────────────
# Datenbasierte Selbstoptimierung (core/optimization_advisor.py)
# ──────────────────────────────────────────
# Team-Optimierung (Retrospektive 2026-09-04): core/optimization_advisor.py.analyze() erkennt
# bereits nach jedem Lauf datenbasiert, ob ein Agent mit einem ANDEREN Modell empirisch
# erfolgreicher wäre - das Ergebnis landete bisher AUSSCHLIESSLICH als Textabschnitt im
# Abschlussbericht, nie angewendet, sofern nicht ein Mensch ihn liest und manuell .env/config.py
# anpasst. Bei autonomen Läufen (--work-backlog, Cron) sieht das niemand. ENABLE_AUTO_MODEL_
# TUNING schließt diesen Kreislauf: bewusst standardmäßig AUS (Opt-in), damit das Verhalten nie
# überraschend einsetzt. Ist es aktiv, schreibt core/optimization_advisor.py.apply_auto_tuning()
# empirisch bessere Modellzuweisungen in AUTO_TUNED_MODELS_FILE - eine reine, jederzeit
# inspizier-/löschbare JSON-Datei (git-ignored wie jede memory/*.json), NIE eine automatische
# Änderung an dieser Datei selbst. get_model_for_agent() liest sie unten als NIEDRIGSTE
# Prioritätsstufe - ein expliziter .env-Rollen- oder Fachbereichs-Override (Schritt 1/2 dort)
# gewinnt IMMER, ein Mensch, der bewusst ein Modell festlegt, wird also nie überstimmt.
ENABLE_AUTO_MODEL_TUNING: bool = os.getenv("ENABLE_AUTO_MODEL_TUNING", "false").strip().lower() in ("true", "1", "yes")
AUTO_TUNED_MODELS_FILE: str = os.path.join(MEMORY_DIR, "auto_tuned_models.json")

# A/B-Tests für Modellzuweisungen (core/model_ab_trials.py): ein Modell-Vorschlag des
# Optimization-Advisors wird zunächst nur in MODEL_AB_TRIAL_SHARE der Läufe verwendet und erst nach
# MODEL_AB_MIN_TRIAL_CALLS echten Aufrufen anhand der Messwerte übernommen oder verworfen.
ENABLE_MODEL_AB_TRIALS: bool = os.getenv("ENABLE_MODEL_AB_TRIALS", "true").strip().lower() in ("true", "1", "yes")
MODEL_AB_TRIAL_SHARE: float = float(os.getenv("MODEL_AB_TRIAL_SHARE", "0.2"))
MODEL_AB_MIN_TRIAL_CALLS: int = int(os.getenv("MODEL_AB_MIN_TRIAL_CALLS", "8"))
MODEL_AB_TRIALS_FILE: str = os.path.join(MEMORY_DIR, "model_ab_trials.json")

# ──────────────────────────────────────────
# Automatisierter Root-Cause-Analyst (core/root_cause_analyst.py)
# ──────────────────────────────────────────
# Gesamtsystem-Analyse 2026-09-14, Punkt 3.1: die Tiefenanalysen, die zu den wichtigsten
# Framework-Fixes geführt haben (Verification Reserve Paradox, Ghost-Frontend, falsches
# Fehler-Routing), entstanden bisher AUSSCHLIESSLICH in manuellen Analyse-Sitzungen - der
# automatisch laufende Retrospektive-/Trainer-Schritt bekommt nur gekürzte Prosa-Auszüge OHNE
# Tool-Zugriff. Anders als ENABLE_AUTO_MODEL_TUNING oben ist dies standardmäßig AN: der
# Root-Cause-Analyst ändert selbst NIE automatisch Code (core/root_cause_analyst.py legt nur
# Vorschlags-Tickets mit source="root_cause_analysis" an, NICHT in core/backlog_worker.py.
# _AUTONOMOUS_SOURCES enthalten - dieselbe Vorsicht wie core/roadmap_advisor.py), das Risiko
# einer überraschenden Verhaltensänderung besteht hier also nicht - nur ein zusätzlicher,
# gezielt getriggerter LLM-Aufruf bei echten Warnsignalen (core/root_cause_analyst.should_
# trigger()), dessen Tokenkosten Nutzer per .env dennoch abschalten können.
ENABLE_ROOT_CAUSE_ANALYST: bool = os.getenv("ENABLE_ROOT_CAUSE_ANALYST", "true").strip().lower() in ("true", "1", "yes")


def _env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in ("1", "true", "yes")


# ──────────────────────────────────────────
# Team-Analyse 2026-09-15 (Teil 2): Kosten, Kommunikation, Überwachung
# ──────────────────────────────────────────
# Agent-Trainer nur bei echten Ausreißern statt nach jedem Lauf (vorher Schwelle 4000 Tokens).
TRAINER_HIGH_USAGE_TOKENS_PER_CALL: int = int(os.getenv("TRAINER_HIGH_USAGE_TOKENS_PER_CALL", "150000"))
TRAINER_MAX_TOOL_ITERATIONS: int = int(os.getenv("TRAINER_MAX_TOOL_ITERATIONS", "3"))

# Team-Board (core/team_board.py): Übergabe-Notizen, Datei-Owner, Schnittstellen-Status und Fragen
# zwischen Agenten statt 3000 Zeichen gekürztem Ergebnistext.
ENABLE_TEAM_BOARD: bool = _env_flag("ENABLE_TEAM_BOARD", True)
TEAM_BOARD_PROMPT_CHARS: int = int(os.getenv("TEAM_BOARD_PROMPT_CHARS", "3500"))
# ask_teammate: ein Agent fragt einen Kollegen (kurzer Nur-Lese-Aufruf des Kollegen).
ENABLE_ASK_TEAMMATE: bool = _env_flag("ENABLE_ASK_TEAMMATE", True)
TEAMMATE_QUESTIONS_PER_RUN: int = int(os.getenv("TEAMMATE_QUESTIONS_PER_RUN", "8"))
TEAMMATE_QUESTIONS_PER_AGENT: int = int(os.getenv("TEAMMATE_QUESTIONS_PER_AGENT", "2"))
TEAMMATE_ANSWER_TOOL_ITERATIONS: int = int(os.getenv("TEAMMATE_ANSWER_TOOL_ITERATIONS", "2"))

# Kontext-Verdichtung im Werkzeug-Loop (core/context_compaction.py): große Werkzeug-Ergebnisse älter
# als die letzten N Modell-Runden werden durch eine Vorschau ersetzt (~95 % der Tokens waren Prompt).
ENABLE_CONTEXT_COMPACTION: bool = _env_flag("ENABLE_CONTEXT_COMPACTION", True)
CONTEXT_COMPACTION_KEEP_ROUNDS: int = int(os.getenv("CONTEXT_COMPACTION_KEEP_ROUNDS", "1"))
CONTEXT_COMPACTION_MIN_CHARS: int = int(os.getenv("CONTEXT_COMPACTION_MIN_CHARS", "500"))
CONTEXT_COMPACTION_DEDUPLICATE_READS: bool = _env_flag("CONTEXT_COMPACTION_DEDUPLICATE_READS", True)
# Fachbereichs-Konsolidierung per LLM (10k-18k Tokens je Lead) oder deterministisch aus Ergebnissen
# und Team-Board-Übergaben (0 Tokens). Die Delegation zu Phasenbeginn bleibt ein LLM-Aufruf.
ENABLE_LLM_DEPARTMENT_CONSOLIDATION: bool = _env_flag("ENABLE_LLM_DEPARTMENT_CONSOLIDATION", False)

# Testtiefe (core/test_depth.py): Anteil der Backend-Routen, die in Tests aufgerufen werden müssen.
# Eine grüne, aber flache Suite bekommt EINE gezielte tester-Runde; bleibt sie zu flach, blockiert die DoD.
ENABLE_TEST_DEPTH_GATE: bool = _env_flag("ENABLE_TEST_DEPTH_GATE", True)
MIN_ROUTE_TEST_RATIO: float = float(os.getenv("MIN_ROUTE_TEST_RATIO", "0.6"))

# P4-3 (ROADMAP_TEMP.md): ergänzendes, rein informatives Signal - Anteil der öffentlichen
# Funktionen/Klassen in app/core/, app/services/, app/domain/, app/logic/, die in mindestens
# einem Test IMPORTIERT UND AUFGERUFEN werden (core/test_depth.py.analyze_domain_logic_depth(),
# core/code_graph.py). Deckt genau die Lücke ab, die die rein routenbasierte Testtiefe oben
# nicht sieht: `cachegrid_proxy` (1 Route) galt mit 100% Routenabdeckung als getestet, obwohl die
# eigentliche Fachlogik (LRU-Eviction, TTL-Verfall, Thundering-Herd-Mutex) ungetestet blieb.
# Bewusst NICHT blockierend (kein eigener Fix-Loop, required=False in der Definition of Done):
# ein AST-Aufruf-Abgleich hat reale blinde Flecken (Decorators, Dependency Injection, dynamischer
# Dispatch) - ohne Kalibrierung an echten Läufen wäre ein blockierendes Gate hier ein Risiko für
# viele falsch-positive Blockaden bisher grüner Projekte.
ENABLE_DOMAIN_LOGIC_DEPTH_SIGNAL: bool = _env_flag("ENABLE_DOMAIN_LOGIC_DEPTH_SIGNAL", True)
MIN_DOMAIN_LOGIC_TEST_RATIO: float = float(os.getenv("MIN_DOMAIN_LOGIC_TEST_RATIO", "0.5"))

# Erzwungener Werkzeug-Aufruf für Code-Rollen ohne gespeicherte Datei (erste und Rettungs-Iteration):
# strukturelle Antwort auf "Code im Chat statt write_file", das Lernregeln allein nicht lösten.
ENABLE_FORCED_TOOL_CALL: bool = _env_flag("ENABLE_FORCED_TOOL_CALL", True)

# Rote Workspace-Projekte automatisch als Nachbesserungs-Ticket einplanen (core/red_project_repair.py),
# höchstens N neue Tickets pro Backlog-Worker-Poll (0 = aus).
RED_PROJECT_REPAIR_PER_POLL: int = int(os.getenv("RED_PROJECT_REPAIR_PER_POLL", "1"))

# Agenten-Watchdog (core/agent_watchdog.py): greift live ein bei Lesen ohne Schreiben, wiederholtem
# Neuschreiben, wiederholten Werkzeug-Fehlern, explodierendem Kontext und zu teuren Einzelaufgaben.
ENABLE_AGENT_WATCHDOG: bool = _env_flag("ENABLE_AGENT_WATCHDOG", True)

# Review-Paar Frontend ↔ Backend im Integrations-Checkpoint (core/contract_verifier.py).
ENABLE_CONTRACT_REVIEW: bool = _env_flag("ENABLE_CONTRACT_REVIEW", True)
WATCHDOG_READ_STREAK_LIMIT: int = int(os.getenv("WATCHDOG_READ_STREAK_LIMIT", "3"))
WATCHDOG_MAX_PROMPT_TOKENS: int = int(os.getenv("WATCHDOG_MAX_PROMPT_TOKENS", "80000"))
WATCHDOG_TASK_TOKEN_CAP: int = int(os.getenv("WATCHDOG_TASK_TOKEN_CAP", "250000"))

# ──────────────────────────────────────────
# Obsidian Vault & Gedächtnis-Synchronisation (core/obsidian_sync.py)
# ──────────────────────────────────────────
OBSIDIAN_VAULT_PATH: str = os.getenv("OBSIDIAN_VAULT_PATH", r"C:\Users\sche-\Desktop\Obsidian")
OBSIDIAN_TARGET_DIR: str = os.getenv("OBSIDIAN_TARGET_DIR", r"02 Areas\Lernprojekte\AI-Softwareentwickler-Team")
OBSIDIAN_AUTO_SYNC: bool = os.getenv("OBSIDIAN_AUTO_SYNC", "true").strip().lower() in ("true", "1", "yes")
OBSIDIAN_SYNC_FILES: list[str] = [
    f.strip()
    for f in os.getenv(
        # Realer Fund: ".env" stand hier bisher als Klartext-Sync-Ziel drin - core/
        # obsidian_sync.py kopiert Dateien unredigiert, dadurch landeten ECHTE, aktive
        # API-Keys (Gemini/Groq/DeepSeek/Tavily/OpenRouter/HuggingFace) im Vault
        # (".env" + generiertes ".env.md"), außerhalb des durch dieses Repo kontrollierten
        # .gitignore-Schutzes - ein Obsidian-Vault wird typischerweise über einen eigenen
        # Sync-Dienst (Obsidian Sync, iCloud, Dropbox, Plugins) verteilt, der von diesem
        # Projekt nicht kontrolliert wird. ".env.example" enthält dieselbe Struktur/
        # Dokumentation für das Gedächtnis, aber nie echte Secrets (nur leere Platzhalter).
        "OBSIDIAN_SYNC_FILES",
        ".env.example,README.md,.gitignore,ARCHITECTURE.md,CHANGELOG.md,CLAUDE.md,.claudeignore,ROADMAP_TEMP.md,skills/ai-dev-team/SKILL.md,skills/ai-dev-team/README.md,logs/FEHLERANALYSE_KI_TEAM_20260916.md,logs/FEHLERANALYSE_PULSE_QUEUE_20260922_TEMP.md,logs/FEHLERANALYSE_SMART_KNOWLEDGE_HUB_20260922_TEMP.md",
    ).split(",")
    if f.strip()
]




# ──────────────────────────────────────────
# Validierung
# ──────────────────────────────────────────
def validate_config() -> list[str]:
    """Prüft ob mindestens ein API-Key vorhanden ist."""
    errors = []
    if not (GEMINI_API_KEY or GROQ_API_KEY or DEEPSEEK_API_KEY or OPENROUTER_API_KEY or HUGGINGFACE_API_KEY or ANTHROPIC_API_KEY):
        errors.append("Kein API-Key in der .env Datei gefunden")
    return errors
