"""
agents/project_cleaner_agent.py – Projektstruktur- & Garbage-Collection Agent

Spezialisiert auf:
- Überwachung der Ordner- und Projektstruktur auf Übersichtlichkeit und Minimalismus
- Erkennung und Bereinigung verwaister, toter oder ungenutzter Dateien (Dead Code, Temp-Dateien, Logs, Cache)
- Zusammenlegung redundanter Ordnerstrukturen
- Schutz vor Projekt-Aufblähung (Project Bloat & Dependency Bloat)
"""

import re
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

### 5. Maschinenlesbare Löschliste
Am ENDE deiner Antwort MUSST du zusätzlich einen Codeblock mit exakt diesem Format anhängen –
nur Pfade, die du unter Punkt 2 auch wirklich als sicher zur Löschung empfohlen hast, einer pro
Zeile, relativ zum Projekt-Root. Nutze list_files/read_file/search_code, um dich VOR jeder
Empfehlung wirklich zu vergewissern, dass ein Pfad unbenutzt ist – im Zweifel NICHT auflisten:
```deletions
pfad/zur/datei_oder_ordner_1
pfad/zur/datei_oder_ordner_2
```
Ist nichts zur Löschung empfohlen, gib einen leeren Codeblock ```deletions\n```  aus.

WICHTIG: Du hast nur LESE-Zugriff (list_files, read_file, search_code) – du kannst und darfst
selbst nichts löschen oder verändern. Jede Löschung aus deiner Liste wird ausschließlich nach
expliziter Bestätigung durch den Menschen ausgeführt.

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

    @staticmethod
    def parse_recommended_deletions(report_text: str) -> list[str]:
        """
        Extrahiert die maschinenlesbare Löschliste (```deletions ... ```-Block) aus einem
        echten Hygiene-Report des Agenten. Robust gegen Leerzeilen/Whitespace; gibt bei
        fehlendem oder leerem Block eine leere Liste zurück (kein Fehler).
        """
        match = re.search(r"```deletions\s*\n(.*?)```", report_text, re.DOTALL)
        if not match:
            return []
        paths = [line.strip() for line in match.group(1).splitlines()]
        return [p for p in paths if p and not p.startswith("#")]

    @staticmethod
    def apply_confirmed_deletions(project_dir: str, relative_paths: list[str]) -> tuple[list[str], list[str]]:
        """
        Löscht NUR die übergebenen, bereits vom Menschen bestätigten Pfade (Dateien oder
        Ordner) innerhalb von project_dir. Wird ausschließlich von interface/cli.py nach
        einer expliziten Confirm.ask()-Bestätigung aufgerufen – niemals von einem Agenten
        selbst (dieser hat dafür bewusst kein Werkzeug in core/agent_toolbox.py).

        Returns: (erfolgreich_geloescht, fehlgeschlagen_oder_ausserhalb)
        """
        import shutil

        base = Path(project_dir).resolve()
        removed: list[str] = []
        failed: list[str] = []

        for rel in relative_paths:
            clean = rel.replace("\\", "/").lstrip("/")
            target = (base / clean).resolve()
            if target != base and base not in target.parents:
                failed.append(f"{rel} (außerhalb des Projektverzeichnisses – abgelehnt)")
                continue
            if not target.exists():
                failed.append(f"{rel} (existiert nicht mehr)")
                continue
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                removed.append(rel)
            except Exception as e:
                failed.append(f"{rel} ({e})")

        return removed, failed
