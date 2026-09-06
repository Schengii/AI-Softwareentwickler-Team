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


def get_task(slug: str) -> BenchmarkTask:
    """Liefert eine Benchmark-Aufgabe nach Slug oder wirft KeyError."""
    if slug not in BENCHMARK_TASKS:
        available = ", ".join(BENCHMARK_TASKS.keys())
        raise KeyError(f"Unbekannter Benchmark-Task '{slug}'. Verfügbar: {available}")
    return BENCHMARK_TASKS[slug]


def list_tasks() -> list[BenchmarkTask]:
    """Liefert alle definierten Benchmark-Tasks."""
    return list(BENCHMARK_TASKS.values())
