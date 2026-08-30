"""
core/deployment_status.py – Persistenter Live-Deployment-Zustand pro Projekt

Realer Fund: core/cloud_deployment.py.CloudDeploymentManager.deploy() liefert eine echte
Preview-URL zurück, aber diese ging bisher spurlos verloren, sobald der aufrufende Prozess
endete - es gab keine Möglichkeit, SPÄTER (z.B. in einem eigenen Poll-Zyklus, siehe
core/production_monitor.py) erneut nachzusehen, ob ein bereits deploytes Projekt noch
erreichbar ist. Ein echtes Team hat dafür ein Monitoring-Dashboard mit dem zuletzt bekannten
Live-Status jedes Deployments - dieses Modul ist die minimale, dateibasierte Variante davon.

Schreibt/liest eine kompakte JSON-Datei DIREKT im Projektverzeichnis (dieselbe Konvention wie
core/project_status.py), bewusst ABER gitignored (siehe .gitignore): anders als die Lauf-
Historie ist dies reiner, sich ständig ändernder LAUFZEIT-Zustand (jeder Health-Check
überschreibt ihn), keine append-only Historie mit eigenem Wert für spätere Sitzungen.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

DEPLOYMENT_STATUS_FILENAME = ".ai_team_deployment.json"


def _status_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / DEPLOYMENT_STATUS_FILENAME


def record_deployment(project_dir: str | Path, provider: str, url: str) -> None:
    """Speichert (überschreibt) den Deployment-Zustand nach einem echten `/deploy-cloud`-Lauf.
    Setzt den Health-Check-Teil bewusst zurück - ein frisch deploytes Projekt hat noch keine
    Prüfung hinter sich."""
    data = {
        "provider": provider,
        "url": url,
        "deployed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_check_at": "",
        "last_check_healthy": None,
        "last_check_detail": "",
    }
    try:
        _status_path(project_dir).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # rein additiv wie core/project_status.py - ein I/O-Fehler darf den Deploy-Lauf nicht scheitern lassen


def read_deployment(project_dir: str | Path) -> dict | None:
    """None, wenn dieses Projekt noch nie per `/deploy-cloud` deployt wurde ODER die Datei
    beschädigt ist (kein Crash) - core/production_monitor.py überspringt es dann einfach."""
    path = _status_path(project_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def record_health_check(project_dir: str | Path, healthy: bool, detail: str) -> None:
    """Aktualisiert NUR den Health-Check-Teil eines bereits bestehenden Deployment-Zustands -
    kein Effekt, wenn nie deployt wurde (nichts zu aktualisieren)."""
    data = read_deployment(project_dir)
    if data is None:
        return
    data["last_check_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    data["last_check_healthy"] = healthy
    data["last_check_detail"] = detail
    try:
        _status_path(project_dir).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def list_all_deployments(workspace_dir: str | Path) -> list[tuple[str, dict]]:
    """(project_slug, deployment_data) für jedes workspace/*-Projekt mit einem gespeicherten
    Deployment - Grundlage für core/production_monitor.py, das nicht selbst wissen muss,
    welche Projekte überhaupt jemals deployt wurden."""
    results: list[tuple[str, dict]] = []
    base = Path(workspace_dir)
    if not base.exists():
        return results
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        data = read_deployment(entry)
        if data:
            results.append((entry.name, data))
    return results
