"""
core/verifier.py – Echte Verifikation statt Keyword-Raten

Ersetzt die alte, rein textbasierte Fix-Schleife (die nur nach Schlagworten
wie "kritischer fehler" im Reviewer-Text suchte und danach blind
backend/frontend/database neu beauftragte). Stattdessen:

1. Legt bei Bedarf eine isolierte virtuelle Umgebung im Projekt an und
   installiert requirements.txt wirklich (echte Dependency-Installation).
2. Führt die tatsächliche Testsuite aus (pytest, falls verfügbar, sonst
   unittest discover) und liest das reale Ergebnis (exit_code/stdout/stderr).
3. Parst bei Fehlschlägen die echten pytest-/unittest-Ausgaben und
   Tracebacks, um herauszufinden, WELCHE Quelldateien betroffen sind –
   als Grundlage dafür, den Fix gezielt an den Agenten zurückzuspielen,
   der genau diese Datei geschrieben hat (statt an alle Dev-Agenten blind).
"""

import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.code_sandbox import CodeSandbox, ExecutionResult

VENV_DIRNAME = ".ai_team_venv"


@dataclass
class TestFailure:
    """Ein einzelner, aus der echten Testausgabe geparster Fehlschlag."""
    test_id: str
    message: str
    files: list[str] = field(default_factory=list)  # Relative Projektpfade, die im Traceback auftauchen


@dataclass
class VerificationReport:
    """Ergebnis eines echten Verifikationslaufs (kein Keyword-Raten)."""
    ran: bool
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    failures: list[TestFailure] = field(default_factory=list)
    reason_skipped: str = ""


@dataclass
class DockerBuildReport:
    """
    Ergebnis eines echten `docker build`-Versuchs – Teil der "echtes Deployment"-Ambition:
    ein generiertes Dockerfile, das nie tatsächlich baut, ist praktisch wertlos für den
    Anspruch, ein Projekt bis zum Ausrollen zu bringen. Wie bei fehlenden Tests (siehe
    VerificationReport.reason_skipped) gilt: kein Dockerfile bzw. keine lokale Docker-
    Installation ist KEIN Fehler, nur nicht prüfbar (attempted=False).
    """
    attempted: bool
    success: bool
    output: str
    reason_skipped: str = ""


