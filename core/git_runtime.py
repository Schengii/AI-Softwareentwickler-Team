"""
core/git_runtime.py – Nicht-interaktive, zeitbegrenzte Git-Aufrufe

Realer Fund (Framework-Analyse 2026-09-10): agents/github_agent.py (commit/push/stash/checkout/
revert), core/framework_release.py und core/obsidian_sync.py starteten `git` ohne `timeout=` und
ohne `GIT_TERMINAL_PROMPT=0`. Fragt `git push` nach Zugangsdaten (abgelaufenes Token, neuer
Remote) oder öffnet der Git Credential Manager einen Dialog, blockiert der Aufruf unbegrenzt -
in unbeaufsichtigten Läufen (Issue-Watcher, Backlog-Worker) hing damit der gesamte Zyklus.

Dieses Modul bündelt beides an einer Stelle: eine Umgebung, in der Git niemals interaktiv nachfragt,
und einen Aufruf, der bei Timeout/fehlendem Git ein normales Fehlerergebnis statt einer Exception
liefert.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

GIT_COMMAND_TIMEOUT_SECONDS = float(os.getenv("GIT_COMMAND_TIMEOUT_SECONDS", "120"))
# Netzwerkoperationen (push/fetch) dürfen länger dauern als lokale Kommandos.
GIT_NETWORK_TIMEOUT_SECONDS = float(os.getenv("GIT_NETWORK_TIMEOUT_SECONDS", "300"))

GIT_TIMEOUT_EXIT_CODE = 124
GIT_NOT_EXECUTABLE_EXIT_CODE = 127


def non_interactive_git_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Kopie der Umgebung, in der Git weder im Terminal noch per Credential-Manager-Dialog nachfragt -
    fehlende Zugangsdaten führen dann zu einem sofortigen, sichtbaren Fehler statt zu einem Hänger."""
    env = dict(os.environ if base is None else base)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_git(
    args: Sequence[str], cwd: str | Path, timeout: float = GIT_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Führt `git <args>` nicht-interaktiv mit Timeout aus. Wirft nie: Timeout -> returncode 124,
    Git nicht startbar -> returncode 127, jeweils mit deutscher Meldung in `stderr`."""
    command = ["git", *args]
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=non_interactive_git_env(),
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            command, GIT_TIMEOUT_EXIT_CODE, _as_text(e.stdout),
            f"⏱️ `git {' '.join(args[:2])}` nach {timeout:.0f}s abgebrochen (Timeout). Häufige Ursache: "
            "Git wartet auf Zugangsdaten - Credential-Helper/Token prüfen." + _as_text(e.stderr),
        )
    except OSError as e:
        return subprocess.CompletedProcess(
            command, GIT_NOT_EXECUTABLE_EXIT_CODE, "", f"Git konnte nicht gestartet werden: {e}",
        )
