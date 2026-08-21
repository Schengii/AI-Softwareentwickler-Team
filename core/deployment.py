"""
core/deployment.py – Echtes lokales Deployment per Docker (Compose bevorzugt)

core/verifier.py.check_docker_build() prüft bislang NUR, ob ein generiertes Dockerfile
überhaupt baut – "das würde eine konkrete Ziel-Infrastruktur voraussetzen, die dieses
Framework nicht kennt" (siehe dortiger Docstring). Jetzt kennt es eine: Docker Compose
lokal/self-hosted, der ohne Cloud-Account/API-Token funktionierende Standardfall – ein
"fertiges" Projekt muss nicht länger nur im workspace/-Ordner liegen bleiben, es kann
tatsächlich laufen.

Manuell ausgelöst (`/deploy` in der CLI, Deploy-Button im Dashboard), NIE automatisch nach
einem Push/Merge – echte Container-Ausführung ist folgenreicher als ein reiner Build-Check
(startet einen laufenden Prozess, belegt Ports) und verdient dieselbe
Bestätigungs-Gate-Philosophie wie der bestehende Git-Push-Dialog (siehe
interface/cli.py._ask_for_git_push).

Bewusst NUR Docker Compose (bzw. `docker build`+`docker run` als Fallback ohne
Compose-Datei) – ein PaaS-Ziel (Fly.io/Railway/...) bräuchte einen echten Account/API-Token
und ist damit eine bewusst separate, spätere Erweiterung.
"""

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.code_sandbox import CodeSandbox

DEPLOY_TIMEOUT_SECONDS = 300.0
_COMPOSE_FILENAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
_EXPOSE_PATTERN = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE | re.MULTILINE)


@dataclass
class DeploymentResult:
    """Ergebnis eines deploy_project()/stop_deployment()-Aufrufs."""
    attempted: bool
    success: bool
    method: str = ""  # "compose" | "docker" | ""
    output: str = ""
    urls: list[str] = field(default_factory=list)
    reason_skipped: str = ""


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _find_compose_file(project_dir: Path) -> Path | None:
    for name in _COMPOSE_FILENAMES:
        candidate = project_dir / name
        if candidate.exists():
            return candidate
    return None


def _service_name(project_dir: Path) -> str:
    """Container-/Image-Name aus dem Projektordnernamen - nur Kleinbuchstaben/Ziffern/
    Bindestriche (Docker erlaubt keine anderen Zeichen in Namen)."""
    return re.sub(r"[^a-z0-9-]+", "-", project_dir.name.lower()).strip("-") or "ai-team-project"


def describe_deploy_plan(project_dir: str | Path) -> str:
    """
    Beschreibt in einem Satz, was deploy_project() für dieses Projekt tun WÜRDE, ohne es
    auszuführen – Grundlage für die Vorschau vor der Bestätigung
    (interface/cli.py._deploy_project_with_confirmation), nutzt dieselbe Datei-Erkennung wie
    deploy_project() selbst statt sie ein zweites Mal zu duplizieren.
    """
    project_dir = Path(project_dir)
    compose_file = _find_compose_file(project_dir)
    if compose_file:
        return f"`docker compose -f {compose_file.name} up -d --build` (Compose-Datei gefunden)"
    if (project_dir / "Dockerfile").exists():
        return "`docker build` + `docker run` (kein Compose, nur ein Dockerfile gefunden)"
    return "Kein Dockerfile/keine Compose-Datei gefunden – Deployment nicht möglich."


def deploy_project(project_dir: str | Path, timeout_seconds: float = DEPLOY_TIMEOUT_SECONDS) -> DeploymentResult:
    """
    Deployt EIN Projekt lokal per Docker: `docker compose up -d --build`, falls eine
    Compose-Datei existiert, sonst `docker build` + `docker run` bei einem reinen Dockerfile.
    Kein Fallback auf einen erfundenen Erfolg – jeder Fehlerfall liefert die ECHTE
    Docker-Ausgabe zurück statt einer beschönigenden Zusammenfassung (dieselbe "echt statt
    geraten"-Philosophie wie der bestehende Dependency-Audit/Docker-Build-Check).
    """
    project_dir = Path(project_dir)

    if not _docker_available():
        return DeploymentResult(
            attempted=False, success=False,
            reason_skipped="Docker ist auf diesem System nicht installiert/verfügbar.",
        )

    compose_file = _find_compose_file(project_dir)
    if compose_file:
        return _deploy_with_compose(project_dir, compose_file, timeout_seconds)

    dockerfile = project_dir / "Dockerfile"
    if dockerfile.exists():
        return _deploy_with_plain_docker(project_dir, dockerfile, timeout_seconds)

    return DeploymentResult(
        attempted=False, success=False,
        reason_skipped="Weder eine Compose-Datei (docker-compose.yml) noch ein Dockerfile im Projekt gefunden.",
    )


