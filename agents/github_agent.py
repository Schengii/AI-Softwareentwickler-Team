"""
agents/github_agent.py – GitHub/Git Agent

Spezialisierter Agent für Git-Operationen und GitHub-Workflows.
Generiert Commit-Messages, Branch-Strategien und PR-Beschreibungen.
Kann auch direkte Git-Kommandos vorschlagen.
"""

import asyncio
import json
import shutil
import subprocess
import uuid

from agents.base_agent import BaseAgent
from config import BASE_DIR
from core.git_isolation import slugify
from core.secret_scanner import SecretFinding, scan_diff


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

    def scan_for_secrets(self) -> list[SecretFinding]:
        """
        Staged alle Änderungen (git add -A – dasselbe, was commit() ohnehin gleich danach
        tut, hier vorgezogen) und durchsucht den vollständigen Diff (inkl. neuer, noch nicht
        getrackter Dateien) nach möglichen Secrets, BEVOR committet wird. Siehe
        core/secret_scanner.py für die Erkennungslogik. Rein lesend im Ergebnis – blockiert
        nichts selbst, der Aufrufer (interface/cli.py) entscheidet, was mit dem Fund passiert.
        """
        self._run_git("add", "-A")
        diff = self._run_git("diff", "--cached")
        return scan_diff(diff)

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

    def get_current_branch(self) -> str:
        """Gibt den Namen des aktuell ausgecheckten Branches zurück."""
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def push(self, remote: str = "origin", branch: str | None = None) -> tuple[bool, str]:
        """
        Pusht den aktuellen Branch zum Remote.

        Realer Fund: `branch` war bisher fest auf "main" verdrahtet – push() pushte damit
        IMMER den lokalen "main"-Branch zum Remote, unabhängig davon, welcher Branch
        tatsächlich ausgecheckt war (z.B. ein Feature-Branch oder ein isolierter
        Selbstverbesserungs-Worktree-Branch, siehe core/git_isolation.py). `branch=None`
        (Standard) ermittelt jetzt den tatsächlich aktiven Branch automatisch und setzt bei
        Bedarf das Upstream-Tracking (`-u`, wichtig für neue/noch nie gepushte Branches).

        Returns:
            (Erfolg, Ausgabe)
        """
        target_branch = branch or self.get_current_branch()
        result = subprocess.run(
            ["git", "push", "-u", remote, target_branch],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    async def wait_for_ci_status(
        self, branch: str, timeout_seconds: float = 90.0, poll_interval: float = 5.0,
    ) -> tuple[str, str]:
        """
        Wartet auf den Status des zuletzt für `branch` gestarteten GitHub-Actions-Laufs
        (per `gh` CLI) und gibt (status, detail) zurück:
        - "passed"  – Lauf abgeschlossen, alle Jobs erfolgreich
        - "failed"  – Lauf abgeschlossen, mindestens ein Job fehlgeschlagen (detail = URL)
        - "timeout" – nach timeout_seconds immer noch nicht abgeschlossen
        - "no_run"  – kein Lauf gefunden / `gh` nicht nutzbar (kein GitHub-Remote, gh fehlt,
                      nicht eingeloggt, ...) – KEIN Fehler, einfach nicht prüfbar

        Realer Fund: push() war bisher "fire and forget" – ob die echte CI-Pipeline
        (.github/workflows/ci.yml, läuft bei jedem Push) tatsächlich grün wird, hat das Team
        nie erfahren. Ein menschlicher Entwickler beobachtet den Status seines Pushs, statt
        ihn zu ignorieren.
        """
        elapsed = 0.0
        while True:
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["gh", "run", "list", "--branch", branch, "--limit", "1",
                     "--json", "status,conclusion,url"],
                    cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                return "no_run", f"gh CLI nicht nutzbar: {e}"

            if result.returncode != 0:
                return "no_run", (result.stderr or result.stdout).strip() or "gh CLI/GitHub-Remote nicht verfügbar."

            try:
                runs = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                return "no_run", "Unerwartete Ausgabe von `gh run list`."

            if not runs:
                return "no_run", f"Kein CI-Lauf für Branch '{branch}' gefunden (evtl. noch nicht gestartet)."

            run = runs[0]
            if run.get("status") == "completed":
                conclusion = run.get("conclusion", "")
                if conclusion == "success":
                    return "passed", run.get("url", "")
                return "failed", f"{conclusion or 'unbekannt'} – {run.get('url', '')}"

            if elapsed >= timeout_seconds:
                return "timeout", f"CI nach {timeout_seconds:.0f}s noch nicht abgeschlossen: {run.get('url', '')}"

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    # ──────────────────────────────────────────
    # PR-Workflow: Feature-Branch + Pull Request statt Direct-Push auf einen Hauptbranch
    # ──────────────────────────────────────────
    # Realer struktureller Unterschied zu einem echten Team: push() commitete bisher direkt
    # auf den gerade ausgecheckten Branch – bei einem frischen/geladenen Projekt i.d.R.
    # "main". Ein echtes Team committet nicht direkt auf den Hauptbranch, sondern legt pro
    # Aufgabe einen Feature-Branch an, öffnet einen Pull Request und lässt CI/Review VOR dem
    # Merge laufen. interface/cli.py._ask_for_git_push() nutzt die folgenden Methoden dafür,
    # WENN der aktuelle Branch einer von config.GIT_PROTECTED_BRANCHES ist UND gh_ready()
    # True liefert – sonst bleibt es beim bisherigen Direct-Push (Graceful Degradation ohne
    # `gh`-CLI/GitHub-Remote, statt den Nutzer komplett zu blockieren).

    def build_feature_branch_name(self, task_summary: str) -> str:
        """
        Erzeugt einen eindeutigen Feature-Branch-Namen aus der Aufgabenbeschreibung –
        dieselbe Slug+UUID-Namenskonvention wie core/git_isolation.py für isolierte
        Selbstverbesserungs-Worktrees, hier unter dem Präfix "feat/" statt "ai-team/", da es
        sich um einen normalen, auf GitHub sichtbaren Feature-Branch handelt (kein isolierter
        Selbstverbesserungslauf).
        """
        return f"feat/{slugify(task_summary)}-{uuid.uuid4().hex[:6]}"

    def create_branch(self, branch_name: str) -> tuple[bool, str]:
        """Legt einen neuen lokalen Branch vom aktuellen HEAD an und checkt ihn aus."""
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    def checkout(self, branch: str) -> tuple[bool, str]:
        """
        Wechselt zu einem bereits existierenden lokalen Branch zurück – genutzt, um nach
        Push+PR-Erstellung wieder auf den ursprünglichen Hauptbranch zu wechseln, damit die
        NÄCHSTE Aufgabe wieder von einem sauberen Hauptbranch-Stand aus einen neuen
        Feature-Branch anlegt, statt unbemerkt auf demselben Feature-Branch weiterzuarbeiten.
        """
        result = subprocess.run(
            ["git", "checkout", branch],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    def gh_ready(self) -> bool:
        """
        Prüft, ob die `gh`-CLI installiert UND eingeloggt ist – Voraussetzung für
        create_pull_request(). Reine Fähigkeitsprüfung ohne Fehler bei negativem Ergebnis:
        der Aufrufer (interface/cli.py) entscheidet selbst, ob er dann auf den bisherigen
        Direct-Push zurückfällt.
        """
        if shutil.which("gh") is None:
            return False
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=10, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def create_pull_request(self, title: str, body: str, base: str, head: str) -> tuple[bool, str]:
        """
        Erstellt einen Pull Request per `gh pr create` – Voraussetzung: `head` wurde bereits
        gepusht (push()) und gh_ready() war True. Gibt bei Erfolg die von `gh` ausgegebene
        PR-URL zurück (letzte Zeile von stdout), sonst die Fehlerausgabe. Wirft NIE eine
        Exception – ein fehlgeschlagener PR-Aufruf soll den bereits gepushten Branch nicht
        verwerfen, nur ohne automatisch erstellten PR liegen lassen (der Nutzer kann ihn dann
        manuell auf GitHub anlegen).
        """
        try:
            result = subprocess.run(
                ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=30, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        success = result.returncode == 0
        output = (result.stdout + result.stderr).strip()
        return success, output

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
