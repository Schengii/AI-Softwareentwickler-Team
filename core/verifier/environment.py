"""
core/verifier/environment.py – EnvironmentMixin: legt bei Bedarf eine isolierte virtuelle
Umgebung im Projekt an und installiert echte Abhängigkeiten (Python venv+pip, npm ci/install,
cargo, go) sowie die dafür nötige Stack-Erkennung (Node-Projekte, Rust/Go-Projekte).

Definiert außerdem __init__() der ProjectVerifier-Klasse (self.project_dir) – Grundlage,
auf der alle anderen Check-Mixins (testrunner, security, lint, coverage, runtime) aufbauen.
"""

import json
import shutil
import sys
from pathlib import Path

from core.code_sandbox import CodeSandbox
from core.verifier.models import _IGNORED_DIRS, VENV_DIRNAME


class EnvironmentMixin:
    """Installiert Abhängigkeiten isoliert und stellt die Stack-Erkennung für ein Projekt bereit."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()

    def _venv_python(self) -> Path:
        venv_dir = self.project_dir / VENV_DIRNAME
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _requirements_files(self) -> list[Path]:
        files = []
        # Dieselben Manifest-Namen, die core/manifest_guard.py bereits als gültige Python-
        # Requirements-Dateien anerkennt (_PYTHON_REQUIREMENTS_MANIFESTS) - vorher fehlten
        # requirements-test.txt/requirements-prod.txt hier, sodass ein Agent, der eine dieser
        # (vom Korruptions-Schutz bereits als legitim behandelten) Dateien anlegt, in der
        # Sandbox trotzdem NIE installiert worden wäre: dieselbe Dependency-Desynchronisation
        # wie beim ursprünglichen requirements-dev.txt-Fund, nur unter anderem Dateinamen.
        for name in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt", "requirements-prod.txt"):
            candidate = self.project_dir / name
            if candidate.exists() and candidate.stat().st_size > 0:
                files.append(candidate)
        return files

    def ensure_environment(self, timeout_seconds: float = 120.0) -> str:
        """
        Installiert echte Abhängigkeiten für JEDEN im Projekt gefundenen Stack:
        - Python: legt bei vorhandener requirements.txt/requirements-dev.txt eine isolierte venv an und
          installiert per pip (sowohl Produktiv- als auch Test-Abhängigkeiten).
        - Node: für jedes gefundene package.json mit "test"-Skript per `npm ci`
          (bei vorhandener package-lock.json, deterministisch) oder `npm install`.
        Gibt eine kombinierte Statuszeile zurück (leer, wenn nichts zu tun war, z.B.
        ein reines Textprojekt ohne requirements.txt/package.json).
        """
        logs: list[str] = []
        req_files = self._requirements_files()
        for req_file in req_files:
            logs.append(self._ensure_python_environment(req_file, timeout_seconds))
        # Team-Optimierung (echter Fund, `recurring-failure-event_relay`/
        # `recurring-failure-service_bookmark_monitor`-Tickets in memory/backlog.json): siehe
        # _ensure_pytest_available()-Docstring - nur relevant, wenn überhaupt eine venv angelegt
        # wurde (req_files nicht leer) UND echte pytest-Testdateien existieren, sonst unnötiger
        # zusätzlicher pip-Aufruf für Projekte ohne Python-Tests.
        if req_files and self._find_python_test_files():
            logs.append(self._ensure_pytest_available(timeout_seconds))
        for node_dir in self._find_node_projects():
            logs.append(self._ensure_node_environment(node_dir, timeout_seconds))
        if self._has_rust_project():
            logs.append(self._ensure_rust_environment(timeout_seconds))
        if self._has_go_project():
            logs.append(self._ensure_go_environment(timeout_seconds))
        return "\n".join(log for log in logs if log)

    def _has_rust_project(self) -> bool:
        return (self.project_dir / "Cargo.toml").exists()

    def _has_go_project(self) -> bool:
        return (self.project_dir / "go.mod").exists()

    def _ensure_rust_environment(self, timeout_seconds: float) -> str:
        if shutil.which("cargo") is None:
            return "⚠️ `cargo` ist auf diesem System nicht installiert/verfügbar – Rust-Check übersprungen."
        result = CodeSandbox.run_command(["cargo", "check"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        status = "✅" if result.exit_code == 0 else "⚠️"
        return f"{status} cargo check (exit_code={result.exit_code})"

    def _ensure_go_environment(self, timeout_seconds: float) -> str:
        if shutil.which("go") is None:
            return "⚠️ `go` ist auf diesem System nicht installiert/verfügbar – Go-Abhängigkeiten übersprungen."
        result = CodeSandbox.run_command(["go", "mod", "download"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        status = "✅" if result.exit_code == 0 else "⚠️"
        return f"{status} go mod download (exit_code={result.exit_code})"

    def _ensure_python_environment(self, req_file: Path, timeout_seconds: float) -> str:
        venv_python = self._venv_python()
        if not venv_python.exists():
            create_result = CodeSandbox.run_command(
                [sys.executable, "-m", "venv", str(self.project_dir / VENV_DIRNAME)],
                cwd=self.project_dir,
                timeout_seconds=60.0,
            )
            if create_result.exit_code != 0:
                return f"⚠️ Konnte keine isolierte venv anlegen (nutze System-Interpreter als Fallback): {create_result.stderr[:300]}"

        target_python = venv_python if venv_python.exists() else Path(sys.executable)
        install_result = CodeSandbox.run_command(
            [str(target_python), "-m", "pip", "install", "-q", "-r", str(req_file)],
            cwd=self.project_dir,
            timeout_seconds=timeout_seconds,
        )
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        tail = (install_result.stdout + install_result.stderr).strip()[-800:]
        return f"{status} pip install -r {req_file.name} (exit_code={install_result.exit_code})" + (f"\n{tail}" if install_result.exit_code != 0 else "")

    def _ensure_pytest_available(self, timeout_seconds: float) -> str:
        """
        Team-Optimierung (echter Fund: memory/backlog.json-Tickets `recurring-failure-
        event_relay` und `recurring-failure-service_bookmark_monitor`). core/verifier/
        testrunner.py._run_pytest_or_unittest() prüft vor jedem Testlauf `import pytest` und
        fällt bei Fehlschlag STILLSCHWEIGEND auf `python -m unittest discover` zurück - das
        findet dabei aber fast IMMER 0 Tests ("Ran 0 tests in 0.000s / NO TESTS RAN"), weil
        generierter Testcode praktisch ausschließlich im pytest-Stil geschrieben wird (einfache
        `def test_...()`-Funktionen ohne `unittest.TestCase`-Basisklasse), die unittests eigene
        Discovery gar nicht als Tests erkennt. Der anschließende Fix-Loop
        (agents/orchestrator/verification.py) konnte diesem "Testfehler" mangels Traceback/
        Datei-Bezug keinen Agenten sinnvoll zuordnen und beauftragte blind den `tester` (siehe
        dortiger Fallback `if not owners: owners = {"tester"}`) - der konnte das Problem nie
        lösen ("Fixversuch änderte nichts"), weil die eigentliche Ursache (fehlendes `pytest` in
        requirements.txt/requirements-dev.txt) außerhalb seiner Zuständigkeit liegt: er kann
        Testdateien schreiben, aber nicht wissen, dass die Umgebung sie gar nicht ausführen kann.

        `pytest` ist das vom FRAMEWORK selbst gewählte Test-Werkzeug (core/verifier/testrunner.py
        entscheidet sich dafür, nicht der generierte Code) - stellt seine Verfügbarkeit deshalb
        unabhängig davon sicher, ob der jeweilige Agent daran gedacht hat, es als Abhängigkeit
        aufzunehmen, statt das strukturell nie lösbare Symptom im Fix-Loop zu bekämpfen. Ein
        Installationsfehlschlag (z.B. kein Netzwerkzugriff) lässt run_tests() bewusst unverändert
        auf den bereits bestehenden `import pytest`-Check/unittest-Fallback zurückfallen, statt
        den gesamten Lauf zu blockieren.
        """
        target_python = self._venv_python() if self._venv_python().exists() else Path(sys.executable)
        check = CodeSandbox.run_command(
            [str(target_python), "-c", "import pytest"], cwd=self.project_dir, timeout_seconds=10.0,
        )
        if check.exit_code == 0:
            return ""
        install_result = CodeSandbox.run_command(
            [str(target_python), "-m", "pip", "install", "-q", "pytest"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        return (
            f"{status} `pytest` fehlte in der Umgebung (nicht in requirements.txt/"
            f"requirements-dev.txt) - nachinstalliert (exit_code={install_result.exit_code})"
        )

    def _ensure_node_environment(self, node_dir: Path, timeout_seconds: float) -> str:
        rel = self._relative_label(node_dir)
        if shutil.which("npm") is None:
            return f"⚠️ `npm` ist auf diesem System nicht installiert/verfügbar – Node-Abhängigkeiten ({rel}) übersprungen."

        command = ["npm", "ci"] if (node_dir / "package-lock.json").exists() else ["npm", "install"]
        install_result = CodeSandbox.run_command(command, cwd=node_dir, timeout_seconds=timeout_seconds)
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        tail = (install_result.stdout + install_result.stderr).strip()[-800:]
        label = f"{' '.join(command)} ({rel})"
        return f"{status} {label} (exit_code={install_result.exit_code})" + (f"\n{tail}" if install_result.exit_code != 0 else "")

    def _relative_label(self, directory: Path) -> str:
        rel = directory.relative_to(self.project_dir)
        return "." if str(rel) == "." else str(rel).replace("\\", "/")

    def _find_node_projects(self) -> list[Path]:
        """
        Findet alle package.json-Verzeichnisse im Projekt (node_modules & Co. ausgeschlossen),
        die ein "test"-Skript deklarieren – nur solche sind über `npm test` echt ausführbar.
        Ein package.json ohne "test"-Skript wird bewusst ignoriert statt eines Fehlschlags,
        genau wie ein Python-Projekt ohne test_*.py-Dateien.
        """
        projects: list[Path] = []
        for pkg_json in self.project_dir.rglob("package.json"):
            if any(part in _IGNORED_DIRS for part in pkg_json.relative_to(self.project_dir).parts):
                continue
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data.get("scripts"), dict) and data["scripts"].get("test"):
                projects.append(pkg_json.parent)
        return projects

    def _find_node_build_projects(self) -> list[Path]:
        """
        Findet alle package.json-Verzeichnisse im Projekt (node_modules & Co. ausgeschlossen),
        die ein "build"-Skript deklarieren – dieselbe Suche wie _find_node_projects() oben, nur
        mit "build" statt "test" als Filterkriterium (siehe RuntimeMixin.check_frontend_build()
        für den vollen Kontext: ein "test"-Skript und ein "build"-Skript prüfen unterschiedliche
        Dinge und ein Projekt kann beide, nur eines oder keines von beiden deklarieren).
        """
        projects: list[Path] = []
        for pkg_json in self.project_dir.rglob("package.json"):
            if any(part in _IGNORED_DIRS for part in pkg_json.relative_to(self.project_dir).parts):
                continue
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data.get("scripts"), dict) and data["scripts"].get("build"):
                projects.append(pkg_json.parent)
        return projects

    def _resolve_python(self) -> str:
        venv_python = self._venv_python()
        return str(venv_python) if venv_python.exists() else sys.executable

    def _has_python_files(self) -> bool:
        return any(
            f for f in self.project_dir.rglob("*.py")
            if not any(part in _IGNORED_DIRS for part in f.parts)
        )