def _deploy_with_compose(project_dir: Path, compose_file: Path, timeout_seconds: float) -> DeploymentResult:
    result = CodeSandbox.run_command(
        ["docker", "compose", "-f", compose_file.name, "up", "-d", "--build"],
        cwd=project_dir, timeout_seconds=timeout_seconds,
    )
    output = (result.stdout + result.stderr).strip()[-3000:]
    if result.exit_code != 0:
        return DeploymentResult(attempted=True, success=False, method="compose", output=output)
    return DeploymentResult(attempted=True, success=True, method="compose", output=output, urls=_compose_urls(project_dir, compose_file))


def _compose_urls(project_dir: Path, compose_file: Path) -> list[str]:
    """
    Liest die tatsächlich veröffentlichten Host-Ports aus `docker compose ps` (echte
    Laufzeit-Zuordnung statt aus der Compose-Datei geraten – Docker kann Ports z.B. per
    "8000" statt "8000:8000" dynamisch zuweisen). Leere Liste bei JEDEM Parsing-Problem statt
    eines Crashs – das Deployment war trotzdem erfolgreich, nur die URL-Anzeige unvollständig.
    """
    result = CodeSandbox.run_command(
        ["docker", "compose", "-f", compose_file.name, "ps", "--format", "json"],
        cwd=project_dir, timeout_seconds=20.0,
    )
    if result.exit_code != 0 or not result.stdout.strip():
        return []
    urls: list[str] = []
    for line in result.stdout.strip().splitlines():  # compose v2: eine Zeile ein JSON-Objekt
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        for mapping in entry.get("Publishers") or []:
            host_port = mapping.get("PublishedPort")
            if host_port:
                urls.append(f"http://localhost:{host_port}")
    return sorted(set(urls))


def _deploy_with_plain_docker(project_dir: Path, dockerfile: Path, timeout_seconds: float) -> DeploymentResult:
    tag = f"ai-team-deploy-{_service_name(project_dir)}"
    build_result = CodeSandbox.run_command(["docker", "build", "-t", tag, "."], cwd=project_dir, timeout_seconds=timeout_seconds)
    if build_result.exit_code != 0:
        return DeploymentResult(
            attempted=True, success=False, method="docker",
            output=(build_result.stdout + build_result.stderr).strip()[-3000:],
        )

    # Einen zuvor laufenden Container mit demselben Namen vorher aufräumen (z.B. erneutes
    # Deploy nach einer Code-Änderung) - Fehler bewusst ignoriert (Container existiert oft
    # noch nicht, "docker rm" auf ein nicht-existentes Ziel ist kein echter Fehlerfall hier).
    CodeSandbox.run_command(["docker", "rm", "-f", tag], cwd=project_dir, timeout_seconds=20.0)

    port_match = _EXPOSE_PATTERN.search(dockerfile.read_text(encoding="utf-8", errors="ignore"))
    run_command = ["docker", "run", "-d", "--name", tag]
    urls: list[str] = []
    if port_match:
        port = port_match.group(1)
        run_command += ["-p", f"{port}:{port}"]
        urls = [f"http://localhost:{port}"]
    run_command.append(tag)

    run_result = CodeSandbox.run_command(run_command, cwd=project_dir, timeout_seconds=30.0)
    if run_result.exit_code != 0:
        return DeploymentResult(
            attempted=True, success=False, method="docker",
            output=(run_result.stdout + run_result.stderr).strip()[-3000:],
        )
    return DeploymentResult(attempted=True, success=True, method="docker", output=run_result.stdout.strip(), urls=urls)


def stop_deployment(project_dir: str | Path, timeout_seconds: float = 60.0) -> DeploymentResult:
    """Fährt ein per deploy_project() gestartetes Deployment wieder herunter (compose down
    bzw. Entfernen des einzelnen Containers)."""
    project_dir = Path(project_dir)
    if not _docker_available():
        return DeploymentResult(
            attempted=False, success=False,
            reason_skipped="Docker ist auf diesem System nicht installiert/verfügbar.",
        )

    compose_file = _find_compose_file(project_dir)
    if compose_file:
        result = CodeSandbox.run_command(
            ["docker", "compose", "-f", compose_file.name, "down"],
            cwd=project_dir, timeout_seconds=timeout_seconds,
        )
        return DeploymentResult(
            attempted=True, success=result.exit_code == 0, method="compose",
            output=(result.stdout + result.stderr).strip()[-2000:],
        )

    tag = f"ai-team-deploy-{_service_name(project_dir)}"
    result = CodeSandbox.run_command(["docker", "rm", "-f", tag], cwd=project_dir, timeout_seconds=timeout_seconds)
    return DeploymentResult(
        attempted=True, success=result.exit_code == 0, method="docker",
        output=(result.stdout + result.stderr).strip()[-2000:],
    )
