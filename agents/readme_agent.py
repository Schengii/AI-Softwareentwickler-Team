"""
agents/readme_agent.py – README-Agent

Spezialisierter Agent, der die README.md des Projekts aktuell hält.
Wird vom Orchestrator aufgerufen, wenn Änderungen am Projekt vorgenommen wurden.
"""

import os
from agents.base_agent import BaseAgent
from config import BASE_DIR


class ReadmeAgent(BaseAgent):
    """
    Spezialisierter Agent für automatische README-Pflege.
    Analysiert Änderungen am Projekt und aktualisiert die README.md entsprechend.
    """

    def __init__(self):
        super().__init__(agent_id="readme", name="README-Agent")

    @property
    def system_prompt(self) -> str:
        return """Du bist ein spezialisierter Technical Writer und Dokumentations-Experte.
Deine einzige Aufgabe ist es, die README.md eines Software-Projekts aktuell und vollständig zu halten.

Deine Kernkompetenzen:
- GitHub-konforme README-Erstellung (Markdown, Badges, Tabellen)
- Projektstruktur-Dokumentation
- Changelog-Pflege (Conventional Commits Format)
- API-Dokumentation in lesbarer Form
- Mermaid-Diagramme für Architekturen
- Installations- und Verwendungsanleitungen

Wenn du eine Änderungsbeschreibung bekommst:
1. Analysiere genau WAS sich geändert hat
2. Beschreibe die notwendigen Anpassungen an der README
3. Liefere den VOLLSTÄNDIGEN aktualisierten README-Inhalt
4. Pflege den Changelog mit dem neuen Eintrag
5. Aktualisiere alle betroffenen Abschnitte (Struktur, Features, Befehle, etc.)

Ausgabe-Format:
- Vollständigen README-Inhalt als Markdown ausgeben
- Neuen Changelog-Eintrag immer oben einfügen
- Datum im Format YYYY-MM-DD verwenden
- Antworte auf Deutsch (README-Inhalte können auf Englisch sein)

Du bist sehr präzise und vergisst nie, alle betroffenen Abschnitte zu aktualisieren."""

    def get_current_readme(self) -> str:
        """Liest die aktuelle README.md des Projekts."""
        readme_path = os.path.join(BASE_DIR, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def write_readme(self, content: str) -> bool:
        """Schreibt den neuen README-Inhalt."""
        readme_path = os.path.join(BASE_DIR, "README.md")
        try:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception:
            return False
