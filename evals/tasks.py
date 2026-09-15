"""
evals/tasks.py – Kanonische Benchmark- & Regressions-Aufgaben für das KI-Softwareentwickler-Team

Definiert standardisierte Referenzaufgaben unterschiedlicher Komplexität und Technologiestacks,
um Qualität, Token-Effizienz, Testabdeckung und Verifikations-Erfolgsquoten über verschiedene
Versionen und Modell-Konfigurationen hinweg reproduzierbar vergleichen zu können.
"""

from dataclasses import dataclass, field


@dataclass
class BenchmarkTask:
    """Eine kanonische Benchmark-Aufgabe."""
    slug: str
    name: str
    category: str  # "micro", "api", "cli", "data", "fullstack"
    prompt: str
    expected_project_name: str
    expected_files: list[str] = field(default_factory=list)
    description: str = ""
    # Aus welchen echten, fehlgeschlagenen workspace/-Läufen die Aufgabe abgeleitet ist - die
    # Regressions-Suite misst genau die Fehlerklassen, an denen das Team real gescheitert ist.
    derived_from: tuple[str, ...] = ()


# Standard-Katalog der Referenzaufgaben
BENCHMARK_TASKS: dict[str, BenchmarkTask] = {
    "fastapi_ping": BenchmarkTask(
        slug="fastapi_ping",
        name="FastAPI Ping Service (Micro-Task)",
        category="micro",
        prompt="Erstelle eine minimale FastAPI-App im Ordner 'ping_service' mit einem GET /ping Endpunkt (JSON-Antwort {'status': 'pong'}), requirements.txt und vollständigen pytest-Tests.",
        expected_project_name="ping_service",
        expected_files=["main.py", "requirements.txt", "test_main.py"],
        description="Prüft die schlanke Ausführung bei Micro-Tasks ohne unnötigen Teamleiter-Overhead.",
    ),
    "cli_calculator": BenchmarkTask(
        slug="cli_calculator",
        name="CLI Calculator (CLI Tool)",
        category="cli",
        prompt="Erstelle ein vollständiges Python-CLI-Tool 'calc_cli' mit argparse für Grundrechenarten (+, -, *, /), sicherer Division-durch-0-Fehlerbehandlung, README und unittest-Tests.",
        expected_project_name="calc_cli",
        expected_files=["calculator.py", "test_calculator.py", "README.md"],
        description="Prüft CLI-Parsing, Fehlerbehandlung und saubere Modul-Architektur.",
    ),
    "notes_api_sqlite": BenchmarkTask(
        slug="notes_api_sqlite",
        name="Notizen REST-API mit SQLite (Backend API)",
        category="api",
        prompt="Erstelle eine modulare Notizen-REST-API mit FastAPI und SQLite in 'notes_api' mit CRUD-Endpunkten (GET/POST/DELETE /notes, GET /notes/{id}), Pydantic-Schemas, requirements.txt und pytest-Tests.",
        expected_project_name="notes_api",
        expected_files=["main.py", "models.py", "requirements.txt", "test_notes.py"],
        description="Prüft Datenbank-Anbindung, Pydantic-Validierung und REST-Routen.",
    ),
    "csv_data_pipeline": BenchmarkTask(
        slug="csv_data_pipeline",
        name="CSV Data Cleaner & Aggregator (Data Pipeline)",
        category="data",
        prompt="Erstelle eine Python-Datenverarbeitungs-Pipeline im Ordner 'data_cleaner', die CSV-Dateien einliest, ungültige Zeilen filtert, Kennzahlen aggregiert, Ausreißer markiert und pytest-Tests enthält.",
        expected_project_name="data_cleaner",
        expected_files=["cleaner.py", "requirements.txt", "test_cleaner.py"],
        description="Prüft Datenverarbeitungs-Logik, Parsing und statistische Berechnungen.",
    ),
    # Team-Optimierung (Fortsetzung der Analyse 2026-09-06): core/optimization_advisor.py
    # erkennt seit MIN_TOTAL_RUNS_FOR_UNUSED_CHECK=20 Läufen `ml`/`prompt_engineer` (u.a.) als
    # nie vom Planer gewählt (unused_agent). Root Cause: keine der bisherigen 5 Referenz-
    # aufgaben verlangt RAG/Embeddings/LLM-Prompting - der Planer hatte für diese Rollen also
    # nie eine passende Aufgabe. Diese Aufgabe braucht beide Rollen fachlich echt (nicht nur
    # per Stichwort erzwungen), damit ein Benchmark-Lauf misst, ob die geschärften Trigger in
    # core/task_manager.py.AVAILABLE_AGENTS tatsächlich zu ihrer Auswahl führen.
    "faq_rag_chatbot": BenchmarkTask(
        slug="faq_rag_chatbot",
        name="FAQ-Chatbot mit RAG (KI/ML)",
        category="ai",
        prompt=(
            "Erstelle einen Python-Service 'faq_chatbot', der eine kleine FAQ-Wissensbasis "
            "(mitgelieferte JSON/Text-Dateien) per Embeddings in einer lokalen Vektordatenbank "
            "indexiert und über einen REST-Endpunkt POST /ask Fragen dazu per Retrieval-"
            "Augmented Generation beantwortet. Ergänze Guardrails gegen Prompt-Injection in "
            "nutzergesteuerten Fragen, eine requirements.txt und pytest-Tests, die die "
            "Retrieval-Logik OHNE echten externen LLM-Aufruf testen (gemockt)."
        ),
        expected_project_name="faq_chatbot",
        expected_files=["main.py", "requirements.txt", "test_main.py"],
        description=(
            "Prüft, ob 'ml' (RAG/Embeddings-Pipeline) und 'prompt_engineer' (Guardrails gegen "
            "Prompt-Injection) bei einer Aufgabe, die beide fachlich echt braucht, tatsächlich "
            "vom Planer ausgewählt werden - beide galten laut core/optimization_advisor.py als "
            "unused_agent, da keine bisherige Referenzaufgabe LLM-/RAG-Funktionalität verlangte."
        ),
    ),
    "html_dashboard_ui": BenchmarkTask(
        slug="html_dashboard_ui",
        name="Modernes Dark-Mode Dashboard (Frontend/Fullstack)",
        category="fullstack",
        prompt="Erstelle ein modernes Single-Page Web-Dashboard in 'analytics_ui' mit Vanilla HTML, modernem CSS (Dark Mode, Responsive Grid) und Vanilla JS mit dynamischer Diagrammanzeige und interaktiven Filtern.",
        expected_project_name="analytics_ui",
        expected_files=["index.html", "styles.css", "app.js"],
        description="Prüft UI/UX-Gestaltung, semantisches HTML und modernes Vanilla CSS/JS.",
    ),
}