class ProjectVerifier:
    """Installiert Abhängigkeiten isoliert und führt die reale Testsuite eines Projekts aus."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()

    def _venv_python(self) -> Path:
        venv_dir = self.project_dir / VENV_DIRNAME
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _requirements_file(self) -> Path | None:
        for name in ("requirements.txt", "requirements-dev.txt"):
            candidate = self.project_dir / name
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
        return None

    def ensure_environment(self, timeout_seconds: float = 120.0) -> str:
        """
        Legt bei vorhandener requirements.txt eine isolierte venv an und installiert
        die Abhängigkeiten wirklich per pip. Gibt eine kurze Statuszeile zurück
        (leer, wenn keine requirements.txt existiert und daher nichts zu tun war).
        """
        req_file = self._requirements_file()
        if not req_file:
            return ""

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

    def _resolve_python(self) -> str:
        venv_python = self._venv_python()
        return str(venv_python) if venv_python.exists() else sys.executable

    def run_tests(self, timeout_seconds: float = 60.0) -> VerificationReport:
        """Führt die echte Testsuite aus. Kein Keyword-Matching – reales exit_code/stdout/stderr."""
        start = time.monotonic()
        ignored = {VENV_DIRNAME, ".venv", "venv", "__pycache__", "node_modules"}
        test_files = [
            f for f in list(self.project_dir.rglob("test_*.py")) + list(self.project_dir.rglob("*_test.py"))
            if not any(part in ignored for part in f.parts)
        ]

        if not test_files:
            return VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="",
                duration_seconds=time.monotonic() - start,
                reason_skipped="Keine Testdateien (test_*.py) im Projekt gefunden – Verifikation übersprungen.",
            )

        python_exe = self._resolve_python()
        exec_result = self._run_pytest_or_unittest(python_exe, timeout_seconds)

        report = VerificationReport(
            ran=True,
            passed=exec_result.exit_code == 0,
            exit_code=exec_result.exit_code,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            duration_seconds=time.monotonic() - start,
        )
        if not report.passed:
            report.failures = self._parse_failures(exec_result)
        return report

    def check_docker_build(self, timeout_seconds: float = 180.0) -> DockerBuildReport:
        """
        Versucht einen echten `docker build` des Projekts, falls ein Dockerfile existiert
        und `docker` lokal verfügbar ist – ein generiertes Dockerfile, das nie tatsächlich
        baut, bringt ein Projekt nicht näher an ein echtes Deployment. Baut NIE `docker run`
        oder gar einen echten Push/Deploy aus (das würde eine konkrete Ziel-Infrastruktur
        voraussetzen, die dieses Framework nicht kennt) – nur die Build-Fähigkeit wird geprüft.
        """
        dockerfile = self.project_dir / "Dockerfile"
        if not dockerfile.exists():
            return DockerBuildReport(attempted=False, success=True, output="", reason_skipped="Kein Dockerfile im Projekt gefunden.")

        if shutil.which("docker") is None:
            return DockerBuildReport(attempted=False, success=True, output="", reason_skipped="Docker ist auf diesem System nicht installiert/verfügbar.")

        tag = f"ai-team-verify-{self.project_dir.name.lower()}"
        result = CodeSandbox.run_command(
            ["docker", "build", "-t", tag, "."],
            cwd=self.project_dir,
            timeout_seconds=timeout_seconds,
        )
        output = (result.stdout + result.stderr).strip()[-2000:]
        return DockerBuildReport(attempted=True, success=result.exit_code == 0, output=output)

    def _run_pytest_or_unittest(self, python_exe: str, timeout_seconds: float) -> ExecutionResult:
        pytest_check = CodeSandbox.run_command([python_exe, "-c", "import pytest"], cwd=self.project_dir, timeout_seconds=10.0)
        if pytest_check.exit_code == 0:
            return CodeSandbox.run_command(
                [python_exe, "-m", "pytest", "-q", "--tb=short", str(self.project_dir)],
                cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
        return CodeSandbox.run_command(
            [python_exe, "-m", "unittest", "discover", "-s", str(self.project_dir), "-p", "test_*.py"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )

    def _parse_failures(self, exec_result: ExecutionResult) -> list[TestFailure]:
        """Parst echte pytest-/unittest-Ausgaben – keine Schlagwortsuche in Freitext."""
        output = f"{exec_result.stdout}\n{exec_result.stderr}"
        failures: dict[str, TestFailure] = {}

        # pytest-Format: "FAILED tests/test_x.py::test_foo - AssertionError: ..."
        for m in re.finditer(r'^FAILED (\S+)(?:\s+-\s+(.*))?$', output, re.MULTILINE):
            test_id = m.group(1)
            failures[test_id] = TestFailure(test_id=test_id, message=(m.group(2) or "").strip())

        # unittest-Format: "FAIL: test_foo (module.TestCase)" / "ERROR: test_foo (module.TestCase)"
        for m in re.finditer(r'^(?:FAIL|ERROR): (.+)$', output, re.MULTILINE):
            test_id = m.group(1).strip()
            failures.setdefault(test_id, TestFailure(test_id=test_id, message=""))

        # Tracebacks: welche Projektdateien tauchen tatsächlich auf? (site-packages/venv ausgeschlossen)
        # Zwei Formate müssen erkannt werden:
        #   1. Klassischer Python-/unittest-Traceback:  File "pfad/datei.py", line 42
        #   2. pytest --tb=short:                        pfad/datei.py:42: in test_foo
        raw_paths = re.findall(r'File "([^"]+)", line \d+', output)
        raw_paths += re.findall(r'^([^\s:][^\n:]*?\.py):\d+: in ', output, re.MULTILINE)

        implicated_files: list[str] = []
        for fp in raw_paths:
            path = Path(fp)
            if any(part in (VENV_DIRNAME, ".venv", "venv", "site-packages") for part in path.parts):
                continue
            try:
                abs_path = path if path.is_absolute() else (self.project_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                continue
            if rel not in implicated_files:
                implicated_files.append(rel)

        if not failures:
            # Kein strukturiertes FAILED/FAIL/ERROR-Muster erkannt (z.B. Sammel-/Importfehler
            # beim Einsammeln der Tests) – trotzdem als generischer Fehlschlag mit realem Output melden.
            failures["<Testlauf>"] = TestFailure(test_id="<Testlauf>", message=output.strip()[-800:])

        for failure in failures.values():
            failure.files = implicated_files

        return list(failures.values())
