"""
core/framework_revision.py – Welche Framework-Codeversion führt einen Lauf gerade aus?

Realer Fund (Analyse auditlog_sentinel, 2026-09-10): Commit `66ab8c0` führte um 14:40 Uhr eine
Modell-Mindeststufe für kritische Rollen ein. Der Lauf um 15:20 Uhr lief trotzdem komplett auf
`gemini-3.1-flash-lite` – die interaktive CLI war schon seit dem Vormittag gestartet und führte
noch den ALTEN, beim Prozessstart importierten Code aus. Weder das Lauf-Log noch die Konsole
verrieten das; die Analyse musste es mühsam über Zeitstempel rekonstruieren.

Dieses Modul liefert deshalb
- den Git-Commit samt Dirty-Flag (für `run_started` im Lauf-Log) und
- einen günstigen Fingerabdruck der Framework-Quelldateien (Pfad, mtime, Größe), mit dem ein
  langlebiger Prozess erkennt, dass sein geladener Code nicht mehr dem auf der Platte entspricht.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_DIRS: tuple[str, ...] = ("agents", "core", "interface", "memory")
_SOURCE_FILES: tuple[str, ...] = ("config.py", "main.py")
_GIT_PATHSPECS: tuple[str, ...] = ("agents", "core", "interface", "memory/*.py", "config.py", "main.py")
_GIT_TIMEOUT_SECONDS = 5.0
UNKNOWN_COMMIT = "unbekannt"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameworkRevision:
    """Momentaufnahme der Framework-Codeversion."""
    commit: str
    dirty: bool
    fingerprint: str

    def label(self) -> str:
        return f"{self.commit}{' (+ lokale Änderungen)' if self.dirty else ''}"


def _iter_source_files(root: Path) -> Iterator[Path]:
    for name in _SOURCE_FILES:
        candidate = root / name
        if candidate.is_file():
            yield candidate
    for directory in _SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in filenames:
                if filename.endswith(".py"):
                    yield Path(dirpath) / filename


def source_fingerprint(root: Path = FRAMEWORK_ROOT) -> str:
    """Hash über Pfad, Änderungszeit und Größe aller Framework-Quelldateien (kein Dateiinhalt –
    läuft in wenigen Millisekunden und kann deshalb vor jeder Aufgabe geprüft werden)."""
    digest = hashlib.sha256()
    for path in sorted(_iter_source_files(root)):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{path.relative_to(root).as_posix()}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
    return digest.hexdigest()[:16]


def _git(args: list[str], root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("git %s fehlgeschlagen: %r", " ".join(args), e)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


_revision_cache: dict[str, FrameworkRevision] = {}


def current_revision(root: Path = FRAMEWORK_ROOT) -> FrameworkRevision:
    """Commit, Dirty-Flag (nur Framework-Quellcode, keine Lauf-Daten) und Fingerabdruck.

    Die zwei git-Aufrufe werden pro Fingerabdruck gecacht – unveränderter Quellcode braucht bei
    jedem weiteren Lauf keinen neuen Subprozess. Ein reiner Commit ohne Dateiänderung ändert den
    Fingerabdruck nicht; der zwischengespeicherte Commit kann dann bis zur nächsten Dateiänderung
    veralten, was für den Zweck (welcher Code lief?) unerheblich ist."""
    fingerprint = source_fingerprint(root)
    cache_key = f"{root}:{fingerprint}"
    cached = _revision_cache.get(cache_key)
    if cached is not None:
        return cached
    commit = _git(["rev-parse", "--short=12", "HEAD"], root) or UNKNOWN_COMMIT
    status = _git(["status", "--porcelain", "--untracked-files=no", "--", *_GIT_PATHSPECS], root)
    revision = FrameworkRevision(commit=commit, dirty=bool(status), fingerprint=fingerprint)
    _revision_cache.clear()
    _revision_cache[cache_key] = revision
    return revision