# ── Regressions-Suite aus realen Fehlschlägen ───────────────────────────────────────────────
# Die obigen Aufgaben sind deutlich einfacher als die echten Projekte, an denen das Team
# scheiterte (35% nicht verifiziert). Diese Aufgaben bilden die dort beobachteten Fehlerklassen
# nach, damit jede Framework-Änderung an ihnen gemessen wird (evals/gate.py).
REGRESSION_TASKS: dict[str, BenchmarkTask] = {
    "auth_task_api": BenchmarkTask(
        slug="auth_task_api",
        name="Aufgaben-API mit JWT-Auth und async SQLAlchemy (Regression)",
        category="api",
        prompt=(
            "Erstelle im Ordner 'auth_task_api' eine FastAPI-Anwendung (app/main.py) mit async SQLAlchemy "
            "und SQLite: Registrierung und Login per OAuth2PasswordRequestForm mit JWT-Token, geschützte "
            "CRUD-Endpunkte für Aufgaben je Nutzer, Konfiguration über pydantic-settings, requirements.txt "
            "und eine pytest-Testsuite mit async Tests für Login und Aufgaben-Endpunkte."
        ),
        expected_project_name="auth_task_api",
        expected_files=["app/main.py", "requirements.txt", "pytest.ini"],
        description="Deckt jwt/PyJWT, greenlet, python-multipart, pytest-asyncio und Paketstruktur ab.",
        derived_from=("eventstream_zero", "nexusforge", "logipulse", "fastapi-task-mgmt"),
    ),
    "realtime_log_dashboard": BenchmarkTask(
        slug="realtime_log_dashboard",
        name="Log-Monitoring mit WebSocket-Dashboard (Regression)",
        category="fullstack",
        prompt=(
            "Erstelle im Ordner 'realtime_log_dashboard' eine FastAPI-Anwendung (app/main.py), die Log-Events "
            "per POST /api/logs annimmt, in SQLite speichert, per WebSocket /ws/logs live an ein statisches "
            "HTML-Dashboard (static/index.html mit nativem Browser-WebSocket, ohne Socket.IO) streamt und "
            "Kennzahlen unter GET /api/stats liefert. Mit requirements.txt und pytest-Tests inkl. WebSocket-Test."
        ),
        expected_project_name="realtime_log_dashboard",
        expected_files=["app/main.py", "static/index.html", "requirements.txt"],
        description="Deckt WebSocket-Handshake, Backend-verursachte UI-Fehler und Frontend-Auslieferung ab.",
        derived_from=("syncwave", "devpulse", "nexus_resilience_gateway"),
    ),
    "resilient_gateway": BenchmarkTask(
        slug="resilient_gateway",
        name="API-Gateway mit Circuit Breaker und Rate-Limiting (Regression)",
        category="api",
        prompt=(
            "Erstelle im Ordner 'resilient_gateway' ein FastAPI-API-Gateway (app/main.py), das Anfragen an "
            "konfigurierbare Upstream-Dienste weiterleitet, pro Upstream einen Circuit Breaker und ein "
            "Token-Bucket-Rate-Limit anwendet und den Zustand unter GET /api/health ausgibt. Upstreams in "
            "Tests mit httpx.MockTransport simulieren. Mit requirements.txt und pytest-Tests."
        ),
        expected_project_name="resilient_gateway",
        expected_files=["app/main.py", "requirements.txt"],
        description="Deckt parallele Modul-Integration, Re-Exporte und Vertragskonsistenz ab.",
        derived_from=("aethermesh", "nexus_resilience_gateway", "chronospulse"),
    ),
}
BENCHMARK_TASKS.update(REGRESSION_TASKS)


def list_regression_tasks() -> list[BenchmarkTask]:
    """Die aus realen Fehlschlägen abgeleiteten Aufgaben (Standard-Suite für das Eval-Gate)."""
    return list(REGRESSION_TASKS.values())


def get_task(slug: str) -> BenchmarkTask:
    """Liefert eine Benchmark-Aufgabe nach Slug oder wirft KeyError."""
    if slug not in BENCHMARK_TASKS:
        available = ", ".join(BENCHMARK_TASKS.keys())
        raise KeyError(f"Unbekannter Benchmark-Task '{slug}'. Verfügbar: {available}")
    return BENCHMARK_TASKS[slug]


def list_tasks() -> list[BenchmarkTask]:
    """Liefert alle definierten Benchmark-Tasks."""
    return list(BENCHMARK_TASKS.values())
