"""
core/checkpoint.py – Phasen-Checkpoint für die Fachbereichs-Hierarchie
(agents/orchestrator/department.py).

Anders als core/project_status.py (grobkörniger Checkpoint PRO ABGESCHLOSSENEM process()-Lauf,
für den Wiedereinstieg zwischen kompletten Läufen über das PROJECT_STATE.md/.ai_team_status.json
im Projektordner) hält dieses Modul den FEINKÖRNIGEN Fortschritt INNERHALB eines einzelnen
process()-Laufs fest: welche der Fachbereichs-Phasen (agents/orchestrator/constants.PHASE_ORDER)
bereits abgeschlossen sind, welche Agenten dabei erfolgreich waren, und der Kontext, den die
nächste offene Phase braucht.

Realer Fund (Nutzeranfrage, KI-Team-Härtungsrunde 2026-09-11): Bricht ein Lauf wegen
Provider-Kontingent-Erschöpfung ab (core/provider_exhaustion.py, der "Fast Circuit Breaker" in
department.py), waren bereits geschriebene ADRs/Artefakte zwar auf der Platte erhalten (echte
Dateien überleben jeden Abbruch), aber der NÄCHSTE process()-Aufruf für denselben Projektordner
wusste nichts davon, dass Phase 1 (Planung) und Phase 2 (Design) bereits erfolgreich delegiert
und konsolidiert waren, und ließ den Teamleiter sowie sein Fachteam diese Arbeit komplett neu
anfordern - reiner Tokenverbrauch ohne neuen Erkenntnisgewinn.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CHECKPOINT_FILENAME = ".ai_team_checkpoint.json"


def _checkpoint_path(project_dir: str) -> Path:
    return Path(project_dir) / CHECKPOINT_FILENAME


def load_checkpoint(project_dir: str) -> dict[str, Any] | None:
    """
    Lädt einen gültigen Checkpoint, falls vorhanden.

    Gibt None bei fehlender, kaputter oder strukturell unerwarteter Datei zurück - ein
    beschädigter Checkpoint darf einen Lauf niemals blockieren, er kostet im schlimmsten Fall
    nur den Resume-Vorteil (Verhalten dann identisch zu "kein Checkpoint vorhanden").
    """
    path = _checkpoint_path(project_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("completed_phases"), list):
        return None
    return data


def save_phase_checkpoint(
    project_dir: str,
    completed_phases: list[str],
    successful_agents: list[str],
    running_context: str,
    remaining_phases: list[str],
    aborted: bool = False,
    abort_reason: str = "",
) -> None:
    """
    Speichert den Fortschritt der Fachbereichs-Hierarchie als `.ai_team_checkpoint.json` im
    Projektordner - aufgerufen NACH jedem abgeschlossenen Fachbereich (department.py) sowie
    zusätzlich bei einem provider_exhausted-Abbruch (aborted=True, abort_reason benannt).

    Schreibfehler (z.B. schreibgeschützter Projektordner) werden bewusst verschluckt: der
    Checkpoint ist ein Komfort-/Effizienz-Feature für den nächsten Lauf, darf den aktuellen
    aber nie zum Absturz bringen.
    """
    path = _checkpoint_path(project_dir)
    data = {
        "completed_phases": completed_phases,
        "successful_agents": successful_agents,
        "running_context": running_context,
        "remaining_phases": remaining_phases,
        "aborted": aborted,
        "abort_reason": abort_reason,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def clear_checkpoint(project_dir: str) -> None:
    """
    Entfernt einen bestehenden Checkpoint - aufgerufen, sobald ALLE Fachbereichs-Phasen ohne
    Abbruch durchlaufen wurden, damit ein späterer process()-Aufruf für denselben Projektordner
    (z.B. ein neuer, unabhängiger Folgeauftrag) keinen veralteten Checkpoint wiederverwendet.
    """
    path = _checkpoint_path(project_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
