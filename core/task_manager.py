"""
core/task_manager.py – Analysiert Nutzeraufgaben und zerlegt sie in Teilaufgaben

Der Orchestrator ruft dieses Modul auf, um zu entscheiden, welche Agenten
für eine gegebene Aufgabe benötigt werden und was genau ihre Teilaufgabe ist.
"""

import json
import re
from typing import Optional
from core.llm_factory import LLMFactory
from core.message_bus import AgentTask
import uuid


# ──────────────────────────────────────────────────────────
# Alle verfügbaren Agenten (23 Spezialisten)
# ──────────────────────────────────────────────────────────

AVAILABLE_AGENTS = {
    # ── Phase 1: Planung & Produkt (sequentiell) ───────────
    "business_analyst": {
        "name": "Business Analyst",
        "phase": 1,
        "description": (
            "Analysiert und klärt Anforderungen, erstellt User Stories und Akzeptanzkriterien. "
            "EINSETZEN wenn: Anforderungen komplex/mehrdeutig sind, Business-Kontext wichtig ist."
        ),
    },
    "product_owner": {
        "name": "Product Owner",
        "phase": 1,
        "description": (
            "Definiert Produktvision, MVP-Scope (MoSCoW), Release-Roadmap und User Journeys. "
            "EINSETZEN wenn: Ein neues Produkt/Feature von Grund auf geplant und gescopt werden soll."
        ),
    },

    # ── Phase 2: Architektur & FinOps (sequentiell) ───────
    "architect": {
        "name": "Software-Architekt",
        "phase": 2,
        "description": (
            "Entwirft die Gesamtarchitektur BEVOR andere Agenten implementieren. "
            "Erstellt Systemdiagramme, API-Contracts und Technologie-Entscheidungen. "
            "EINSETZEN wenn: mehrere Komponenten zusammenarbeiten, Technologiewahl unklar ist."
        ),
    },
    "finops": {
        "name": "Cost & FinOps Engineer",
        "phase": 2,
        "description": (
            "Kalkuliert Cloud- & Infrastrukturkosten (AWS, GCP, Hetzner, Serverless, AI Tokens). "
            "EINSETZEN wenn: Budget, Cloud-Kosten, TCO oder Skalierungskosten relevant sind."
        ),
    },

    # ── Phase 3: Implementierungs-Agenten (parallel) ───────
    "ui_ux": {
        "name": "UI/UX Designer",
        "phase": 3,
        "description": (
            "Erstellt UI-Konzepte, Wireframes, User Flows, Farbschemata und Design-Tokens. "
            "EINSETZEN bei: Web-Apps, Mobile-Apps, Benutzeroberflächen."
        ),
    },
    "frontend": {
        "name": "Frontend-Entwickler",
        "phase": 3,
        "description": (
            "Implementiert HTML/CSS/JavaScript, React, Vue, Next.js Komponenten. "
            "EINSETZEN bei: Web-Frontends, Web-Apps, Browser-Anwendungen."
        ),
    },
    "backend": {
        "name": "Backend-Entwickler",
        "phase": 3,
        "description": (
            "Entwickelt REST/FastAPI/Node Server-Logik, Authentifizierung, Business-Logik. "
            "EINSETZEN bei: APIs, Server-Anwendungen, Backend-Services."
        ),
    },
    "database": {
        "name": "Datenbank-Entwickler",
        "phase": 3,
        "description": (
            "Entwirft Datenbankschemas (SQL/NoSQL), Migrationen, ORM-Modelle, Abfragen. "
            "EINSETZEN wenn: Datenpersistenz benötigt wird, Datenmodell komplex ist."
        ),
    },
    "api_integration": {
        "name": "API & Integration Specialist",
        "phase": 3,
        "description": (
            "Erstellt OpenAPI 3.1 Specs, GraphQL Schemas, Webhooks, Idempotency & Drittanbieter-Anbindungen (Stripe/OAuth). "
            "EINSETZEN bei: API-Schnittstellen, externen Diensten, Webhooks, Zahlungen."
        ),
    },
    "data_engineer": {
        "name": "Data Engineer",
        "phase": 3,
        "description": (
            "Entwickelt ETL-Pipelines, Event-Streaming (Kafka/RabbitMQ), Redis-Caching-Architektur. "
            "EINSETZEN bei: Streaming, Pipelines, Caching, Event-Driven Architecture."
        ),
    },
    "mobile": {
        "name": "Mobile-Entwickler",
        "phase": 3,
        "description": (
            "Entwickelt iOS- und Android-Apps mit Flutter, React Native, Swift, Kotlin. "
            "EINSETZEN bei: Mobile-App-Entwicklung, Cross-Platform-Apps."
        ),
    },
    "ml": {
        "name": "KI/ML-Entwickler",
        "phase": 3,
        "description": (
            "Integriert LLM-APIs, entwickelt RAG-Systeme, Embeddings, ML-Pipelines. "
            "EINSETZEN bei: KI-Features, Chatbots, Empfehlungssystemen, Embeddings."
        ),
    },
    "performance": {
        "name": "Performance-Ingenieur",
        "phase": 3,
        "description": (
            "Erstellt Load-Tests, optimiert Latenzen, Bottlenecks, Profiling, Query-Optimierung. "
            "EINSETZEN wenn: Performance-Anforderungen vorhanden sind, High-Load erwartet wird."
        ),
    },
    "i18n": {
        "name": "Internationalisierungs-Spezialist",
        "phase": 3,
        "description": (
            "Implementiert Mehrsprachigkeit (i18n/l10n), RTL-Unterstützung, Formatierung. "
            "EINSETZEN wenn: App mehrsprachig sein soll oder international genutzt wird."
        ),
    },

    # ── Phase 3: Infrastruktur & Qualität (parallel) ───────
    "devops": {
        "name": "DevOps-Ingenieur",
        "phase": 3,
        "description": (
            "Erstellt Dockerfile, docker-compose, CI/CD-Pipelines (GitHub Actions), K8s Manifeste. "
            "EINSETZEN bei: Deployment-Bedarf, CI/CD, Container-Infrastruktur."
        ),
    },
    "tester": {
        "name": "QA-Tester",
        "phase": 3,
        "description": (
            "Schreibt Unit-Tests, Integrationstests, End-to-End-Testpläne (Pytest/Jest). "
            "IMMER einsetzen wenn Code produziert wird."
        ),
    },
    "documentation": {
        "name": "Dokumentant",
        "phase": 3,
        "description": (
            "Erstellt API-Dokumentationen, Inline-Kommentare, Architekturdokumente. "
            "EINSETZEN bei: neuen Projekten, APIs, komplexem Code."
        ),
    },
    "security": {
        "name": "Sicherheits-Analyst",
        "phase": 3,
        "description": (
            "Analysiert Code auf Sicherheitslücken (OWASP Top 10, Auth-Flaws, Injection). "
            "EINSETZEN bei: Authentifizierung, sensiblen Daten, APIs, Payment."
        ),
    },

    # ── Phase 4: Review, Refactoring & Compliance (sequentiell)
    "code_reviewer": {
        "name": "Code-Reviewer",
        "phase": 4,
        "description": (
            "Prüft den Code ALLER anderen Agenten auf Qualität, Konsistenz und Bugs. "
            "IMMER einsetzen wenn Code produziert wird."
        ),
    },
    "refactoring": {
        "name": "Refactoring Specialist",
        "phase": 4,
        "description": (
            "Erkennt Code Smells, refaktoriert komplexe Module und stellt strikte Typsicherheit her. "
            "EINSETZEN bei: Refactoring, Code-Modernisierung, Clean Code."
        ),
    },
    "compliance": {
        "name": "Legal & Compliance Specialist",
        "phase": 4,
        "description": (
            "Auditiert DSGVO/GDPR-Konformität, Open-Source-Lizenzen und Accessibility (WCAG). "
            "EINSETZEN bei: Datenschutz, Open-Source-Lizenzprüfung, Barrierefreiheit."
        ),
    },

    # ── Utility-Agenten ────────────────────────────────────
    "readme": {
        "name": "README-Agent",
        "phase": 3,
        "description": (
            "Erstellt oder aktualisiert die README.md für das Projekt. "
            "EINSETZEN wenn: Projektdokumentation für Endnutzer benötigt wird."
        ),
    },
    "github": {
        "name": "GitHub-Agent",
        "phase": 3,
        "description": (
            "Generiert Commit-Messages, Branch-Strategien, PR-Beschreibungen. "
            "EINSETZEN wenn: Git-Workflow-Hilfe oder PR-Vorlagen benötigt werden."
        ),
    },
}

