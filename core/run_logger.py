"""
core/run_logger.py – Strukturiertes, persistentes Lauf-Protokoll (JSONL)

Realer Fund (KI-Team-Masterplan-Analyse, 09.09.2026): Das Verzeichnis `logs/` war vollständig
leer, und in `core/`, `agents/`, `interface/` sowie `main.py` gab es KEIN einziges
`logging.basicConfig` und keinen `FileHandler`. Die gesamte Diagnose lief über die
rich-Konsolenausgabe – die nach dem Schließen des Terminals weg ist.

Für ein Framework, das ausdrücklich autonom im Hintergrund arbeiten soll (`--work-backlog`,
`core/issue_watcher.py`, `core/production_monitor.py`, `core/merge_watcher.py`), ist das der
größte blinde Fleck: Scheiterte ein nächtlicher Lauf, gab es hinterher nichts zu untersuchen.

Zwei Artefakte pro Lauf:

1. `logs/runs/<zeitstempel>_<slug>.jsonl` – eine Zeile je Ereignis. Für Agenten-Aufrufe wird
   bewusst BEIDES festgehalten: das angeforderte UND das tatsächlich antwortende Modell. Genau
   diese Unterscheidung fehlte bisher überall und war die Ursache dafür, dass 160
   Kontingent-Ausfälle als Qualitätsmängel von `claude-sonnet-5` gezählt wurden, obwohl über
   dieses Modell nie ein Call lief (siehe core/provider_exhaustion.py.classify_failure).

2. `logs/verification/<zeitstempel>_<slug>.log` – die ROHE Ausgabe der Verifikationsläufe
   (pip/pytest/npm, stdout+stderr). In den Bericht wandert nur eine gekürzte Zusammenfassung;
   die eigentliche Fehlermeldung, die ein Mensch zum Debuggen braucht, ging bisher verloren.

Grundsatz (wie core/project_status.py und memory/run_history.py): Protokollierung ist rein
additiv. Ein I/O-Fehler beim Schreiben darf einen sonst erfolgreichen Lauf NIEMALS zum
Scheitern bringen – jede öffentliche Methode schluckt ihre Fehler.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import BASE_DIR
from core.run_trace import append_trace_event, prune_run_artifacts, trace_path

LOGS_DIR = Path(BASE_DIR) / "logs"
RUN_LOGS_DIR = LOGS_DIR / "runs"
VERIFICATION_LOGS_DIR = LOGS_DIR / "verification"

# Aufbewahrung: begrenzt auf die jüngsten Läufe UND ein Höchstalter. Ohne beides wächst das
# Verzeichnis über viele Sitzungen unbegrenzt (dasselbe Problem, das MAX_RUNS_KEPT in
# memory/run_history.py löst).
MAX_RUN_LOGS_KEPT = int(os.getenv("MAX_RUN_LOGS_KEPT", "200"))
MAX_RUN_LOG_AGE_DAYS = int(os.getenv("MAX_RUN_LOG_AGE_DAYS", "30"))

# Rohausgaben einzelner Verifikationsschritte können sehr groß werden (ein fehlgeschlagener
# `pip install` mit vollem Resolver-Backtracking erzeugt Megabytes). Pro Eintrag gedeckelt,
# damit das Log als Diagnosewerkzeug handhabbar bleibt.
MAX_VERIFICATION_CHARS_PER_ENTRY = int(os.getenv("MAX_VERIFICATION_CHARS_PER_ENTRY", "200000"))

_SLUG_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_slug(slug: str) -> str:
    """Reduziert einen Projekt-Slug auf dateisystemsichere Zeichen (Windows-tauglich)."""
    cleaned = _SLUG_SAFE_RE.sub("_", (slug or "").strip()).strip("_")
    return cleaned[:60] or "unbenannt"


class RunLogger:
    """
    Schreibt das strukturierte Protokoll EINES Laufs. Bewusst kein globaler Singleton: Das
    Framework kann mehrere Läufe nebeneinander ausführen (Dashboard-Jobs, Backlog-Worker), und
    jeder soll seine eigene, klar zuordenbare Datei bekommen.

    Nutzung::

        logger = RunLogger(project_slug="notes_api")
        logger.log_event("run_started", task="…")
        logger.log_agent_result(result, requested_model="claude-sonnet-5")
        logger.log_verification_output("pytest", exit_code=1, output=raw_stdout)
        logger.log_event("run_finished", verification_ok=False)
    """

    def __init__(self, project_slug: str = "", *, enabled: bool = True, project_dir: str | Path | None = None) -> None:
        self.project_slug = project_slug or "unbenannt"
        self.started_at = datetime.now(UTC)
        self.enabled = enabled
        self._sequence = 0
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        self.stamp = stamp
        name = f"{stamp}_{_safe_slug(self.project_slug)}"
        self.run_log_path = RUN_LOGS_DIR / f"{name}.jsonl"
        self.verification_log_path = VERIFICATION_LOGS_DIR / f"{name}.log"
        # Zusätzlich projektlokal und versioniert (core/run_trace.py) - logs/ ist gitignored und
        # auf jedem anderen Rechner (CI, Backlog-Worker) nicht verfügbar.
        self.project_dir = Path(project_dir) if project_dir else None
        self.project_trace_path = trace_path(self.project_dir, stamp) if self.project_dir else None
        self._verification_started = False
        self.closed = False
        if self.enabled:
            self._prepare_directories()

    # ── Öffentliche API ───────────────────────────────────────────────────────────────────

    def log_event(self, event: str, **fields: Any) -> None:
        """Schreibt ein beliebiges Lauf-Ereignis als eine JSONL-Zeile."""
        self._write({"event": event, **fields})

    def log_agent_result(self, result: Any, requested_model: str = "") -> None:
        """
        Protokolliert das Ergebnis EINES Agenten-Aufrufs (core/message_bus.py.AgentResult).

        `requested_model` ist das laut config.py für die Rolle KONFIGURIERTE Modell,
        `effective_model` das, welches tatsächlich geantwortet hat. Weichen beide voneinander
        ab, hat ein Fallback-Hop stattgefunden – dieser Unterschied ist der wichtigste einzelne
        Diagnosewert im ganzen Log und war zuvor nirgends festgehalten.
        """
        from core.llm_factory import is_same_model

        effective_model = getattr(result, "model_used", "") or ""
        entry: dict[str, Any] = {
            "event": "agent_call",
            "agent_id": getattr(result, "agent_id", ""),
            "agent_name": getattr(result, "agent_name", ""),
            "success": bool(getattr(result, "success", False)),
            "requested_model": requested_model,
            "effective_model": effective_model,
            # Kanonischer Vergleich: Die Provider-Wrapper entfernen ihr Präfix beim Anlegen, das
            # angeforderte Modell trägt es aber noch ("openai/gpt-oss-120b" vs.
            # "groq:openai/gpt-oss-120b"). Ein direkter Vergleich meldete deshalb bei JEDEM
            # Groq-/OpenRouter-/DeepSeek-Aufruf fälschlich eine Abwertung.
            "model_downgraded": bool(
                requested_model and effective_model and not is_same_model(requested_model, effective_model)
            ),
            "prompt_tokens": getattr(result, "prompt_tokens", 0),
            "completion_tokens": getattr(result, "completion_tokens", 0),
            "total_tokens": getattr(result, "total_tokens", 0),
            "duration_seconds": round(getattr(result, "duration_seconds", 0.0) or 0.0, 2),
            "tool_calls_count": getattr(result, "tool_calls_count", 0),
            "files_written": list(getattr(result, "files_written", []) or []),
        }
        watchdog_events = list(getattr(result, "watchdog_events", []) or [])
        if watchdog_events:
            entry["watchdog_events"] = watchdog_events
        compacted = getattr(result, "context_chars_compacted", 0) or 0
        if compacted:
            entry["context_chars_compacted"] = compacted
        if not entry["success"]:
            entry["failure_class"] = getattr(result, "failure_class", "") or ""
            error = getattr(result, "error", None)
            # Fehlermeldungen einzelner Provider können ganze JSON-Bodies enthalten - für die
            # Diagnose reicht der Anfang, der die Ursache trägt.
            entry["error"] = (str(error)[:2000] if error else "")
        self._write(entry)

    def log_verification_output(
        self, step: str, output: str, exit_code: int | None = None,
    ) -> None:
        """
        Hängt die ROHE Ausgabe eines Verifikationsschritts (pip/pytest/npm/ruff …) an das
        Verifikations-Log an und vermerkt im JSONL-Lauf-Log, dass sie dort zu finden ist.
        """
        if not self.enabled:
            return
        text = output or ""
        truncated = len(text) > MAX_VERIFICATION_CHARS_PER_ENTRY
        if truncated:
            text = text[:MAX_VERIFICATION_CHARS_PER_ENTRY] + "\n… [gekürzt] …\n"
        header = (
            f"\n{'=' * 78}\n"
            f"# Schritt: {step}\n"
            f"# Zeit:    {datetime.now(UTC).isoformat(timespec='seconds')}\n"
            f"# Exit:    {exit_code if exit_code is not None else 'n/a'}\n"
            f"{'=' * 78}\n"
        )
        try:
            self.verification_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.verification_log_path.open("a", encoding="utf-8") as fh:
                fh.write(header)
                fh.write(text)
                if not text.endswith("\n"):
                    fh.write("\n")
            self._verification_started = True
        except OSError:
            return
        self._write({
            "event": "verification_step",
            "step": step,
            "exit_code": exit_code,
            "output_chars": len(output or ""),
            "output_truncated": truncated,
            "raw_log": str(self.verification_log_path),
        })

    def close(self, **fields: Any) -> None:
        """Schließt den Lauf ab und räumt alte Log-Dateien auf. Idempotent: ein zweiter Aufruf
        (z.B. die Absicherung in Orchestrator.process()) schreibt keine doppelte Abschlusszeile."""
        if self.closed:
            return
        self.closed = True
        self._write({
            "event": "run_closed",
            "duration_seconds": round((datetime.now(UTC) - self.started_at).total_seconds(), 1),
            **fields,
        })
        prune_old_logs()
        if self.project_dir is not None:
            prune_run_artifacts(self.project_dir)

    # ── Interna ───────────────────────────────────────────────────────────────────────────

    def _prepare_directories(self) -> None:
        try:
            RUN_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            VERIFICATION_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Kein schreibbares Log-Verzeichnis: Protokollierung still abschalten, statt jeden
            # weiteren Aufruf scheitern zu lassen. Der Lauf selbst ist wichtiger als sein Log.
            self.enabled = False

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._sequence += 1
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "seq": self._sequence,
            "project_slug": self.project_slug,
            **payload,
        }
        if self.project_trace_path is not None:
            append_trace_event(self.project_trace_path, record)
        try:
            with self.run_log_path.open("a", encoding="utf-8") as fh:
                # default=str: Ein einzelnes nicht serialisierbares Feld (z.B. ein Path) darf
                # nie die gesamte Protokollzeile verlieren.
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except (OSError, TypeError, ValueError):
            return


def prune_old_logs(
    max_files: int = MAX_RUN_LOGS_KEPT, max_age_days: int = MAX_RUN_LOG_AGE_DAYS,
) -> int:
    """
    Entfernt Lauf- und Verifikations-Logs, die älter als `max_age_days` sind oder über die
    jüngsten `max_files` hinausgehen. Gibt die Anzahl gelöschter Dateien zurück.

    Läuft rein defensiv: Eine Datei, die gerade von einem parallelen Lauf beschrieben wird oder
    unter Windows gesperrt ist, wird übersprungen statt einen Fehler auszulösen.
    """
    removed = 0
    cutoff = time.time() - max_age_days * 86400
    for directory, suffix in ((RUN_LOGS_DIR, ".jsonl"), (VERIFICATION_LOGS_DIR, ".log")):
        if not directory.exists():
            continue
        try:
            files = sorted(
                (p for p in directory.iterdir() if p.is_file() and p.suffix == suffix),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            continue
        surplus = files[: max(0, len(files) - max_files)]
        for path in files:
            try:
                too_old = path.stat().st_mtime < cutoff
            except OSError:
                continue
            if path in surplus or too_old:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
    return removed
