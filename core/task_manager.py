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


# Bekannte Agenten und ihre Beschreibungen (für den Decompose-Prompt)
AVAILABLE_AGENTS = {
    "ui_ux": {
        "name": "UI/UX Designer",
        "description": "Erstellt UI-Konzepte, Wireframe-Beschreibungen, User Flows, Farbschemata, Typografie und Komponentenspezifikationen."
    },
    "frontend": {
        "name": "Frontend-Entwickler",
        "description": "Implementiert HTML/CSS/JavaScript, React, Vue.js Komponenten und die gesamte Benutzeroberfläche."
    },
    "backend": {
        "name": "Backend-Entwickler",
        "description": "Entwickelt REST APIs, Server-Logik, Authentifizierung, Business-Logik in Python/Node.js/etc."
    },
    "database": {
        "name": "Datenbank-Entwickler",
        "description": "Entwirft Datenbankschemas (SQL/NoSQL), Migrationen, Abfragen und Optimierungen."
    },
    "devops": {
        "name": "DevOps-Ingenieur",
        "description": "Erstellt Docker-Konfigurationen, CI/CD-Pipelines, Deployment-Skripte und Infrastruktur-Setup."
    },
    "tester": {
        "name": "QA-Tester",
        "description": "Schreibt Unit-Tests, Integrationstests, Testpläne und führt Qualitätssicherung durch."
    },
    "documentation": {
        "name": "Dokumentant",
        "description": "Erstellt README-Dateien, API-Dokumentationen, Inline-Kommentare und Changelogs."
    },
    "security": {
        "name": "Sicherheits-Analyst",
        "description": "Analysiert Code auf Sicherheitslücken, empfiehlt Best Practices und prüft OWASP-Compliance."
    },
    "readme": {
        "name": "README-Agent",
        "description": "Aktualisiert die README.md des Projekts bei Änderungen, neuen Features oder Strukturänderungen."
    },
    "github": {
        "name": "GitHub-Agent",
        "description": "Generiert Commit-Messages, Branch-Strategien, PR-Beschreibungen und Git-Workflow-Empfehlungen."
    },
}

DECOMPOSE_SYSTEM_PROMPT = """Du bist ein erfahrener Software-Architekt und Projektmanager.
Deine Aufgabe ist es, eine Software-Entwicklungsaufgabe zu analysieren und in konkrete Teilaufgaben 
für spezialisierte Agenten aufzuteilen.

Antworte NUR mit einem gültigen JSON-Objekt. Keine Erklärungen davor oder danach.

Das JSON-Format ist wie folgt:
{
  "task_summary": "Kurze Zusammenfassung der Gesamtaufgabe",
  "required_agents": [
    {
      "agent_id": "<einer der verfügbaren Agenten-IDs>",
      "task": "Detaillierte, spezifische Aufgabenbeschreibung für diesen Agenten. Sei sehr konkret!"
    }
  ]
}

Verfügbare Agenten-IDs: ui_ux, frontend, backend, database, devops, tester, documentation, security

Wichtige Regeln:
- Wähle NUR die Agenten, die für die Aufgabe wirklich relevant sind
- Jede Agenten-Aufgabe muss eigenständig und klar definiert sein
- Die Aufgaben sollen parallel bearbeitet werden können
- Sei sehr spezifisch bei den Aufgabenbeschreibungen
"""


class TaskManager:
    """Analysiert und zerlegt Nutzeraufgaben in parallelisierbare Teilaufgaben."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
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
            f"- {agent_id}: {info['description']}"
            for agent_id, info in AVAILABLE_AGENTS.items()
        ])

        context_section = ""
        if conversation_context:
            context_section = f"\n\nVorheriger Gesprächskontext:\n{conversation_context}"

        prompt = f"""Analysiere folgende Nutzeranfrage und erstelle einen Aufgabenplan:

NUTZERANFRAGE:
{user_request}
{context_section}

VERFÜGBARE AGENTEN:
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
                continue  # Unbekannte Agenten ignorieren

            agent_tasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                agent_id=agent_id,
                description=agent_info.get("task", ""),
                context=user_request,
            ))

        return task_summary, agent_tasks

    def _parse_plan(self, raw_json: str) -> dict:
        """Parst den JSON-String zu einem Dictionary. Robust gegen Formatierungsfehler."""
        # Versuche direktes JSON-Parsing
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            pass

        # Versuche JSON aus Markdown-Codeblock zu extrahieren
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_json)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback: Leerer Plan
        return {
            "task_summary": "Aufgabe analysiert",
            "required_agents": []
        }
