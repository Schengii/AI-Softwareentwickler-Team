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
#
# Anthropic bietet – anders als Gemini – KEIN dauerhaftes Gratis-Kontingent (nur ein
# einmaliges kleines Startguthaben für neue Accounts). Solange kein ANTHROPIC_API_KEY
# gesetzt ist, springt core/llm_factory.py bei allen HEAVY-Aufgaben deshalb zunächst auf
# GROQ_HEAVY_MODEL – ein starkes, aber tatsächlich kostenloses Open-Weight-Modell mit
# großzügigem Rate-Limit – und erst danach auf die Gemini-Standard-Stufe aus, statt
# sofort auf das schwächste verfügbare Modell abzurutschen.
GEMINI_LITE_MODEL: str = os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite")
GEMINI_STANDARD_MODEL: str = os.getenv("GEMINI_STANDARD_MODEL", "gemini-3.6-flash")
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
MIN_TEST_COVERAGE: float = float(os.getenv("MIN_TEST_COVERAGE", "0"))

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
MAX_REVIEW_ITERATIONS: int = int(os.getenv("MAX_REVIEW_ITERATIONS", "1"))

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
