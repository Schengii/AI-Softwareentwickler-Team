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
# Alle verfügbaren Agenten (17 Spezialisten)
# ──────────────────────────────────────────────────────────

AVAILABLE_AGENTS = {
    # ── Phasen-Agenten (sequentiell) ──────────────────────
    "business_analyst": {
        "name": "Business Analyst",
        "phase": 1,
        "description": (
            "Analysiert und klärt Anforderungen, erstellt User Stories und Akzeptanzkriterien. "
            "EINSETZEN wenn: Anforderungen komplex/mehrdeutig sind, Business-Kontext wichtig ist, "
            "oder das Projekt scope-definiert werden muss."
        ),
    },
    "architect": {
        "name": "Software-Architekt",
        "phase": 2,
        "description": (
            "Entwirft die Gesamtarchitektur BEVOR andere Agenten implementieren. "
            "Erstellt Systemdiagramme, API-Contracts und Technologie-Entscheidungen. "
            "EINSETZEN wenn: mehrere Komponenten zusammenarbeiten, Technologiewahl unklar ist, "
            "oder das System skalierbar/erweiterbar sein muss."
        ),
    },
    "code_reviewer": {
        "name": "Code-Reviewer",
        "phase": 4,
        "description": (
            "Prüft den Code ALLER anderen Agenten auf Qualität und Konsistenz. "
            "IMMER einsetzen wenn Code produziert wird (frontend, backend, database, mobile, ml, etc.)."
        ),
    },

    # ── Implementierungs-Agenten (parallel) ───────────────
    "ui_ux": {
        "name": "UI/UX Designer",
        "phase": 3,
        "description": (
            "Erstellt UI-Konzepte, Wireframe-Beschreibungen, User Flows, Farbschemata, "
            "Typografie und Komponentenspezifikationen. EINSETZEN bei: Web-Apps, Mobile-Apps, "
            "Desktop-Software mit Benutzeroberfläche."
        ),
    },
    "frontend": {
        "name": "Frontend-Entwickler",
        "phase": 3,
        "description": (
            "Implementiert HTML/CSS/JavaScript, React, Vue.js Komponenten und Benutzeroberflächen. "
            "EINSETZEN bei: Web-Frontends, Web-Apps, Browser-basierte Anwendungen."
        ),
    },
    "backend": {
        "name": "Backend-Entwickler",
        "phase": 3,
        "description": (
            "Entwickelt REST APIs, Server-Logik, Authentifizierung, Business-Logik in Python/Node.js. "
            "EINSETZEN bei: APIs, Server-Anwendungen, Backend-Services."
        ),
    },
    "database": {
        "name": "Datenbank-Entwickler",
        "phase": 3,
        "description": (
            "Entwirft Datenbankschemas (SQL/NoSQL), Migrationen, Abfragen und Optimierungen. "
            "EINSETZEN wenn: Datenpersistenz benötigt wird, Datenmodell komplex ist."
        ),
    },
    "mobile": {
        "name": "Mobile-Entwickler",
        "phase": 3,
        "description": (
            "Entwickelt iOS- und Android-Apps mit React Native, Flutter, Swift oder Kotlin. "
            "EINSETZEN bei: Mobile-App-Entwicklung, Cross-Platform-Apps."
        ),
    },
    "ml": {
        "name": "KI/ML-Entwickler",
        "phase": 3,
        "description": (
            "Integriert LLM-APIs (Gemini, Claude, OpenAI), entwickelt ML-Modelle, "
            "RAG-Systeme, Datenanalyse. EINSETZEN bei: KI-Features, Chatbots, "
            "Empfehlungssysteme, Datenanalyse."
        ),
    },
    "performance": {
        "name": "Performance-Ingenieur",
        "phase": 3,
        "description": (
            "Erstellt Load-Tests, analysiert Performance-Engpässe, optimiert Backend und Frontend. "
            "EINSETZEN wenn: Performance-Anforderungen vorhanden sind, Skalierbarkeit wichtig ist, "
            "oder Performance-Optimierung explizit gewünscht wird."
        ),
    },
    "i18n": {
        "name": "Internationalisierungs-Spezialist",
        "phase": 3,
        "description": (
            "Implementiert Mehrsprachigkeit (i18n/l10n), RTL-Unterstützung, "
            "Zeitzonen- und Währungsformatierung. EINSETZEN wenn: App mehrsprachig sein soll "
            "oder internationale Nutzer angesprochen werden."
        ),
    },

    # ── Infrastruktur & Qualität (parallel) ───────────────
    "devops": {
        "name": "DevOps-Ingenieur",
        "phase": 3,
        "description": (
            "Erstellt Docker-Konfigurationen, CI/CD-Pipelines, Deployment-Skripte. "
            "EINSETZEN bei: Deployment-Bedarf, CI/CD, Container-Infrastruktur."
        ),
    },
    "tester": {
        "name": "QA-Tester",
        "phase": 3,
        "description": (
            "Schreibt Unit-Tests, Integrationstests, Testpläne. "
            "IMMER einsetzen wenn Code produziert wird."
        ),
    },
    "documentation": {
        "name": "Dokumentant",
        "phase": 3,
        "description": (
            "Erstellt README-Dateien, API-Dokumentationen, Inline-Kommentare, Changelogs. "
            "EINSETZEN bei: neuen Projekten, öffentlichen APIs, komplexem Code."
        ),
    },
    "security": {
        "name": "Sicherheits-Analyst",
        "phase": 3,
        "description": (
            "Analysiert Code auf Sicherheitslücken, OWASP-Compliance. "
            "EINSETZEN bei: Authentifizierungssystemen, öffentlichen APIs, "
            "sensiblen Daten, Payment-Systemen."
        ),
    },

    # ── Utility-Agenten ────────────────────────────────────
    "readme": {
        "name": "README-Agent",
        "phase": 3,
        "description": (
            "Aktualisiert die README.md des Projekts bei Änderungen. "
            "EINSETZEN wenn: das eigene KI-Team-Projekt geändert wird."
        ),
    },
    "github": {
        "name": "GitHub-Agent",
        "phase": 3,
        "description": (
            "Generiert Commit-Messages, Branch-Strategien, PR-Beschreibungen. "
            "EINSETZEN wenn: Git-Workflow-Hilfe oder Commit-Messages benötigt werden."
        ),
    },
}

