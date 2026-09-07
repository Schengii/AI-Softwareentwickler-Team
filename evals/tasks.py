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
    # KI-Team-Analyse 07.09.2026, Punkt 4: 'mobile', 'i18n', 'data_engineer' und
    # 'image_generator' hatten trotz geschärfter Planer-Beschreibungen (siehe
    # core/task_manager.py.AVAILABLE_AGENTS) weiterhin KEINE einzige Referenzaufgabe, die sie
    # fachlich wirklich braucht - derselbe Root Cause wie beim faq_rag_chatbot-Fix oben
    # (ml/prompt_engineer), hier für die 4 verbleibenden, laut team_lessons.jsonl nie gewählten
    # Rollen (accessibility ist hier zusätzlich mit abgedeckt, da JEDES HTML-Frontend-Projekt
    # laut dessen Trigger-Beschreibung relevant ist).
    "multilang_expense_app": BenchmarkTask(
        slug="multilang_expense_app",
        name="Mehrsprachige Cross-Platform Ausgaben-App (Mobile/i18n)",
        category="mobile",
        prompt=(
            "Erstelle eine Cross-Platform-Mobile-App 'expense_tracker' (Flutter oder React "
            "Native, offline-first mit lokaler Speicherung) zum Erfassen von Ausgaben in "
            "mehreren Währungen. Die App muss vollständig internationalisiert sein (mindestens "
            "Deutsch und Englisch umschaltbar, locale-abhängige Datums-/Währungsformate) und "
            "barrierefrei bedienbar sein (Screenreader-Labels, ausreichende Kontraste). Liefere "
            "eine README mit Setup-Anleitung und Tests für die Kernlogik (Ausgaben summieren, "
            "Währungsumrechnung)."
        ),
        expected_project_name="expense_tracker",
        expected_files=["README.md"],
        description=(
            "Prüft, ob 'mobile' (Cross-Platform-App statt reflexhaft 'frontend'), 'i18n' "
            "(echte Mehrsprachigkeit/locale-Formate) und 'accessibility' bei einer Aufgabe, "
            "die alle drei fachlich echt braucht, tatsächlich vom Planer ausgewählt werden."
        ),
    ),
    "streaming_cost_pipeline": BenchmarkTask(
        slug="streaming_cost_pipeline",
        name="Event-Streaming-Pipeline mit Kosten- & Lastanalyse (Data Engineering)",
        category="data",
        prompt=(
            "Erstelle einen Python-Service 'stream_pipeline', der Events über eine Message-"
            "Queue (Kafka oder RabbitMQ) aus mehreren simulierten Quellen konsumiert, sie über "
            "eine Redis-Caching-Schicht aggregiert und die Ergebnisse in einer REST-API "
            "bereitstellt. Recherchiere vorab die aktuell empfohlenen, stabilen Paketversionen "
            "für den gewählten Message-Broker-Client. Vergleiche außerdem die monatlichen "
            "Hosting-Kosten von mindestens zwei Cloud-Anbietern für diesen Workload und "
            "dokumentiere sie. Liefere requirements.txt, pytest-Tests (Broker gemockt) und "
            "einen Lasttest für die REST-API."
        ),
        expected_project_name="stream_pipeline",
        expected_files=["requirements.txt"],
        description=(
            "Prüft, ob 'data_engineer' (Event-Streaming/Caching-Pipeline statt reflexhaft "
            "'backend'), 'web_research' (aktuelle Paketversionen), 'finops' (Cloud-Kosten-"
            "vergleich) und 'performance' (Lasttest) bei einer Aufgabe, die alle vier fachlich "
            "echt braucht, tatsächlich vom Planer ausgewählt werden."
        ),
    ),
    "branded_landing_page": BenchmarkTask(
        slug="branded_landing_page",
        name="SaaS-Landingpage mit eigenem Branding (Copywriting/Grafik)",
        category="fullstack",
        prompt=(
            "Erstelle eine öffentliche Marketing-Landingpage 'brandflow_landing' für ein neues "
            "SaaS-Produkt namens 'BrandFlow' OHNE bestehendes Branding. Die Seite braucht ein "
            "eigenes Logo/Icon-Set, überzeugende deutsche Marketingtexte (Hero-Headline, "
            "Feature-Beschreibungen, FAQ, Call-to-Action-Buttons) statt Lorem-Ipsum/technischer "
            "Platzhalter, und modernes responsives HTML/CSS."
        ),
        expected_project_name="brandflow_landing",
        expected_files=["index.html"],
        description=(
            "Prüft, ob 'image_generator' (Logo/Icons ohne bestehendes Branding) und "
            "'copywriter' (echte Marketingtexte statt Platzhalter) bei einer Aufgabe, die "
            "beide fachlich echt braucht, tatsächlich vom Planer ausgewählt werden."
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
