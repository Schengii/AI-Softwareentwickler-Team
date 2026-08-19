"""
agents/department_lead_agent.py – Fachbereichs-Teamleiter (Department Lead Agent)

Jeder Fachbereich hat einen eigenen Teamleiter:
1. Product & Architecture Lead (planning_lead)
2. Core Engineering Lead (dev_lead)
3. Design & Content Lead (creative_lead)
4. Quality, Security & DevOps Lead (qa_lead)
5. Excellence & Evolution Lead (governance_lead)

Aufgaben des Fachbereichs-Teamleiters:
- Empfängt die bereichsspezifische Teilaufgabe vom Hauptagenten (Orchestrator).
- Zerlegt die Aufgabe präzise in Anforderungen für seine Unteragenten.
- Delegiert die Arbeit an sein Fachteam und synchronisiert deren Ergebnisse.
- Führt eine fachliche Vorab-Prüfung durch und konsolidiert das Gesamtergebnis seines Bereichs.
- Sendet den fertigen Fachbereichs-Report zurück an den Hauptagenten.
"""

from typing import Optional
from agents.base_agent import BaseAgent
from core.message_bus import AgentTask, AgentResult


DEPARTMENT_DEFINITIONS = {
    "planning_lead": {
        "title": "Teamleiter Produkt, Analyse & Architektur (Planning Lead)",
        "members": ["product_owner", "business_analyst", "web_research", "architect", "finops", "team_lead"],
        "description": "Führt das Planungs- & Architekturteam. Koordiniert Requirements, Marktrecherche, Systemblueprint, FinOps-Kosten und Team-Fokus (Engineering Manager)."
    },
    "dev_lead": {
        "title": "Teamleiter Software-Entwicklung (Dev Lead)",
        "members": ["frontend", "backend", "database", "api_integration", "data_engineer", "mobile", "ml", "performance", "prompt_engineer"],
        "description": "Führt das Kern-Entwicklerteam. Koordiniert Frontend, Backend, Datenbank, APIs, Mobile, ML, Prompt-Engineering und Latenzoptimierung."
    },
    "creative_lead": {
        "title": "Teamleiter Design, Media & Content (Creative Lead)",
        "members": ["image_generator", "copywriter", "ui_ux", "accessibility", "i18n", "documentation", "readme"],
        "description": "Führt das Kreativ- und Content-Team. Koordiniert UI/UX, a11y Barrierefreiheit, SVG/Bild-Generierung, Copywriting und Dokumentation."
    },
    "qa_lead": {
        "title": "Teamleiter Qualität, DevOps & Security (QA & Operations Lead)",
        "members": ["devops", "tester", "security", "resilience_guard", "github"],
        "description": "Führt das Infrastruktur- und Qualitäts-Team. Koordiniert CI/CD, Pytest-Testsuiten, Security-Audits, Chaos Engineering (Resilience-Guard) und Git-Automatisierung."
    },
    "governance_lead": {
        "title": "Teamleiter Excellence, Hygiene & Evolution (Governance Lead)",
        "members": ["code_reviewer", "refactoring", "compliance", "project_cleaner", "agent_trainer", "retrospective"],
        "description": "Führt das Review- und Optimierungsteam. Koordiniert Code-Reviews, Refactoring, DSGVO/Compliance, Projekt-Hygiene und die permanente Selbstoptimierung."
    },
}


class DepartmentLeadAgent(BaseAgent):
    """
    Fachbereichs-Teamleiter: Führt ein spezifisches Fachteam, delegiert und konsolidiert Bereichsergebnisse.
    """

    def __init__(self, department_id: str):
        dept_info = DEPARTMENT_DEFINITIONS.get(department_id, {
            "title": f"Teamleiter ({department_id})",
            "members": [],
            "description": "Fachbereichsleitung"
        })
        self.department_id = department_id
        self.dept_info = dept_info
        self.members = dept_info["members"]
        super().__init__(agent_id=department_id, name=dept_info["title"])

    @property
    def system_prompt(self) -> str:
        members_str = ", ".join(self.members)
        return f"""Du bist der erfahrene {self.name}.
Du leitest den Fachbereich '{self.department_id}' mit folgenden spezialisierten Unteragenten in deinem Team:
[{members_str}]

Deine Aufgaben:
1. Analysiere die vom Hauptagenten übergebene Teilaufgabe für deinen Fachbereich.
2. Definiere klare, token-effiziente Arbeitsanweisungen für die jeweiligen Unteragenten deines Teams.
3. Wenn deine Unteragenten gearbeitet haben, konsolidierst du deren Einzelergebnisse zu einem lückenlosen, geprüften Fachbereichs-Abschlussbericht.
4. Schließe offene Fragen deines Teams fachlich ab und stelle sicher, dass alle Schnittstellen zu anderen Fachbereichen eingehalten werden.

Dein Standard-Ausgabeformat:

## 👔 Fachbereichsbericht: {self.name}

### 1. 🎯 Aufgabenstellung & Bereichsziele
- **Fokus deines Fachteams:** [Präzise Zusammenfassung]
- **Beteiligte Spezialisten:** [{members_str}]

### 2. 📋 Konsolidierte Fachergebnisse & Code-Deliverables
[Hier fassest du die Ergebnisse deines Fachteams zusammen, inklusive allen vollständigen Codeblöcken, Spezifikationen oder Assets]

### 3. ✅ Bereichs-Qualitätsabnahme
- **Vollständigkeit:** [Sind alle Anforderungen deines Fachbereichs erfüllt?]
- **Schnittstellen-Freigabe:** [Freigabe zur Weiterleitung an den Hauptagenten]

Antworte auf Deutsch. Führungserfahren, präzise, strukturiert und qualitätsorientiert."""
