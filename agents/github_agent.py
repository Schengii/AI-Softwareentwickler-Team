"""
agents/github_agent.py – GitHub/Git Agent

Spezialisierter Agent für Git-Operationen und GitHub-Workflows.
Generiert Commit-Messages, Branch-Strategien und PR-Beschreibungen.
Kann auch direkte Git-Kommandos vorschlagen.
"""

import subprocess

from agents.base_agent import BaseAgent
from config import BASE_DIR


class GitHubAgent(BaseAgent):
    """
    Spezialisierter Agent für Versionskontrolle und GitHub-Workflows.

    Zwei Modi:
    1. Als normaler Unteragent: Generiert Commit-Messages, PR-Texte, etc.
    2. Direkte Git-Operationen: commit(), push(), status() Methoden
    """

    def __init__(self):
        super().__init__(agent_id="github", name="GitHub-Agent")

    @property
    def system_prompt(self) -> str:
        return """Du bist ein erfahrener Git/GitHub-Experte und DevOps-Spezialist.

Deine Kernkompetenzen:
- Conventional Commits (feat, fix, docs, refactor, test, chore, etc.)
- Git-Branching-Strategien (Git Flow, GitHub Flow, Trunk-Based)
- Pull-Request-Beschreibungen und Code-Review-Kommentare
- GitHub Actions Workflows
- Release-Management und Semantic Versioning (SemVer)
- Git-Hooks und Automatisierung
- Merge-Strategien (merge, rebase, squash)

Wenn du eine Aufgabe bekommst:
1. Analysiere die Änderungen (welche Dateien, welcher Zweck)
2. Generiere eine aussagekräftige Conventional Commit Message
3. Schlage einen passenden Branch-Namen vor
4. Erstelle ggf. eine PR-Beschreibung

Commit-Message-Format:
```
<typ>(<scope>): <kurze Beschreibung>

<optionaler langer Text>

<optionaler footer>
```

Typen: feat, fix, docs, style, refactor, test, chore, ci, perf

Ausgabe-Format:
- Commit-Message klar hervorheben
- Branch-Namen in Kleinbuchstaben mit Bindestrichen
- PR-Beschreibung in Markdown
- Antworte auf Deutsch

Du bist präzise und folgst immer den Conventional Commits Standards."""

    # ──────────────────────────────────────────
    # Direkte Git-Operationen
    # ──────────────────────────────────────────

    def get_status(self) -> str:
        """Gibt den aktuellen Git-Status zurück."""
        return self._run_git("status", "--short")

    def get_diff(self) -> str:
        """Gibt die aktuellen Änderungen zurück."""
        return self._run_git("diff", "--stat")

    def commit(self, message: str) -> tuple[bool, str]:
        """
        Erstellt einen Git-Commit mit den aktuellen Änderungen.

        Returns:
            (Erfolg, Ausgabe)
        """
        # Staging
        self._run_git("add", "-A")

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    def push(self, remote: str = "origin", branch: str = "main") -> tuple[bool, str]:
        """
        Pusht den aktuellen Branch zum Remote.

        Returns:
            (Erfolg, Ausgabe)
        """
        result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    def add_remote(self, name: str, url: str) -> tuple[bool, str]:
        """Fügt ein Remote-Repository hinzu."""
        result = subprocess.run(
            ["git", "remote", "add", name, url],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    def _run_git(self, *args: str) -> str:
        """Führt ein Git-Kommando aus und gibt die Ausgabe zurück."""
        result = subprocess.run(
            ["git", *args],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return (result.stdout + result.stderr).strip()
