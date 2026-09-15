"""
evals/runner.py – Benchmark & Evaluations-Harness für das KI-Softwareentwickler-Team

Ermöglicht automatisierte, wiederholbare Testläufe gegen die kanonischen Benchmark-Aufgaben
(evals/tasks.py). Misst Token-Verbrauch, Ausführungsdauer, Verifikationsergebnis und
erzeugte Dateien, um Versionen des Teams objektiv vergleichen zu können.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from agents.orchestrator import Orchestrator
from core.telemetry_hygiene import should_skip_real_write
from core.workspace import WorkspaceManager
from evals.tasks import BenchmarkTask, get_task, list_tasks

EVALS_HISTORY_FILE = Path(__file__).resolve().parent / "eval_history.json"
_REAL_EVALS_HISTORY_FILE = EVALS_HISTORY_FILE
StatusCallback = Callable[[str], None]


@dataclass
class BenchmarkTaskResult:
    """Ergebnis eines einzelnen Benchmark-Task-Laufs."""
    slug: str
    name: str
    category: str
    success: bool
    verification_ok: bool
    duration_seconds: float
    total_tokens: int
    missing_files: list[str] = field(default_factory=list)
    found_files: list[str] = field(default_factory=list)
    error: str = ""
    summary: str = ""
    # Strukturierte Details für das Regressions-Gate (evals/gate.py): welche Prüfungen scheiterten
    # und ob die Definition of Done erfüllt war.
    failed_checks: list[str] = field(default_factory=list)
    dod_done: bool = False


@dataclass
class BenchmarkSuiteResult:
    """Gesamtergebnis eines Benchmark-Durchlaufs."""
    timestamp: str
    total_tasks: int
    passed_tasks: int
    total_tokens: int
    total_duration_seconds: float
    results: list[BenchmarkTaskResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return round((self.passed_tasks / self.total_tasks * 100), 1) if self.total_tasks > 0 else 0.0

    def format_terminal_table(self) -> str:
        """Erzeugt eine kompakte ASCII-Tabelle für die Konsole."""
        lines = [
            "=" * 80,
            f"🎯 BENCHMARK-ERGEBNISSE ({self.timestamp})",
            f"Erfolgsquote: {self.passed_tasks}/{self.total_tasks} ({self.pass_rate}%) | Tokens: {self.total_tokens:,} | Dauer: {self.total_duration_seconds:.1f}s",
            "-" * 80,
            f"{'Task':<22} | {'Kategorie':<10} | {'Status':<8} | {'Verifiziert':<11} | {'Dauer':<7} | {'Tokens':<8}",
            "-" * 80,
        ]
        for r in self.results:
            status_sym = "✅ OK" if r.success else "❌ FEHLER"
            verif_sym = "✅ JA" if r.verification_ok else "❌ NEIN"
            lines.append(
                f"{r.slug:<22} | {r.category:<10} | {status_sym:<8} | {verif_sym:<11} | {r.duration_seconds:>5.1f}s | {r.total_tokens:>8,}"
            )
        lines.append("=" * 80)
        return "\n".join(lines)

    def format_markdown_report(self) -> str:
        """Erzeugt einen ausführlichen Markdown-Bericht."""
        md = [
            "# 🎯 Benchmark-Bericht: KI-Softwareentwickler-Team",
            "",
            f"- **Datum / Uhrzeit**: {self.timestamp}",
            f"- **Aufgaben gesamt**: {self.total_tasks}",
            f"- **Bestanden**: {self.passed_tasks} ({self.pass_rate}%)",
            f"- **Gesamt-Tokens**: {self.total_tokens:,}",
            f"- **Gesamtdauer**: {self.total_duration_seconds:.1f}s",
            "",
            "## Übersicht",
            "",
            "| Task | Kategorie | Status | Verifikation | Dauer | Tokens | Fehlende Dateien |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in self.results:
            status = "✅ Bestanden" if r.success else "❌ Fehler"
            verif = "✅ Verifiziert" if r.verification_ok else "❌ Nicht verifiziert"
            missing = ", ".join(r.missing_files) if r.missing_files else "-"
            md.append(f"| `{r.slug}` | {r.category} | {status} | {verif} | {r.duration_seconds:.1f}s | {r.total_tokens:,} | {missing} |")

        md.append("")
        return "\n".join(md)


def save_benchmark_result(suite_result: BenchmarkSuiteResult, history_path: Path | None = None) -> None:
    """Speichert das Benchmark-Ergebnis in der JSON-Historie.

    Der Pfad wird erst beim Aufruf aufgelöst: als Default-Argument (`= EVALS_HISTORY_FILE`) war er
    bereits beim Import gebunden - ein Test, der `evals.runner.EVALS_HISTORY_FILE` patcht, schrieb
    dadurch trotzdem Fake-Ergebnisse in die echte Historie und verfälschte das Eval-Gate.
    """
    history_path = Path(history_path) if history_path is not None else EVALS_HISTORY_FILE
    if should_skip_real_write(history_path, _REAL_EVALS_HISTORY_FILE):
        return
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

    history.append(asdict(suite_result))
    # Behalte maximal die letzten 50 Benchmark-Läufe
    if len(history) > 50:
        history = history[-50:]

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def _archive_previous_project(
    workspace: WorkspaceManager, project_name: str, status_callback: StatusCallback | None = None,
) -> None:
    """
    Benennt ein bereits existierendes Benchmark-Projektverzeichnis vor dem Lauf um, damit die
    Datei-Existenzprüfung ausschließlich das misst, was DIESER Lauf erzeugt hat.

    Bewusst umbenennen statt löschen: Ein Benchmark darf nie Arbeit vernichten, falls jemand
    versehentlich einen echten Projektnamen als `expected_project_name` einträgt. Das Archiv
    trägt einen Zeitstempel und bleibt zur Nachanalyse erhalten. Fehler beim Umbenennen (z.B.
    ein unter Windows noch offener Datei-Handle) dürfen den Benchmark nicht abbrechen - dann
    läuft die Prüfung wie bisher gegen das bestehende Verzeichnis, was allenfalls zu optimistisch
    misst, aber keinen Lauf verliert.
    """
    try:
        project_dir = workspace.get_project_dir(project_name)
    except Exception:
        return
    if not project_dir.exists():
        return
    archive_dir = project_dir.with_name(f"{project_dir.name}__eval_archiv_{datetime.now():%Y%m%d_%H%M%S}")
    try:
        project_dir.rename(archive_dir)
        if status_callback:
            status_callback(f"🧹 Vorheriges Benchmark-Verzeichnis archiviert nach `{archive_dir.name}`")
    except OSError as e:
        if status_callback:
            status_callback(
                f"⚠️ Benchmark-Verzeichnis `{project_dir.name}` konnte nicht archiviert werden "
                f"({e}) – die Datei-Prüfung kann dadurch Ergebnisse eines früheren Laufs mitzählen."
            )


async def run_single_task(
    task: BenchmarkTask,
    orchestrator: Orchestrator | None = None,
    status_callback: StatusCallback | None = None,
) -> BenchmarkTaskResult:
    """Führt eine einzelne Benchmark-Aufgabe aus und prüft die Erwartungen."""
    if orchestrator is None:
        orchestrator = Orchestrator()

    if status_callback:
        status_callback(f"🚀 Starte Benchmark-Task: {task.name} ({task.slug})...")

    # Frisches Verzeichnis erzwingen (realer Fund, KI-Team-Masterplan-Analyse): Die
    # Datei-Existenzprüfung unten lief gegen ein Verzeichnis, das zwischen Benchmark-Läufen
    # NICHT geleert wurde. Dateien aus einem früheren, erfolgreichen Lauf ließen damit einen
    # späteren, gescheiterten Lauf bestehen - der Benchmark maß also teilweise die Vergangenheit.
    workspace = WorkspaceManager()
    _archive_previous_project(workspace, task.expected_project_name, status_callback)

    start_time = time.monotonic()
    success = False
    verification_ok = False
    total_tokens = 0
    error_msg = ""
    result_text = ""
    failed_checks: list[str] = []
    dod_done = False

    try:
        result_text = await orchestrator.process(task.prompt, status_callback=status_callback)
        success = True
        # Realer Fund: Hier stand zuvor ein Substring-Match auf dem Report-TEXT:
        #   verification_ok = "✅ Verifikation erfolgreich" in result_text
        #                     or "🧪 Verifikations-Protokoll" in result_text
        # Der zweite Marker steht aber in JEDEM Verifikationsbericht - auch in gescheiterten
        # (belegt in workspace/event_ticket_api/.ai_team_status.json: `verification_ok: false`
        # bei gleichzeitig vorhandenem "### 🧪 Verifikations-Protokoll"). Dadurch war
        # `verification_ok` praktisch immer True und der Benchmark konnte strukturell nicht
        # durchfallen: 50 von 50 aufgezeichneten Läufen "bestanden". Jetzt wird das
        # STRUKTURIERTE Ergebnis des Orchestrators gelesen, nie wieder Report-Prosa geparst.
        verification_ok = bool(getattr(orchestrator, "last_verification_ok", False))
        outcome = getattr(orchestrator, "last_verification_outcome", None)
        failed_checks = list(getattr(outcome, "failed_checks", []) or []) if outcome is not None else []
        dod = getattr(orchestrator, "last_definition_of_done", None)
        dod_done = bool(getattr(dod, "is_done", False)) if dod is not None else False
        # `total_tokens` wurde zuvor mit 0 initialisiert und NIE zugewiesen - jeder
        # Benchmark-Report wies deshalb 0 Tokens aus (die Kennzahl war tot).
        total_tokens = sum(
            getattr(r, "total_tokens", 0) or 0
            for r in (getattr(orchestrator, "last_agent_results", None) or [])
        )
    except Exception as e:
        error_msg = str(e)
        success = False

    duration = round(time.monotonic() - start_time, 2)

    # Prüfe erwartete Dateien im Projektverzeichnis
    project_dir = workspace.get_project_dir(task.expected_project_name)
    found_files = []
    missing_files = []

    if project_dir.exists():
        for expected in task.expected_files:
            target = project_dir / expected
            if target.exists():
                found_files.append(expected)
            else:
                missing_files.append(expected)
    else:
        missing_files = list(task.expected_files)

    # Wenn essenzielle Dateien fehlen, gilt der Task nicht als vollständig bestanden
    if missing_files:
        success = False

    return BenchmarkTaskResult(
        slug=task.slug,
        name=task.name,
        category=task.category,
        success=success,
        verification_ok=verification_ok,
        duration_seconds=duration,
        total_tokens=total_tokens,
        missing_files=missing_files,
        found_files=found_files,
        error=error_msg,
        summary=result_text[:300] if result_text else error_msg,
        failed_checks=[str(c) for c in failed_checks],
        dod_done=dod_done,
    )


async def run_benchmark(
    task_slugs: list[str] | None = None,
    orchestrator: Orchestrator | None = None,
    status_callback: StatusCallback | None = None,
    save_history: bool = True,
) -> BenchmarkSuiteResult:
    """
    Führt die ausgewählten (oder alle) Benchmark-Aufgaben aus und liefert ein Gesamtergebnis.
    """
    tasks_to_run: list[BenchmarkTask] = []
    if task_slugs:
        for s in task_slugs:
            tasks_to_run.append(get_task(s))
    else:
        tasks_to_run = list_tasks()

    suite_start = time.monotonic()
    results: list[BenchmarkTaskResult] = []

    for task in tasks_to_run:
        # Frische Orchestrator-Instanz pro Task
        orch = orchestrator or Orchestrator()
        task_res = await run_single_task(task, orchestrator=orch, status_callback=status_callback)
        results.append(task_res)

    total_duration = round(time.monotonic() - suite_start, 2)
    passed_tasks = sum(1 for r in results if r.success and r.verification_ok)
    total_tokens = sum(r.total_tokens for r in results)

    suite_result = BenchmarkSuiteResult(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_tasks=len(results),
        passed_tasks=passed_tasks,
        total_tokens=total_tokens,
        total_duration_seconds=total_duration,
        results=results,
    )

    if save_history:
        save_benchmark_result(suite_result)

    return suite_result
