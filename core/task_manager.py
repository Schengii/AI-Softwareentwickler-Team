"""
core/task_manager.py – Analysiert Nutzeraufgaben und zerlegt sie in Teilaufgaben (30 Spezialisten)
"""

import json
import re
import uuid

from core.llm_factory import LLMFactory
from core.message_bus import AgentTask

# ──────────────────────────────────────────────────────────
# Alle verfügbaren Agenten (30 Spezialisten)
# ──────────────────────────────────────────────────────────

AVAILABLE_AGENTS = {
    # ── Phase 1: Führung, Planung & Recherche ─────────────
    "team_lead": {
        "name": "Teamleiter (Engineering Manager)",
        "phase": 1,
        "description": "Definiert Projektziele, DoD, Trade-Off-Entscheidungen und steuert den Team-Fokus.",
    },
    "product_owner": {
        "name": "Product Owner",
        "phase": 1,
        "description": "Definiert Produktvision, MVP-Scope (MoSCoW), Release-Roadmap und User Journeys.",
    },
    "business_analyst": {
        "name": "Business Analyst",
        "phase": 1,
        "description": "Analysiert Anforderungen, erstellt User Stories und Akzeptanzkriterien (Given/When/Then).",
    },
    "web_research": {
        "name": "Web-Recherche Specialist",
        "phase": 1,
        "description": "Recherchiert aktuelle Framework-Dokumentationen, Best Practices, Open-Source-Pakete und Markttrends.",
    },

    # ── Phase 2: Architektur & FinOps ─────────────────────
    "architect": {
        "name": "Software-Architekt",
        "phase": 2,
        "description": "Entwirft Systemarchitektur, API-Contracts, Komponenten-Blueprints und ADRs.",
    },
    "finops": {
        "name": "Cost & FinOps Engineer",
        "phase": 2,
        "description": "Kalkuliert Cloud-Kosten (AWS/GCP/Hetzner), TCO, Serverless vs. VM und AI-Token-Budgets.",
    },

    # ── Phase 2: Vorab-Design, UI/UX & Media ──────────────
    "ui_ux": {
        "name": "UI/UX Designer",
        "phase": 2,
        "description": "Wireframes, Design-Systeme, Farbpaletten und Design-Tokens.",
    },
    "image_generator": {
        "name": "Bild- & Grafik-Designer",
        "phase": 2,
        "description": "Erstellt SVG-Grafiken/Logos und optimierte Bild-Prompts für Imagen 3 / Midjourney.",
    },
    "copywriter": {
        "name": "Copywriter & Content Specialist",
        "phase": 2,
        "description": "Schreibt Landingpage-Texte, UI-Microcopy (Buttons, Errors), SEO-Texte und FAQs.",
    },

    # ── Phase 3: Kern-Entwicklung ─────────────────────────
    "frontend": {
        "name": "Frontend-Entwickler",
        "phase": 3,
        "description": "Implementiert React, Vue, Next.js, HTML/CSS und interaktive Web-UIs.",
    },
    "backend": {
        "name": "Backend-Entwickler",
        "phase": 3,
        "description": "Entwickelt REST/FastAPI/Node Server-Logik, Authentifizierung und APIs.",
    },
    "database": {
        "name": "Datenbank-Entwickler",
        "phase": 3,
        "description": "Entwirft SQL/NoSQL Datenmodelle, ORM-Schemas, Indizes und Migrationen.",
    },
    "api_integration": {
        "name": "API & Integration Specialist",
        "phase": 3,
        "description": "OpenAPI 3.1 Specs, GraphQL, Webhooks mit HMAC-Sicherheit, Stripe, OAuth2.",
    },
    "data_engineer": {
        "name": "Data Engineer",
        "phase": 3,
        "description": "Event-Streaming (Kafka/RabbitMQ), Redis Caching-Layer und ETL-Pipelines.",
    },
    "mobile": {
        "name": "Mobile-Entwickler",
        "phase": 3,
        "description": "Entwickelt Cross-Platform Apps mit Flutter, React Native, iOS & Android.",
    },
    "ml": {
        "name": "KI/ML-Entwickler",
        "phase": 3,
        "description": "LLM-APIs, RAG-Systeme, Embeddings, Vector Stores und ML-Pipelines.",
    },
    "prompt_engineer": {
        "name": "Prompt Engineer & AI Architect",
        "phase": 3,
        "description": "System-Prompts für LLM-Apps, Few-Shot-Vorlagen, Guardrails und RAG-Prompting.",
    },
    "performance": {
        "name": "Performance-Ingenieur",
        "phase": 3,
        "description": "Load-Testing, Profiling, Query-Optimierung und Latenz-Minimierung.",
    },

    # ── Phase 4: Content, Doku & Barrierefreiheit ─────────
    "accessibility": {
        "name": "Accessibility & a11y Specialist",
        "phase": 4,
        "description": "WCAG 2.2 AA/AAA Barrierefreiheit, ARIA-Attribute, Tastaturnavigation, Screenreader.",
    },
    "i18n": {
        "name": "Internationalisierungs-Spezialist",
        "phase": 4,
        "description": "Mehrsprachigkeit (i18n/l10n), RTL-Unterstützung und Formatierungen.",
    },
    "documentation": {
        "name": "Dokumentant",
        "phase": 4,
        "description": "API-Dokumentation, Inline-Kommentare und Architekturguides.",
    },
    "readme": {
        "name": "README & Tech-Writer",
        "phase": 4,
        "description": "Erstellt professionelle README.md, Quickstart-Guides und Projektübersichten.",
    },

    # ── Phase 5: Infrastruktur & Qualität ─────────────────
    "devops": {
        "name": "DevOps-Ingenieur",
        "phase": 5,
        "description": "Dockerfile, docker-compose, CI/CD GitHub Actions Pipelines, K8s.",
    },
    "tester": {
        "name": "QA-Tester",
        "phase": 5,
        "description": "Unit-Tests (pytest), Integrationstests und E2E-Testpläne.",
    },
    "security": {
        "name": "Sicherheits-Analyst",
        "phase": 5,
        "description": "OWASP Top 10, Auth-Audits, Input-Sanitization, Security-Headers.",
    },
    "resilience_guard": {
        "name": "Resilience-Guard (QA & Fault-Tolerance)",
        "phase": 5,
        "description": "Circuit Breaker, Retries mit Backoff/Jitter, Ausfalltoleranz, Graceful Degradation & Chaos Tests.",
    },

    # ── Phase 6: Review, Refactoring, Compliance & Hygiene ─
    "code_reviewer": {
        "name": "Code-Reviewer",
        "phase": 6,
        "description": "Qualitätskontrolle, Konsistenzprüfung, Code-Scoring und Bug-Detektion.",
    },
    "refactoring": {
        "name": "Refactoring Specialist",
        "phase": 6,
        "description": "Beseitigt Code Smells, refaktoriert Module und sichert strikte Typsicherheit.",
    },
    "compliance": {
        "name": "Legal & Compliance Specialist",
        "phase": 6,
        "description": "DSGVO/GDPR-Audits, Lizenzprüfung (GPL vs MIT), WCAG 2.1 Barrierefreiheit.",
    },
    "project_cleaner": {
        "name": "Projekt-Hygiene & Struktur-Wächter",
        "phase": 6,
        "description": "Bereinigt alte/tote Dateien, verhindert Projekt-Bloat und optimiert Ordnerstrukturen.",
    },

    # ── Phase 6: Ausbildung, Retrospektive & Evolution ─────
    "agent_trainer": {
        "name": "Ausbilder & Agent-Optimizer",
        "phase": 6,
        "description": "Optimiert System-Prompts, analysiert Fehler der Agenten und bildet neue Rollen aus.",
    },
    "retrospective": {
        "name": "Retrospektive & Lessons Learned Agent",
        "phase": 6,
        "description": "Erstellt die Abschluss-Retrospektive (Was lief gut/schlecht, Lessons Learned).",
    },
    "github": {
        "name": "GitHub-Agent",
        "phase": 5,
        "description": "Generiert Commit-Messages und führt automatische Git-Pushes durch.",
    },
}

