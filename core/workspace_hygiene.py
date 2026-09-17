"""
core/workspace_hygiene.py – Smarte Speicher- und Artefakt-Hygiene für den Workspace.

Realer Befund (2026-09-16): Der Ordner `workspace/` enthielt über 98.000 Dateien und belegte
mehr als 1,5 GB Speicherplatz auf der Festplatte. Fast 95 % dieses Volumens stammten nicht aus
geschriebenem Quellcode, sondern aus temporären virtuellen Python-Umgebungen (`.ai_team_venv`),
Node.js-Abhängigkeiten (`node_modules`), Build-Ausgaben (`dist`, `build`) und Test-Caches
(`.pytest_cache`).

Dieses Modul implementiert "Option 1" der Workspace-Hygiene:
- Der geschriebene Quellcode, Tests, Dokumentationen und Git-Dateien bleiben IMMER unangetastet.
- Liegt die letzte Dateiänderung in einem Workspace-Projekt länger als `max_age_days` (Standard: 7 Tage)
  zurück, werden nur die schweren, jederzeit reproduzierbaren Artefakt-Ordner gelöscht:
    * `.ai_team_venv`
    * `node_modules`
    * `.pytest_cache`
    * `.ruff_cache`
    * `dist`
    * `build`
- Braucht das KI-Team das Projekt später wieder, baut der Verifier die Umgebung bei Bedarf automatisch
  wieder auf (`ProjectVerifier.ensure_environment()`).
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import WORKSPACE_DIR

# Verzeichnisse, die gefahrlos entfernt werden können, da sie reine Build-/Laufzeit-Artefakte sind
PRUNABLE_DIR_NAMES = frozenset({
    ".ai_team_venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "__pycache__",
})


@dataclass
class ProjectPruneResult:
    """Ergebnis der Bereinigung eines einzelnen Projekts."""
    project_name: str
    removed_dirs: list[str] = field(default_factory=list)
    freed_bytes: int = 0
    error: str = ""


@dataclass
class WorkspaceHygieneReport:
    """Gesamtergebnis eines Hygiene-Durchlaufs."""
    scanned_projects: int = 0
    pruned_projects: int = 0
    total_freed_bytes: int = 0
    results: list[ProjectPruneResult] = field(default_factory=list)

    def format_summary(self) -> str:
        mb = self.total_freed_bytes / (1024 * 1024)
        if self.pruned_projects == 0:
            return f"🧹 Workspace-Hygiene: {self.scanned_projects} Projekt(e) geprüft – keine veralteten Artefakte gefunden (0 MB freigegeben)."
        details = [
            f"  • {r.project_name}: {len(r.removed_dirs)} Ordner entfernt ({r.freed_bytes / (1024 * 1024):.1f} MB)"
            for r in self.results if r.removed_dirs
        ]
        return (
            f"🧹 Workspace-Hygiene:\n"
            f"  - {self.scanned_projects} Projekt(e) gescannt\n"
            f"  - {self.pruned_projects} Projekt(e) bereinigt\n"
            f"  - {mb:.1f} MB Speicherplatz freigegeben\n"
            + "\n".join(details)
        )


def _get_project_mtime(project_dir: Path) -> float:
    """Ermittelt den jüngsten Änderungszeitpunkt echter Quell-Dateien im Projekt
    (ignoriert dabei die zu löschenden Artefakt-Ordner wie .ai_team_venv/node_modules)."""
    latest = project_dir.stat().st_mtime
    try:
        for entry in project_dir.iterdir():
            if entry.name in PRUNABLE_DIR_NAMES or entry.name.startswith(".git"):
                continue
            if entry.is_file():
                mtime = entry.stat().st_mtime
                if mtime > latest:
                    latest = mtime
            elif entry.is_dir():
                try:
                    for sub in entry.rglob("*"):
                        if any(part in PRUNABLE_DIR_NAMES or part.startswith(".git") for part in sub.parts):
                            continue
                        try:
                            mtime = sub.stat().st_mtime
                            if mtime > latest:
                                latest = mtime
                        except OSError:
                            continue
                except OSError:
                    continue
    except OSError:
        pass
    return latest


def _calc_dir_size(dir_path: Path) -> int:
    """Berechnet die Größe eines Verzeichnisses in Bytes."""
    total = 0
    try:
        for entry in dir_path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def prune_project_artifacts(project_dir: Path, max_age_days: float = 7.0, dry_run: bool = False) -> ProjectPruneResult:
    """Bereinigt Artefakt-Ordner in einem Projekt, wenn es älter als `max_age_days` ist."""
    result = ProjectPruneResult(project_name=project_dir.name)
    if not project_dir.is_dir():
        return result

    # Schutzmarkierung: Datei `.keep` verhindert automatische Bereinigung
    if (project_dir / ".keep").exists():
        return result

    now = time.time()
    cutoff = now - (max_age_days * 86400.0)
    last_modified = _get_project_mtime(project_dir)

    # Projekt wurde innerhalb des Zeitfensters aktiv bearbeitet -> nicht bereinigen
    if last_modified > cutoff:
        return result

    for entry in project_dir.iterdir():
        if entry.is_dir() and entry.name in PRUNABLE_DIR_NAMES:
            dir_size = _calc_dir_size(entry)
            result.freed_bytes += dir_size
            result.removed_dirs.append(entry.name)
            if not dry_run:
                try:
                    shutil.rmtree(entry, ignore_errors=True)
                except OSError as e:
                    result.error = f"Konnte {entry.name} nicht löschen: {e}"

    return result


def run_workspace_hygiene(
    workspace_dir: str | Path | None = None,
    max_age_days: float = 7.0,
    dry_run: bool = False,
) -> WorkspaceHygieneReport:
    """
    Scannt alle Projekte in `workspace/` und bereinigt schwere Build-Artefakte (.ai_team_venv, node_modules),
    wenn das Projekt seit mehr als `max_age_days` Tagen nicht mehr geändert wurde.
    """
    base = Path(workspace_dir) if workspace_dir else Path(WORKSPACE_DIR)
    report = WorkspaceHygieneReport()
    if not base.is_dir():
        return report

    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return report

    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        report.scanned_projects += 1
        res = prune_project_artifacts(entry, max_age_days=max_age_days, dry_run=dry_run)
        if res.removed_dirs:
            report.pruned_projects += 1
            report.total_freed_bytes += res.freed_bytes
            report.results.append(res)

    return report