# ──────────────────────────────────────────────────────────
# System-Prompt für die Task-Zerlegung
# ──────────────────────────────────────────────────────────

DECOMPOSE_SYSTEM_PROMPT = """Du bist ein erfahrener Principal Software-Architekt und Engineering Lead.
Deine Aufgabe ist es, eine Software-Entwicklungsaufgabe zu analysieren und in konkrete
Teilaufgaben für spezialisierte Teammitglieder aufzuteilen.

WICHTIG - Phasen-Agenten (besondere Regeln):
1. Phase 1 (business_analyst / product_owner): Einsetzen bei neuen Produktideen, User Stories, MVP-Definitionen.
2. Phase 2 (architect / finops): Immer einsetzen wenn Systemarchitektur oder Cloud-Kosten entworfen werden.
3. Phase 3 (frontend, backend, database, api_integration, data_engineer, etc.): Arbeiten parallel.
4. Phase 4 (code_reviewer, refactoring, compliance): Qualitätssicherung, Code-Review & Compliance.

Antworte NUR mit einem gültigen JSON-Objekt. Keine Erklärungen davor oder danach.

Das JSON-Format ist exakt wie folgt:
{
  "task_summary": "Kurze Zusammenfassung der Gesamtaufgabe",
  "project_slug": "kurzer_projekt_ordnername_ohne_sonderzeichen",
  "required_agents": [
    {
      "agent_id": "<agent_id aus der Liste>",
      "task": "Sehr detaillierte, spezifische Aufgabenbeschreibung für diesen Agenten"
    }
  ]
}

Verfügbare Agenten-IDs:
business_analyst, product_owner, architect, finops,
ui_ux, frontend, backend, database, api_integration, data_engineer, mobile, ml, performance, i18n,
devops, tester, documentation, security,
code_reviewer, refactoring, compliance,
readme, github

Wichtige Regeln:
- Wähle NUR die Agenten, die für die Aufgabe wirklich relevant sind
- Jede Agenten-Aufgabe muss eigenständig und klar definiert sein
- Sei SEHR spezifisch bei den Aufgabenbeschreibungen – je konkreter desto besser
- code_reviewer bei jeder Coding-Aufgabe einschließen
- architect bei Aufgaben mit mehreren Komponenten einschließen
"""