# Realer Fund aus einem echten End-to-End-Testlauf: diese Agenten werden laut den
# DECOMPOSE_SYSTEM_PROMPT-Regeln unten NUR bei echter Komplexität eingeplant (architect/
# security/compliance sind dort explizit "NICHT optional, sobald..."-Fälle, die übrigen
# signalisieren von sich aus einen größeren Aufgabenzuschnitt) - taucht auch nur EINER davon
# im Plan auf, ist die Aufgabe per Definition NICHT trivial.
_COMPLEXITY_SIGNAL_AGENT_IDS = {
    "architect", "security", "compliance", "finops", "performance",
    "data_engineer", "ml", "mobile", "product_owner", "business_analyst", "web_research",
}

# Ab dieser Gesamtzahl an eingeplanten Spezialisten gilt eine Aufgabe nicht mehr als "klein"
# genug, um die Teamleiter-Koordination zu überspringen - selbst wenn kein einzelner Agent
# ein Komplexitäts-Signal ist, deutet eine breite Aufgabenverteilung auf echten
# Abstimmungsbedarf hin.
_MICRO_TASK_MAX_AGENTS = 4


def is_micro_task(agent_tasks: list["AgentTask"]) -> bool:
    """
    Rein deterministische Klassifikation aus dem BEREITS erstellten Aufgabenplan - KEIN
    zusätzlicher LLM-Aufruf, keine neue Schätzung. Nutzt genau die Agenten-Auswahl, die
    decompose() (siehe DECOMPOSE_SYSTEM_PROMPT unten) ohnehin schon für die Zwecke von
    "welche Spezialisten sind wirklich nötig" trifft, nur ein zweites Mal ausgewertet für
    "wie viel Teamleiter-Koordination braucht dieser Plan wirklich".
    """
    if len(agent_tasks) > _MICRO_TASK_MAX_AGENTS:
        return False
    return not any(t.agent_id in _COMPLEXITY_SIGNAL_AGENT_IDS for t in agent_tasks)


