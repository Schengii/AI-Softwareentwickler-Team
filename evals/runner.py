"""
evals/runner.py – Benchmark & Evaluations-Harness für das KI-Softwareentwickler-Team

Ermöglicht automatisierte, wiederholbare Testläufe gegen die kanonischen Benchmark-Aufgaben
(evals/tasks.py). Misst Token-Verbrauch, Ausführungsdauer, Verifikationsergebnis und
erzeugte Dateien, um Versionen des Teams objektiv vergleichen zu können.
"""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from agents.orchestrator import Orchestrator
from core.workspace import WorkspaceManager
from evals.tasks import BENCHMARK_TASKS, BenchmarkTask, get_task, list_tasks
from memory.run_history import record_run

EVALS_HISTORY_FILE = Path(__file__).resolve().parent / "eval_history.json"
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
            f"# 🎯 Benchmark-Bericht: KI-Softwareentwickler-Team",
            f"",
            f"- **Datum / Uhrzeit**: {self.timestamp}",
            f"- **Aufgaben gesamt**: {self.total_tasks}",
            f"- **Bestanden**: {self.passed_tasks} ({self.pass_rate}%)",
            f"- **Gesamt-Tokens**: {self.total_tokens:,}",
            f"- **Gesamtdauer**: {self.total_duration_seconds:.1f}s",
            f"",
            f"## Übersicht",
            f"",
            f"| Task | Kategorie | Status | Verifikation | Dauer | Tokens | Fehlende Dateien |",
            f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in self.results:
            status = "✅ Bestanden" if r.success else "❌ Fehler"
            verif = "✅ Verifiziert" if r.verification_ok else "❌ Nicht verifiziert"
            missing = ", ".join(r.missing_files) if r.missing_files else "-"
            md.append(f"| `{r.slug}` | {r.category} | {status} | {verif} | {r.duration_seconds:.1f}s | {r.total_tokens:,} | {missing} |")

        md.append("")
        return "\n".join(md)


def save_benchmark_result(suite_result: BenchmarkSuiteResult, history_path: Path = EVALS_HISTORY_FILE) -> None:
    """Speichert das Benchmark-Ergebnis in der JSON-Historie."""
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

    start_time = time.monotonic()
    success = False
    verification_ok = False
    total_tokens = 0
    error_msg = ""
    result_text = ""

    try:
        result_text = await orchestrator.process(task.prompt, status_callback=status_callback)
        success = True
        verification_ok = "✅ Verifikation erfolgreich" in result_text or "🧪 Verifikations-Protokoll" in result_text
    except Exception as e:
        error_msg = str(e)
        success = False

    duration = round(time.monotonic() - start_time, 2)

    # Prüfe erwartete Dateien im Projektverzeichnis
    workspace = WorkspaceManager()
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