class TaskManager:
    """Analysiert und zerlegt Nutzeraufgaben in parallelisierbare Teilaufgaben."""

    def __init__(self, model_name: str = "gemini-3.6-flash"):
        self._llm = LLMFactory.create_gemini(model_name)

    async def decompose(
        self,
        user_request: str,
        conversation_context: Optional[str] = None
    ) -> tuple[str, str, list[AgentTask]]:
        """
        Analysiert die Nutzeranfrage und erstellt Teilaufgaben für die Agenten.

        Returns:
            Tuple aus (task_summary, project_slug, Liste von AgentTask-Objekten)
        """
        agents_description = "\n".join([
            f"- {agent_id} [Phase {info['phase']}]: {info['description']}"
            for agent_id, info in AVAILABLE_AGENTS.items()
        ])

        context_section = ""
        if conversation_context:
            context_section = f"\n\nVorheriger Gesprächskontext:\n{conversation_context}"

        prompt = f"""Analysiere folgende Nutzeranfrage und erstelle einen Aufgabenplan:

NUTZERANFRAGE:
{user_request}
{context_section}

VERFÜGBARE AGENTEN (mit Phasen):
{agents_description}

Erstelle jetzt das JSON mit den Teilaufgaben."""

        raw_json = await self._llm.generate_json(prompt, DECOMPOSE_SYSTEM_PROMPT)
        plan = self._parse_plan(raw_json)
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
                context=user_request,
            ))

        return task_summary, project_slug, agent_tasks

    def _parse_plan(self, raw_json: str) -> dict:
        """Parst den JSON-String robust."""
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
