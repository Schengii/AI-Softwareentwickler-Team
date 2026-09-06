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
#
# Anthropic bietet – anders als Gemini – KEIN dauerhaftes Gratis-Kontingent (nur ein
# einmaliges kleines Startguthaben für neue Accounts). Solange kein ANTHROPIC_API_KEY
# gesetzt ist, springt core/llm_factory.py bei allen HEAVY-Aufgaben deshalb zunächst auf
# GROQ_HEAVY_MODEL – ein starkes, aber tatsächlich kostenloses Open-Weight-Modell mit
# großzügigem Rate-Limit – und erst danach auf die Gemini-Standard-Stufe aus, statt
# sofort auf das schwächste verfügbare Modell abzurutschen.
GEMINI_LITE_MODEL: str = os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite")
GEMINI_STANDARD_MODEL: str = os.getenv("GEMINI_STANDARD_MODEL", "gemini-3.8-flash")
GEMINI_HEAVY_MODEL: str = os.getenv("GEMINI_HEAVY_MODEL", "gemini-pro-latest")

CLAUDE_LITE_MODEL: str = os.getenv("CLAUDE_LITE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_STANDARD_MODEL: str = os.getenv("CLAUDE_STANDARD_MODEL", "claude-sonnet-5")
CLAUDE_HEAVY_MODEL: str = os.getenv("CLAUDE_HEAVY_MODEL", "claude-opus-5")

# Kostenlose Ausweich-Stufe für HEAVY-Aufgaben, falls kein ANTHROPIC_API_KEY vorhanden ist.
GROQ_HEAVY_MODEL: str = os.getenv("GROQ_HEAVY_MODEL", "groq:openai/gpt-oss-120b")

# Proaktive Rate-Begrenzung (core/rate_limiter.py): verhindert, dass viele parallele Agenten
# (asyncio.gather bei 3+-Mitglieder-Fachbereichen) Gemini gleichzeitig anstürmen und dessen
# Minutenlimit dadurch ERST auslösen. Bewusst konservativ unter typischen kostenlosen
# Gemini-RPM-Limits gehalten (Reserve für gleichzeitige Nutzung außerhalb dieses Frameworks).
GEMINI_MAX_CALLS_PER_MINUTE: int = int(os.getenv("GEMINI_MAX_CALLS_PER_MINUTE", "12"))

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


def get_model_for_agent(agent_id: str) -> str:
    """Ermittelt das konfigurierte LLM-Modell für einen Agenten unter Berücksichtigung von Overrides."""
    # 1. Spezifischer Rollen-Override
    if agent_id in AGENT_MODELS and os.getenv(f"{agent_id.upper()}_MODEL"):
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

    # 3. Datenbasierte Selbstoptimierung (opt-in, siehe ENABLE_AUTO_MODEL_TUNING oben) - NUR
    # wenn weder ein Rollen- noch ein Fachbereichs-Override explizit gesetzt ist, greift eine
    # zuvor von core/optimization_advisor.py empirisch ermittelte, bessere Modellzuweisung.
    if ENABLE_AUTO_MODEL_TUNING:
        auto_tuned = _read_auto_tuned_model(agent_id)
        if auto_tuned:
            return auto_tuned

    # 4. Standard-Zuordnung aus AGENT_MODELS oder Fallback
    return AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)


def _read_auto_tuned_model(agent_id: str) -> str:
    """Liest eine zuvor automatisch vorgeschlagene Modellzuweisung für `agent_id` aus
    AUTO_TUNED_MODELS_FILE - leerer String, falls keine existiert oder die Datei fehlt/beschädigt
    ist (nie ein Absturz nur wegen dieser rein optionalen Optimierung)."""
    path = Path(AUTO_TUNED_MODELS_FILE)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    entry = data.get(agent_id) if isinstance(data, dict) else None
    return entry.get("model", "") if isinstance(entry, dict) else ""


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

# Realer Fund (Bestandsaufnahme cloudvault-Projekt): 13 ruff-Lint-Funde standen im
# Verifikations-Protokoll, wurden aber nie behoben - Lint ist rein informativ (siehe
# core/verifier/lint.py.LintReport-Docstring), kein Agent war je beauftragt, sie zu fixen.
# ENABLE_AUTO_LINT_FIX=true (Standard) lässt core/verifier/lint.py._lint_python() vor dem
# eigentlichen Check-Lauf `ruff check --fix` (NUR sichere Autofixes, kein `--unsafe-fixes`)
# ausführen - unsortierte/ungenutzte Importe, veraltete Typannotationen u.Ä. verschwinden so
# automatisch, ohne einen Agenten-Auftrag zu brauchen, analog zu `black`/`prettier` im
# Pre-Commit-Hook eines echten Teams.
ENABLE_AUTO_LINT_FIX: bool = os.getenv("ENABLE_AUTO_LINT_FIX", "true").lower() in ("true", "1", "yes")

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

# ──────────────────────────────────────────
# Hartes Lauf-Budget (echter Abbruch statt nur Reporting)
# ──────────────────────────────────────────
# core/quota_estimator.py zeigt den Tokenverbrauch nur an – ohne Obergrenze kann ein
# einzelner Lauf (z.B. durch mehrere Verifikations-Fixversuche mit dem kostenpflichtigen
# ORCHESTRATOR_MODEL/Heavy-Agenten) unbegrenzt weiterlaufen. MAX_RUN_TOKENS=0 (Standard)
# lässt bestehende Läufe unangetastet; setze z.B. MAX_RUN_TOKENS=300000 in der .env, um
# agents/orchestrator.py nach Erreichen dieses Werts die verbleibenden Fachbereichs-Phasen,
# Verifikations-Fixversuche sowie Retrospektive/Selbstoptimierung übersprungen ausliefern
# zu lassen (die bis dahin erarbeiteten Ergebnisse werden trotzdem synthetisiert).
MAX_RUN_TOKENS: int = int(os.getenv("MAX_RUN_TOKENS", "0"))

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
        ".env.example,README.md,ZWISCHENSTAND_KI_TEAM_PROJEKT.md,.gitignore,ARCHITECTURE.md,CHANGELOG.md,CLAUDE.md,.claudeignore",
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