DECOMPOSE_SYSTEM_PROMPT = """Du bist ein erfahrener Principal Software-Architekt und Engineering Lead.
Analysiere die Aufgabe und wähle NUR die wirklich notwendigen Spezialisten aus, um maximale Token-Effizienz zu gewährleisten.

Antworte NUR mit einem gültigen JSON-Objekt. Keine Erklärungen davor oder danach.

Das JSON-Format ist exakt wie folgt:
{
  "needs_clarification": false,
  "clarifying_questions": [],
  "task_summary": "3-8 Wörter, technischer Imperativ im Perfekt (z.B. 'FastAPI Health-Check-Endpoint implementiert', 'Taschenrechner-GUI mit Core/GUI-Trennung erstellt'). NIEMALS die Nutzeranfrage wörtlich wiederholen, zitieren oder paraphrasieren, auch nicht in Teilen - beschreibe WAS entstehen wird, nicht WAS der Nutzer geschrieben hat. Dieser Text erscheint u.a. als Git-Commit-Message.",
  "project_slug": "kurzer_projekt_ordnername_ohne_sonderzeichen",
  "required_agents": [
    {
      "agent_id": "<agent_id aus der Liste>",
      "task": "Präzise, token-effiziente Aufgabenbeschreibung für diesen Agenten"
    }
  ]
}

Rückfrage statt Raten (wie ein erfahrener Senior-Entwickler): Setze "needs_clarification"
auf true und liste 1-3 knappe, konkrete Fragen in "clarifying_questions" (required_agents
dann leer), wenn die Aufgabe SO unklar ist, dass unterschiedliche vertretbare Interpretationen
zu grundverschieden Ergebnissen führen würden, oder eine für die Umsetzung ZWINGENDE Angabe
komplett fehlt (z.B. welches Zielsystem, welche Datenquelle, welcher Kernzweck der Anwendung).
NICHT für gewöhnliche Unterspezifikation nutzen, die ein erfahrener Entwickler sinnvoll selbst
entscheiden würde (z.B. Styling-Details, exakte Bibliotheksversion) - im Zweifel lieber eine
vernünftige Annahme treffen und im task_summary kurz erwähnen, statt nachzufragen.

Verfügbare Agenten-IDs:
team_lead, product_owner, business_analyst, web_research,
architect, finops,
frontend, backend, database, api_integration, data_engineer, mobile, ml, prompt_engineer, performance,
image_generator, copywriter, ui_ux, accessibility, i18n, documentation, devops, tester, security, resilience_guard,
code_reviewer, refactoring, compliance, project_cleaner, agent_trainer, readme, github

Wichtige Regeln:
- Wähle NUR die zwingend erforderlichen Agenten aus (Token-Sparsamkeit)
- Halte die Aufgabenbeschreibungen klar und fokussiert
- code_reviewer bei Code-Generierung einschließen
- tester einbeziehen, wenn echte Programmlogik entsteht (Funktionen/Klassen mit Verhalten,
  nicht nur Konfiguration/Text) - ausgelieferter Code ohne jeden Test ist nicht Ziel dieses Teams
- security einbeziehen, sobald Authentifizierung/Autorisierung, Nutzer-/Personendaten,
  Zahlungsdaten, Datei-Uploads oder ein nach außen erreichbarer Netzwerk-Endpunkt entstehen -
  das ist NICHT optional, sondern genauso verpflichtend wie code_reviewer bei Code-Generierung
- compliance einbeziehen, sobald personenbezogene Daten (DSGVO-Relevanz), neue
  Drittanbieter-Abhängigkeiten mit unklarer/restriktiver Lizenz oder regulierte Bereiche
  (z.B. Finanzen, Gesundheit) betroffen sind - ebenfalls NICHT optional
- architect einbeziehen, sobald eine echte Technologie-/Architektur-Entscheidung mit
  mehreren vertretbaren Alternativen zu treffen ist (z.B. Wahl der Datenpersistenz,
  Monolith vs. Microservices, REST vs. GraphQL, Wahl des Datenbanksystems, Auth-Strategie) -
  NICHT optional, auch wenn die Aufgabe sonst klein wirkt; ohne echte Alternative (z.B. reine
  Konfigurationsänderung, triviale Erweiterung um einen weiteren Endpunkt nach bereits
  etabliertem Muster) bleibt architect dagegen weiterhin weggelassen
- project_cleaner einbeziehen, wenn Verzeichnisstrukturen aufgeräumt oder schlank gehalten werden sollen
- Wenn die Aufgabe ein bestehendes Projekt (oder einen Pfad wie 'workspace/<name>') nennt oder referenziert,
  nutze EXAKT diesen bestehenden 'project_slug'. Erfinde NIEMALS abgeleitete Slugs wie '<name>_repair',
  '<name>_fix' oder '<name>_patch'.
"""