# ──────────────────────────────────────────────────────────
# System-Prompt für die Task-Zerlegung
# ──────────────────────────────────────────────────────────

DECOMPOSE_SYSTEM_PROMPT = """Du bist ein erfahrener Software-Architekt und Projektmanager.
Deine Aufgabe ist es, eine Software-Entwicklungsaufgabe zu analysieren und in konkrete
Teilaufgaben für spezialisierte Agenten aufzuteilen.

WICHTIG - Phasen-Agenten (besondere Regeln):

1. business_analyst (Phase 1): Immer einsetzen wenn Anforderungen mehrdeutig/komplex sind.
2. architect (Phase 2): Immer einsetzen wenn mehrere technische Komponenten zusammenarbeiten.
3. code_reviewer (Phase 4): IMMER einsetzen wenn Code produziert wird.

Antworte NUR mit einem gültigen JSON-Objekt. Keine Erklärungen davor oder danach.

Das JSON-Format ist exakt wie folgt:
{
  "task_summary": "Kurze Zusammenfassung der Gesamtaufgabe",
  "required_agents": [
    {
      "agent_id": "<agent_id aus der Liste>",
      "task": "Sehr detaillierte, spezifische Aufgabenbeschreibung für diesen Agenten"
    }
  ]
}

Verfügbare Agenten-IDs:
business_analyst, architect, code_reviewer,
ui_ux, frontend, backend, database, mobile, ml, performance, i18n,
devops, tester, documentation, security, readme, github

Wichtige Regeln:
- Wähle NUR die Agenten, die für die Aufgabe wirklich relevant sind
- Jede Agenten-Aufgabe muss eigenständig und klar definiert sein
- Agenten in Phase 3 können parallel arbeiten
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
    ) -> tuple[str, list[AgentTask]]:
        """
        Analysiert die Nutzeranfrage und erstellt Teilaufgaben für die Agenten.

        Returns:
            Tuple aus (task_summary, Liste von AgentTask-Objekten)
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

        return task_summary, agent_tasks

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

        return {"task_summary": "Aufgabe analysiert", "required_agents": []}
