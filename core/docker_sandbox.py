"""
core/docker_sandbox.py – Container-Isolation für die Ausführung von Agenten-Code

Realer Fund (Framework-Analyse 2026-09-10): Von Agenten erzeugter Code (Testsuiten, setup.py-/
postinstall-Skripte beim `pip install`, `node`/`npx` über run_command) lief direkt auf dem Host.
core/code_sandbox.py entfernt zwar Secret-Umgebungsvariablen, aber derselbe Code konnte die
`.env` des Frameworks mit ALLEN API-Keys schlicht vom Dateisystem lesen - bei Aufträgen aus
externen Quellen (GitHub-Issues) ein realer Exfiltrationspfad.

Mit `SANDBOX_BACKEND=docker` laufen die Code-ausführenden Pfade in einem kurzlebigen Container,
in den AUSSCHLIESSLICH das Projektverzeichnis eingebunden wird (kein Framework-Code, keine `.env`,
keine Host-Umgebungsvariablen):
- Abhängigkeitsinstallation (pip, npm ci/install) - core/verifier/environment.py
- Testausführung (pytest/unittest, npm test) - core/verifier/testrunner.py
- Frontend-Build (npm run build) - core/verifier/runtime.py
- run_command-Werkzeug der Agenten für pip/python/pytest/npm/npx/node - core/agent_toolbox.py

Python-Pakete landen in einem benannten Volume je Projekt+Image (kein Host-venv), node_modules in
einem Volume je Node-Verzeichnis - der Host-Arbeitsbaum bleibt frei von Linux-Binärartefakten.
Rein statische Werkzeuge (ruff/mypy/flake8/black) führen keinen Projektcode aus und bleiben lokal.

Bewusst NICHT abgedeckt (weiterhin lokal, siehe ARCHITECTURE.md): Runtime-Smoke-/Lasttests und
Browser-Checks, die einen lokal erreichbaren Server starten.

Ist SANDBOX_BACKEND=docker gesetzt, der Daemon aber nicht erreichbar, wird einmalig gewarnt und
lokal ausgeführt - ein nicht gestartetes Docker Desktop soll keinen Lauf komplett blockieren.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import threading
import time
import uuid
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from config import SANDBOX_BACKEND, SANDBOX_CPUS, SANDBOX_MEMORY, SANDBOX_NODE_IMAGE, SANDBOX_PYTHON_IMAGE
from core.code_sandbox import CodeSandbox, ExecutionResult

CONTAINER_WORKDIR = "/workspace"
CONTAINER_VENV = "/opt/ai-team-venv"
_DAEMON_CHECK_TTL_SECONDS = 60.0
_IMAGE_PULL_TIMEOUT_SECONDS = 900.0
# Einzige Variablen, die in den Container gelangen - nie etwas aus der Host-Umgebung.
_CONTAINER_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_ROOT_USER_ACTION": "ignore",
    "PATH": f"{CONTAINER_VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

_logger = logging.getLogger(__name__)


def _mount_arg(**fields: str) -> str:
    """`--mount`-Wert im CSV-Format; Felder mit Komma/Anführungszeichen werden gequotet."""
    parts = []
    for key, value in fields.items():
        item = f"{key}={value}"
        if "," in item or '"' in item:
            item = '"' + item.replace('"', '""') + '"'
        parts.append(item)
    return ",".join(parts)


class DockerSandbox:
    """Führt Agenten-Code in einem Container aus, der nur das Projektverzeichnis sieht."""

    _lock = threading.Lock()
    _daemon_state: tuple[float, bool] | None = None
    _warned_unavailable = False
    _pulled_images: set[str] = set()

    # ── Aktivierung ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def enabled() -> bool:
        return SANDBOX_BACKEND.strip().lower() == "docker"

    @classmethod
    def daemon_available(cls) -> bool:
        now = time.monotonic()
        with cls._lock:
            if cls._daemon_state and now - cls._daemon_state[0] < _DAEMON_CHECK_TTL_SECONDS:
                return cls._daemon_state[1]
        available = False
        if shutil.which("docker"):
            result = CodeSandbox.run_command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout_seconds=15.0)
            available = result.exit_code == 0 and bool(result.stdout.strip())
        with cls._lock:
            cls._daemon_state = (now, available)
        return available

    @classmethod
    def is_active(cls) -> bool:
        """True, wenn Agenten-Code jetzt im Container laufen soll UND kann."""
        if not cls.enabled():
            return False
        if cls.daemon_available():
            return True
        with cls._lock:
            warn = not cls._warned_unavailable
            cls._warned_unavailable = True
        if warn:
            _logger.warning(
                "SANDBOX_BACKEND=docker ist gesetzt, aber der Docker-Daemon ist nicht erreichbar – "
                "Agenten-Code läuft LOKAL ohne Container-Isolation (Docker Desktop starten)."
            )
        return False

    @classmethod
    def reset_state(cls) -> None:
        """Verwirft Daemon-Cache, Warnhinweis und Image-Cache (Tests, Daemon-Neustart)."""
        with cls._lock:
            cls._daemon_state = None
            cls._warned_unavailable = False
            cls._pulled_images = set()

    # ── Ausführung ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def volume_name(kind: str, project_dir: Path, discriminator: str = "") -> str:
        project_dir = Path(project_dir).resolve()
        digest = hashlib.sha256(f"{project_dir}|{discriminator}".encode()).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9_.-]+", "-", project_dir.name.lower()).strip("-.")[:40] or "projekt"
        return f"ai-team-{kind}-{slug}-{digest}"

    @staticmethod
    def build_command(
        argv: Sequence[str], project_dir: Path, *, image: str, workdir_rel: str = ".",
        volumes: Sequence[tuple[str, str]] = (), container_name: str,
    ) -> list[str]:
        workdir = str(PurePosixPath(CONTAINER_WORKDIR) / PurePosixPath(workdir_rel.replace("\\", "/")))
        command = [
            "docker", "run", "--rm", "--init", "--name", container_name,
            "--mount", _mount_arg(type="bind", source=str(Path(project_dir).resolve()), target=CONTAINER_WORKDIR),
        ]
        for source, target in volumes:
            command += ["--mount", _mount_arg(type="volume", source=source, target=target)]
        command += [
            "-w", workdir,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
            "--memory", SANDBOX_MEMORY, "--cpus", SANDBOX_CPUS, "--pids-limit", "512",
        ]
        for key, value in _CONTAINER_ENV.items():
            command += ["-e", f"{key}={value}"]
        return [*command, image, *argv]

    @classmethod
    def ensure_image(cls, image: str) -> ExecutionResult | None:
        """Lädt ein fehlendes Image EINMAL mit großzügigem Timeout - der erste `docker pull` soll
        nicht das kurze Test-Timeout verbrauchen. None = Image vorhanden."""
        if image in cls._pulled_images:
            return None
        inspect = CodeSandbox.run_command(["docker", "image", "inspect", image], timeout_seconds=30.0)
        if inspect.exit_code != 0:
            pull = CodeSandbox.run_command(["docker", "pull", image], timeout_seconds=_IMAGE_PULL_TIMEOUT_SECONDS)
            if pull.exit_code != 0:
                return pull
        with cls._lock:
            cls._pulled_images.add(image)
        return None

    @staticmethod
    def _to_host_paths(text: str) -> str:
        return (text or "").replace(f"{CONTAINER_WORKDIR}/", "")

    @classmethod
    def _run(
        cls, argv: Sequence[str], project_dir: Path, *, image: str, workdir_rel: str,
        volumes: Sequence[tuple[str, str]], timeout_seconds: float,
    ) -> ExecutionResult:
        pull_failure = cls.ensure_image(image)
        if pull_failure is not None:
            return ExecutionResult(
                exit_code=pull_failure.exit_code or 1, stdout=pull_failure.stdout,
                stderr=f"Sandbox-Image '{image}' konnte nicht geladen werden: {pull_failure.stderr}",
                duration_seconds=pull_failure.duration_seconds, timed_out=pull_failure.timed_out,
            )
        container_name = f"ai-team-sbx-{uuid.uuid4().hex[:12]}"
        command = cls.build_command(
            argv, project_dir, image=image, workdir_rel=workdir_rel, volumes=volumes, container_name=container_name,
        )
        result = CodeSandbox.run_command(command, cwd=project_dir, timeout_seconds=timeout_seconds, restrict_env=True)
        if result.timed_out:
            # Das Beenden des docker-CLI stoppt den Container NICHT - sonst liefe er weiter.
            CodeSandbox.run_command(["docker", "rm", "-f", container_name], timeout_seconds=30.0)
        return ExecutionResult(
            exit_code=result.exit_code, stdout=cls._to_host_paths(result.stdout),
            stderr=cls._to_host_paths(result.stderr), duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
        )

    @classmethod
    def run_python(
        cls, argv: Sequence[str], project_dir: Path | str, timeout_seconds: float, workdir_rel: str = ".",
    ) -> ExecutionResult:
        """Führt `argv` im Python-Image aus; `python`/`pip`/`pytest` stammen aus einer projekt-
        eigenen venv im Volume (wird beim ersten Aufruf angelegt)."""
        project_dir = Path(project_dir).resolve()
        bootstrap = [
            "sh", "-c",
            f'[ -x {CONTAINER_VENV}/bin/python ] || python -m venv {CONTAINER_VENV} || exit 97; exec "$@"',
            "ai-team-sandbox", *[a.replace("\\", "/") for a in argv],
        ]
        volume = cls.volume_name("pyenv", project_dir, SANDBOX_PYTHON_IMAGE)
        return cls._run(
            bootstrap, project_dir, image=SANDBOX_PYTHON_IMAGE, workdir_rel=workdir_rel,
            volumes=[(volume, CONTAINER_VENV)], timeout_seconds=timeout_seconds,
        )

    @classmethod
    def run_node(
        cls, argv: Sequence[str], project_dir: Path | str, node_dir: Path | str, timeout_seconds: float,
    ) -> ExecutionResult:
        """Führt `argv` im Node-Image in `node_dir` aus; node_modules liegt in einem Volume."""
        project_dir = Path(project_dir).resolve()
        rel = Path(node_dir).resolve().relative_to(project_dir).as_posix()
        target = f"{CONTAINER_WORKDIR}/node_modules" if rel == "." else f"{CONTAINER_WORKDIR}/{rel}/node_modules"
        volume = cls.volume_name("node", project_dir, f"{rel}|{SANDBOX_NODE_IMAGE}")
        return cls._run(
            [a.replace("\\", "/") for a in argv], project_dir, image=SANDBOX_NODE_IMAGE, workdir_rel=rel,
            volumes=[(volume, target)], timeout_seconds=timeout_seconds,
        )
