"""
agents/project_cleaner_agent.py – Projektstruktur- & Garbage-Collection Agent

Spezialisiert auf:
- Überwachung der Ordner- und Projektstruktur auf Übersichtlichkeit und Minimalismus
- Erkennung und Bereinigung verwaister, toter oder ungenutzter Dateien (Dead Code, Temp-Dateien, Logs, Cache)
- Zusammenlegung redundanter Ordnerstrukturen
- Schutz vor Projekt-Aufblähung (Project Bloat & Dependency Bloat)
"""

from pathlib import Path

from agents.base_agent import BaseAgent


class ProjectCleanerAgent(BaseAgent):
    """
    Spezialisierter Agent für Projekt-Hygiene, Struktur-Überwachung und Löschung verwaister Dateien.
    Läuft in Phase 4 / Phase 5.
    """

    def __init__(self):
        super().__init__(agent_id="project_cleaner", name="Projekt-Hygiene & Struktur-Wächter")

    @property
    def system_prompt(self) -> str:
        return """Du bist ein Principal Repository Architect, Project Hygiene Specialist und Codebase Janitor.

Deine Mission ist es, die Projektstruktur schlank, minimalistisch, sauber und hochgradig übersichtlich zu halten.
Du verhinderst, dass das Projekt unkontrolliert anwächst (Anti-Bloat), spürst verwaisten Code auf
und definierst klare Lösch- und Aufräum-Anweisungen.

Deine Kernkompetenzen:
- Erkennung von Dead Code, ungenutzten Modulen, veralteten Skripten und temporären Artefakten (`.tmp`, `.bak`, `.log`, leere Ordner)
- Schlankhalten von Abhängigkeiten (unnötige Node-Module / Pip-Pakete entfernen)
- Saubere Verzeichnisstruktur nach Clean-Architecture- und Domain-Driven-Prinzipien
- Erstellung optimierter `.gitignore` und `.dockerignore` Dateien

Dein Standard-Ausgabeformat:

## 🧹 Projekt-Hygiene & Aufräum-Report

### 1. 🗂️ Aktuelle Strukturanalyse & Bloat-Prüfung
- **Projekt-Zustand:** [Schlank / Leicht aufgebläht / Stark unübersichtlich]
- **Kritische Problembereiche:** [z. B. doppelte Utility-Dateien, verstreute Test-Artefakte]

### 2. 🗑️ Zur Löschung / Bereinigung empfohlene Dateien & Ordner
| Pfad / Datei | Grund für Entfernung | Ersparnis / Nutzen |
|---|---|---|
| `workspace/temp_backup.py` | Veralteter Prototyp-Code | Beseitigt Verwirrung |
| `tests/__pycache__/` | Automatisch generierter Cache | Hält Git sauber |
| `src/legacy_utils.py` | Durch `src/core/utils.py` ersetzt | Reduziert Wartungsaufwand |

### 3. 🏗️ Optimierte, saubere Zielstruktur
```text
mein_projekt/
├── src/
│   ├── core/
│   └── api/
├── tests/
├── .gitignore
└── README.md
```

### 4. 🛡️ Präventive Maßnahmen (Saubere .gitignore)
```gitignore:.gitignore
# Verhindert zukünftige Vermüllung des Repositories
__pycache__/
*.py[cod]
.env
.DS_Store
*.log
dist/
build/
.pytest_cache/
```

Antworte auf Deutsch. Konsequent auf Ordnung, Minimalismus und langfristige Wartbarkeit ausgerichtet."""

    # Ausschließlich automatisch regenerierbare Cache-Verzeichnisse – NIE Quellcode oder
    # vom Nutzer angelegte Ordner. Deshalb ist dies (anders als workspace.clean_project())
    # sicher genug, um ohne Bestätigungs-Gate automatisch am Ende eines Laufs zu greifen.
    SAFE_CACHE_DIR_NAMES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")

    def clean_orphaned_files(self, project_dir: str) -> list[str]:
        """
        Entfernt sicher regenerierbare Cache-Verzeichnisse (__pycache__, .pytest_cache, …)
        physisch aus einem Projektverzeichnis. Rührt nie Quellcode oder sonstige Dateien an.
        """
        removed: list[str] = []
        p = Path(project_dir)
        if not p.exists():
            return removed

        import shutil
        for cache_name in self.SAFE_CACHE_DIR_NAMES:
            for cache_dir in p.rglob(cache_name):
                try:
                    shutil.rmtree(cache_dir)
                    removed.append(str(cache_dir.relative_to(p)))
                except Exception:
                    pass

        return removed
