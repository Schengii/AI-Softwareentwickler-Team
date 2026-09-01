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

    def create_branch(self, branch_name: str, base: str | None = None) -> tuple[bool, str]:
        """
        Legt einen neuen lokalen Branch an und checkt ihn aus – von `base`, falls angegeben,
        sonst vom aktuellen HEAD. `base` explizit zu setzen ist wichtig, sobald das
        Arbeitsverzeichnis NICHT mehr zuverlässig auf dem Hauptbranch steht (siehe
        interface/cli.py._ask_for_git_push(): nach einem PR-Workflow-Lauf bleibt das
        Arbeitsverzeichnis jetzt bewusst auf dem zuletzt genutzten Feature-Branch stehen,
        damit gerade erst generierte Dateien nicht durch einen Checkout unsichtbar werden).
        """
        args = ["checkout", "-b", branch_name]
        if base:
            args.append(base)
        result = subprocess.run(
            ["git", *args],
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

    def create_pull_request(self, title: str, body: str, base: str, head: str, draft: bool = False) -> tuple[bool, str]:
        """
        Erstellt einen Pull Request per `gh pr create` – Voraussetzung: `head` wurde bereits
        gepusht (push()) und gh_ready() war True. Gibt bei Erfolg die von `gh` ausgegebene
        PR-URL zurück (letzte Zeile von stdout), sonst die Fehlerausgabe. Wirft NIE eine
        Exception – ein fehlgeschlagener PR-Aufruf soll den bereits gepushten Branch nicht
        verwerfen, nur ohne automatisch erstellten PR liegen lassen (der Nutzer kann ihn dann
        manuell auf GitHub anlegen).

        draft=True erstellt den PR als Draft (`gh pr create --draft`) - genutzt von
        interface/cli.py._ask_for_git_push(), wenn die echte Testsuite den Code NICHT
        bestätigt bestanden hat (realer Fund: ein normaler PR mit rein informativer Warnung im
        Body wurde trotzdem anstandslos gemerged, siehe README/PR-Workflow-Abschnitt - ein
        Draft-Status macht "noch nicht bereit" für GitHub selbst sichtbar, nicht nur im Text).
        """
        command = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]
        if draft:
            command.append("--draft")
        try:
            result = subprocess.run(
                command,
                cwd=BASE_DIR, capture_output=True, text=True, timeout=30, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        success = result.returncode == 0
        output = (result.stdout + result.stderr).strip()
        return success, output

    # Feste Palette statt vom Modell frei erfundener Label-Namen/Farben - `gh pr create
    # --label` schlägt fehl, wenn das Label im Repo noch nicht existiert (kein Auto-Anlegen),
    # deshalb müssen Name UND Farbe hier vorab bekannt sein, bevor label_pr() sie per
    # `gh label create --force` sicherstellt.
    _STATUS_LABELS: dict[str, tuple[str, str]] = {
        "verification-failed": ("d73a4a", "Echte Testsuite hat diesen PR nicht bestätigt bestanden"),
        "budget-aborted": ("e99695", "Lauf-Budget wurde erreicht, verbleibende Fachbereiche übersprungen"),
        "needs-clarification": ("fbca04", "Mindestens eine Fachrolle hat eine offene Rückfrage"),
    }

    def label_pr(self, pr_url_or_number: str, labels: list[str]) -> tuple[bool, str]:
        """
        Realer Fund: der Verifikationsstatus eines Laufs steckte bisher nur im Titel-Präfix und
        im PR-Body (siehe interface/cli.py._ask_for_git_push()) - in der PR-LISTE auf GitHub
        (die häufigste Stelle, an der ein Reviewer mehrere offene PRs überfliegt) ist davon
        nichts sichtbar, ein Titel-Präfix geht dort im Rauschen langer Aufgabenbeschreibungen
        unter. Labels erscheinen dort als eigene, farbige Chips.

        Legt jedes benötigte Label per `gh label create --force` an (idempotent - überschreibt
        Farbe/Beschreibung eines bereits vorhandenen Labels desselben Namens, statt bei
        Kollision zu scheitern), bevor es per `gh pr edit --add-label` auf den PR angewendet
        wird. Wirft NIE eine Exception, aus demselben Grund wie create_pull_request() oben: ein
        fehlgeschlagenes Label darf einen bereits erfolgreich erstellten PR nicht verwerfen.
        Nur Namen aus _STATUS_LABELS werden akzeptiert (kein beliebiger String vom Aufrufer).
        """
        unknown = [name for name in labels if name not in self._STATUS_LABELS]
        if unknown:
            return False, f"Unbekannte Label(s), nicht in _STATUS_LABELS: {unknown}"
        if not labels:
            return True, ""
        for name in labels:
            color, description = self._STATUS_LABELS[name]
            try:
                subprocess.run(
                    ["gh", "label", "create", name, "--color", color, "--description", description, "--force"],
                    cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                return False, f"Label `{name}` konnte nicht angelegt werden: {e}"
        try:
            result = subprocess.run(
                ["gh", "pr", "edit", pr_url_or_number, *[arg for name in labels for arg in ("--add-label", name)]],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        return result.returncode == 0, (result.stdout + result.stderr).strip()

    def get_repo_slug(self) -> str | None:
        """
        Gibt `owner/repo` des aktuellen GitHub-Remotes zurück (via `gh repo view`), oder None
        bei JEDEM Problem (kein `gh`, kein GitHub-Remote, nicht eingeloggt, …) – Grundlage für
        set_branch_protection() unten, das den Repo-Slug für den API-Pfad braucht.
        """
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        slug = data.get("nameWithOwner")
        return slug or None

    def set_branch_protection(
        self,
        branch: str,
        required_approving_reviews: int = 1,
        required_status_check_contexts: list[str] | None = None,
    ) -> tuple[bool, str]:
        """
        Aktiviert echte GitHub-Branch-Protection für `branch` über die REST-API (`gh api
        --method PUT ... --input -`): Pull-Request-Pflicht mit mindestens
        `required_approving_reviews` Freigaben VOR dem Merge, optional Pflicht-Status-Checks
        (z.B. der CI-Job-Name aus .github/workflows/ci.yml), kein Force-Push, keine Löschung
        des Branches, gilt auch für Repo-Admins (`enforce_admins`).

        Realer struktureller Unterschied zu einem echten Team: der PR-Workflow oben
        (create_branch/create_pull_request) verhindert nur, dass DIESES Tool direkt auf einen
        Hauptbranch pusht – ein Mensch (oder ein anderes Tool/Skript) könnte weiterhin
        `git push origin main` direkt ausführen, ohne dass GitHub selbst das verhindert. Ein
        echtes Team sichert seinen Hauptbranch zusätzlich auf GitHub-Seite selbst ab.

        Erfordert Admin-Rechte auf dem Repo (die verwendete `gh`-Anmeldung muss sie haben) –
        wirft NIE eine Exception, fehlende Rechte/kein Remote/`gh` fehlt liefern
        (False, Fehlermeldung) statt abzubrechen. Bewusst NUR über einen expliziten
        CLI-Befehl (`/protect-branch`) ausgelöst, nie automatisch – eine Änderung an den
        Repo-Einstellungen selbst ist ein bewusster, einmaliger Schritt, kein Seiteneffekt
        eines normalen Team-Laufs.
        """
        repo_slug = self.get_repo_slug()
        if not repo_slug:
            return False, "Kein GitHub-Remote gefunden oder `gh` nicht nutzbar/eingeloggt."

        payload: dict = {
            "required_status_checks": (
                {"strict": True, "contexts": required_status_check_contexts}
                if required_status_check_contexts else None
            ),
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "required_approving_review_count": max(0, required_approving_reviews),
            },
            "restrictions": None,
            "allow_force_pushes": False,
            "allow_deletions": False,
        }
        try:
            result = subprocess.run(
                ["gh", "api", "--method", "PUT", f"repos/{repo_slug}/branches/{branch}/protection",
                 "-H", "Accept: application/vnd.github+json", "--input", "-"],
                input=json.dumps(payload),
                cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        success = result.returncode == 0
        output = (result.stdout + result.stderr).strip()
        return success, output

    def get_pr_status(self, pr_url: str) -> tuple[str, str]:
        """
        Fragt den echten Status eines Pull Requests per `gh pr view <url>` ab – Grundlage für
        core/merge_watcher.py, um Backlog-Tickets (core/backlog_store.py) nach einem echten
        Merge automatisch von "review" auf "done" zu ziehen, statt für immer auf "review"
        hängen zu bleiben. Gibt ("merged"|"closed"|"open", Detail) zurück, oder
        ("unknown", Fehlermeldung) bei JEDEM Problem (gh fehlt, PR nicht mehr auffindbar,
        Netzwerkfehler, kaputtes JSON, ...) – der Aufrufer lässt das Ticket dann einfach
        unverändert, statt einen falschen Status zu erzwingen.
        """
        try:
            result = subprocess.run(
                ["gh", "pr", "view", pr_url, "--json", "state,mergedAt"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return "unknown", str(e)
        if result.returncode != 0:
            return "unknown", (result.stderr or result.stdout).strip()
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return "unknown", "Unerwartete Ausgabe von `gh pr view`."

        state = (data.get("state") or "").upper()  # gh liefert "OPEN"/"CLOSED"/"MERGED"
        if state == "MERGED":
            return "merged", data.get("mergedAt", "")
        if state == "CLOSED":
            return "closed", ""
        if state == "OPEN":
            return "open", ""
        return "unknown", f"Unbekannter PR-Status: '{state}'"

    # ──────────────────────────────────────────
    # Rollback: echter Revert-Workflow für bereits gemergte PRs
    # ──────────────────────────────────────────
    # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: bricht ein gemergter PR den
    # Hauptbranch (z.B. rotes CI erst NACH dem Merge bemerkt, siehe oben), gab es keinerlei
    # Mechanismus, das rückgängig zu machen - nur der manuelle Weg über GitHub selbst. Ein
    # echtes Team hat einen bekannten, schnellen Rollback-Pfad. interface/cli.py._rollback_
    # merged_pr() nutzt die folgenden zwei Methoden dafür (`/rollback <PR-Nummer>`).

    def get_merged_pr_info(self, pr_number: int) -> tuple[bool, str, str]:
        """
        Liest Merge-Commit-SHA und Titel eines PRs per `gh pr view` – Voraussetzung für
        revert_commit(). Ein Revert ergibt nur für einen TATSÄCHLICH gemergten PR Sinn, daher
        (False, Fehlermeldung, "") bei jedem anderen Zustand (offen, geschlossen ohne Merge,
        nicht gefunden, `gh` nicht nutzbar) statt eines falschen Erfolgs.
        """
        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--json", "state,mergeCommit,title"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"gh CLI nicht nutzbar: {e}", ""
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip() or f"PR #{pr_number} nicht gefunden.", ""
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False, "Unerwartete Ausgabe von `gh pr view`.", ""

        state = (data.get("state") or "").upper()
        if state != "MERGED":
            return False, f"PR #{pr_number} ist nicht gemerged (Status: {state or 'unbekannt'}).", ""
        merge_commit = (data.get("mergeCommit") or {}).get("oid") or ""
        if not merge_commit:
            return False, f"PR #{pr_number} hat keinen bekannten Merge-Commit.", ""
        return True, merge_commit, data.get("title", "")

    def revert_commit(self, commit_sha: str) -> tuple[bool, str]:
        """
        Erstellt einen echten `git revert --no-edit <sha>` auf dem AKTUELL ausgecheckten
        Branch – der Aufrufer legt vorher per create_branch() einen eigenen Revert-Branch an
        (siehe interface/cli.py._rollback_merged_pr()), damit der Revert genau wie jede andere
        Änderung über den normalen PR-Workflow läuft statt direkt auf den Hauptbranch
        durchzuschlagen. `--no-edit` übernimmt Gits Standard-Commit-Message
        ('Revert "<ursprüngliche Message>"') unverändert, damit die Herkunft nachvollziehbar
        bleibt. Ein Merge-Konflikt beim Revert selbst (z.B. weil seitdem überlappender Code
        dazukam) ist KEIN Absturz, nur ein Fehlschlag – der Aufrufer bricht dann sauber ab.
        """
        result = subprocess.run(
            ["git", "revert", "--no-edit", commit_sha],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output.strip()

    # ──────────────────────────────────────────
    # Issue-Polling: autonome, getriggerte Läufe (core/issue_watcher.py)
    # ──────────────────────────────────────────
    # Gegenstück zum PR-Workflow oben: nicht nur ein Mensch stößt über die CLI einen Lauf an,
    # sondern ein wiederkehrender Poll-Zyklus (core/issue_watcher.py, aufgerufen über
    # `python main.py --check-issues`) findet eigenständig neue Arbeit über GitHub Issues.

    def list_actionable_issues(self, label: str, exclude_labels: list[str]) -> list[dict]:
        """
        Listet offene Issues mit `label`, die KEINES der `exclude_labels` tragen (z.B.
        bereits in Bearbeitung/erledigt/blockiert) – Grundlage für core/issue_watcher.py, um
        bei jedem Poll-Zyklus nur wirklich neue, noch unbearbeitete Arbeit aufzunehmen.
        Filtert clientseitig, da `gh issue list --label` nur UND-Verknüpfung kennt, keinen
        Ausschluss. Leere Liste bei JEDEM Fehler (kein `gh`, kein Remote, Timeout, kaputtes
        JSON, ...) statt einer Exception – ein Poll-Zyklus soll bei einem vorübergehenden
        Problem beim nächsten Mal einfach erneut versuchen, nicht abstürzen.
        """
        try:
            result = subprocess.run(
                ["gh", "issue", "list", "--label", label, "--state", "open",
                 "--json", "number,title,body,labels", "--limit", "50"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        try:
            issues = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []
        exclude = set(exclude_labels)
        return [
            issue for issue in issues
            if not exclude & {lbl.get("name", "") for lbl in issue.get("labels", [])}
        ]

    def ensure_label_exists(self, name: str, color: str = "ededed", description: str = "") -> None:
        """
        Legt ein GitHub-Label an, falls es im Repo noch nicht existiert – `gh issue edit
        --add-label` schlägt sonst fehl, wenn das Label dort noch nie angelegt wurde. Best
        effort: ignoriert JEDEN Fehler bewusst (Label existiert bereits, keine
        Schreibrechte, `gh` fehlt, ...) – reine Komfort-Vorbereitung, kein kritischer Schritt.
        """
        try:
            subprocess.run(
                ["gh", "label", "create", name, "--color", color,
                 "--description", description, "--force"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def add_issue_label(self, issue_number: int, label: str) -> tuple[bool, str]:
        """Fügt einem Issue ein Label hinzu (Label muss bereits existieren, siehe ensure_label_exists())."""
        return self._gh_issue_edit(issue_number, "--add-label", label)

    def remove_issue_label(self, issue_number: int, label: str) -> tuple[bool, str]:
        """Entfernt ein Label von einem Issue – kein Fehler, wenn es ohnehin nicht gesetzt war."""
        return self._gh_issue_edit(issue_number, "--remove-label", label)

    def _gh_issue_edit(self, issue_number: int, flag: str, label: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["gh", "issue", "edit", str(issue_number), flag, label],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        return result.returncode == 0, (result.stdout + result.stderr).strip()

    def comment_on_issue(self, issue_number: int, body: str) -> tuple[bool, str]:
        """
        Postet einen Kommentar auf ein Issue – die einzige Rückmeldung, die ein Mensch bei
        einem autonom getriggerten Lauf ohne CLI/Dashboard-Ansicht überhaupt zu sehen
        bekommt (Ergebnis, Blockade-Grund, Fehler), siehe core/issue_watcher.py.
        """
        try:
            result = subprocess.run(
                ["gh", "issue", "comment", str(issue_number), "--body", body],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        return result.returncode == 0, (result.stdout + result.stderr).strip()

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