class TaskManager:
    """Analysiert und zerlegt Nutzeraufgaben in parallelisierbare Teilaufgaben."""

    def __init__(self, model_name: str = "gemini-3.8-flash"):
        self._llm = LLMFactory.create_for_model(model_name)

    async def decompose(
        self,
        user_request: str,
        conversation_context: str | None = None,
        existing_projects: list[str] | None = None,
    ) -> tuple[str, str, list[AgentTask]]:
        agents_description = "\n".join([
            f"- {agent_id} [Phase {info['phase']}]: {info['description']}"
            for agent_id, info in AVAILABLE_AGENTS.items()
            if agent_id not in ("retrospective", "agent_trainer")
        ])

        context_section = ""
        if conversation_context:
            context_section = f"\n\nVorheriger Kontext (gekürzt):\n{conversation_context[:1000]}"

        existing_projects_section = ""
        if existing_projects:
            existing_projects_section = (
                "\n\nBEREITS EXISTIERENDE PROJEKTE IM WORKSPACE:\n"
                + ", ".join(sorted(existing_projects))
                + "\nWICHTIG: Bezieht sich die Nutzeranfrage auf eines dieser Projekte, verwende EXAKT dessen "
                "bestehenden 'project_slug' (kein Suffix wie '_repair' oder '_fix')!"
            )

        prompt = f"""Analysiere folgende Nutzeranfrage und erstelle einen effizienten Aufgabenplan:

NUTZERANFRAGE:
{user_request}
{context_section}
{existing_projects_section}

VERFÜGBARE AGENTEN:
{agents_description}

Erstelle jetzt das JSON mit den Teilaufgaben."""

        try:
            raw_json = await self._llm.generate_json(prompt, DECOMPOSE_SYSTEM_PROMPT)
        except Exception as e:
            # Wie in ResultAggregator.synthesize(): nicht crashen, sondern einen klaren,
            # nutzerverständlichen Grund liefern statt eines rohen Stacktraces. Orchestrator.
            # process() behandelt eine leere agent_tasks-Liste bereits als regulären Fall.
            return f"⚠️ Aufgabenanalyse fehlgeschlagen (alle konfigurierten Modelle/Provider aktuell nicht erreichbar: {e})", "project", []

        plan = self._parse_plan(raw_json)

        # Rückfrage statt Raten: wie ein erfahrener Senior-Entwickler nachfragen, statt bei
        # einer grundlegend unklaren Anfrage einfach die naheliegendste Interpretation zu
        # bauen (real beobachtet: vage Prompts wie "Ich möchte, dass ihr das Projekt weiter
        # verbessert" führten zu frei erfundenen, thematisch beliebigen Demo-Projekten statt
        # einer Rückfrage). agent_tasks bleibt bewusst leer - dieselbe, bereits vorhandene
        # Behandlung wie bei einem Provider-Totalausfall (siehe Orchestrator.process()),
        # nur mit "❓" statt "⚠️" als Präfix, damit der Aufrufer zwischen "echter Fehler"
        # und "brauche eine Antwort vom Menschen" unterscheiden kann.
        if plan.get("needs_clarification") and plan.get("clarifying_questions"):
            questions = "\n".join(f"{i}. {q}" for i, q in enumerate(plan["clarifying_questions"], 1))
            return (
                f"❓ Bevor ich das Team loslasse, brauche ich noch eine Präzisierung:\n\n{questions}",
                "project", [],
            )

        task_summary = plan.get("task_summary", "Aufgabe wird bearbeitet...")
        project_slug = plan.get("project_slug", "project")
        required_agents = plan.get("required_agents", [])

        agent_tasks = []
        for agent_info in required_agents:
            agent_id = agent_info.get("agent_id", "")
            if agent_id not in AVAILABLE_AGENTS:
                continue

            agent_tasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                agent_id=agent_id,
                description=agent_info.get("task", ""),
                context=user_request[:1500],
            ))

        return task_summary, project_slug, agent_tasks

    def _parse_plan(self, raw_json: str) -> dict:
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_json)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return {"task_summary": "Aufgabe analysiert", "project_slug": "project", "required_agents": []}
