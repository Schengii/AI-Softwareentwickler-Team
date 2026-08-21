"""
core/verifier.py – Echte Verifikation statt Keyword-Raten

Ersetzt die alte, rein textbasierte Fix-Schleife (die nur nach Schlagworten
wie "kritischer fehler" im Reviewer-Text suchte und danach blind
backend/frontend/database neu beauftragte). Stattdessen:

1. Legt bei Bedarf eine isolierte virtuelle Umgebung im Projekt an und
   installiert requirements.txt wirklich (echte Dependency-Installation).
   Für Node/npm-Projekte (package.json) läuft dieselbe echte Installation
   über `npm ci`/`npm install`.
2. Führt die tatsächliche Testsuite aus (pytest, falls verfügbar, sonst
   unittest discover; für Node-Projekte `npm test`) und liest das reale
   Ergebnis (exit_code/stdout/stderr).
3. Parst bei Fehlschlägen die echten pytest-/unittest-/npm-test-Ausgaben und
   Tracebacks, um herauszufinden, WELCHE Quelldateien betroffen sind –
   als Grundlage dafür, den Fix gezielt an den Agenten zurückzuspielen,
   der genau diese Datei geschrieben hat (statt an alle Dev-Agenten blind).

Realer Fund: bisher wurde AUSSCHLIESSLICH Python-Code echt verifiziert
(test_*.py). Ein vom frontend/mobile-Agenten erzeugtes JS/TS-Projekt lief nie
durch einen echten `npm test` – "keine Tests gefunden" tauchte selbst dann
auf, wenn eine vollständige, echt ausführbare npm-Testsuite existierte.

Zusätzlich: check_dependency_vulnerabilities() ersetzt die bisherige rein
LLM-basierte Einschätzung des security-Agenten zu Abhängigkeits-Risiken durch
einen echten Scan (pip-audit/npm audit) gegen eine öffentliche Advisory-
Datenbank – kein Raten mehr, ob eine gepinnte Paketversion bekannte CVEs hat.

Und: check_lint() prüft generierten Code jetzt auch tatsächlich mit echten
Tools (ruff für Python – immer, braucht keine Projekt-Konfiguration; ESLint/
tsc für Node – nur wenn das Projekt sie selbst bereits als Dev-Abhängigkeit +
Konfiguration mitbringt, keine ungefragte Meinungsänderung am Projekt-Stil).
Bisher lief ruff.toml NUR gegen den Framework-Code selbst (workspace/ dort
bewusst ausgeschlossen) – generierter Code hatte dadurch überhaupt keine
automatische Stil-/Fehlerprüfung.
"""

import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import MIN_TEST_COVERAGE_PERCENT
from core.code_sandbox import CodeSandbox, ExecutionResult

VENV_DIRNAME = ".ai_team_venv"

# Verzeichnisse, die weder als Python- noch als Node-Testquelle zählen – Build-/Umgebungs-
# Artefakte, keine vom Team geschriebenen Projektdateien.
_IGNORED_DIRS = {VENV_DIRNAME, ".venv", "venv", "__pycache__", "node_modules", ".git"}

# Best-effort-Erkennung fehlgeschlagener npm-Tests: Jest/Vitest melden fehlgeschlagene
# Testdateien als "FAIL <pfad>" bzw. mit "✕"/"×" vor dem Testnamen. Da es kein einheitliches
# Node-Test-Ausgabeformat gibt (anders als Python mit pytest/unittest), ist das bewusst ein
# Best-Effort wie bei allen anderen nicht strukturiert geparsten Fehlschlägen (siehe
# _parse_python_failures unten) – kein Anspruch, jedes Framework exakt zu parsen.
_NODE_FAIL_FILE_PATTERN = re.compile(r"^(?:FAIL|✕|×)\s+(\S+\.(?:js|jsx|ts|tsx))", re.MULTILINE)
_NODE_STACK_FILE_PATTERN = re.compile(r"\(([^():\n]+\.(?:js|jsx|ts|tsx)):\d+:\d+\)")

# tsc hat kein natives JSON-Format – `--pretty false` liefert stattdessen dieses stabile,
# grep-bare Zeilenformat: "pfad(zeile,spalte): error TSxxxx: nachricht".
_TSC_ERROR_PATTERN = re.compile(r"^(.+?)\((\d+),(\d+)\): (error|warning) (TS\d+): (.+)$", re.MULTILINE)

# ESLint-Konfigurationsdateien, deren Vorhandensein signalisiert, dass das Projekt ESLint
# selbst bewusst eingerichtet hat – nur DANN wird gelintet, um keine ungefragte Meinung
# über den Code-Stil eines Projekts durchzusetzen, das sich nie für ESLint entschieden hat.
_ESLINT_CONFIG_NAMES = (
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml",
)


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


@dataclass
class DependencyVulnerability:
    """Eine einzelne, aus einem echten pip-audit-/npm-audit-Scan geparste Schwachstelle."""
    package: str
    version: str
    vulnerability_id: str
    description: str
    severity: str = ""


@dataclass
class DependencyAuditReport:
    """
    Ergebnis eines echten Dependency-Vulnerability-Scans (`pip-audit` für Python,
    `npm audit` für Node) – ersetzt die bisherige rein LLM-basierte Einschätzung des
    security-Agenten, der Abhängigkeiten nur "plausibel" bewerten konnte, durch einen
    echten Abgleich gegen eine öffentliche CVE-/Advisory-Datenbank.

    Wie bei DockerBuildReport gilt: eine fehlende Abhängigkeitsdatei, ein fehlendes
    Scan-Tool ODER ein technischer Fehlschlag des Scans selbst (z. B. keine
    Netzwerkverbindung zur Advisory-Datenbank) sind KEIN Fehler, nur nicht prüfbar
    (attempted=False) – und werden NIEMALS fälschlich als "keine Schwachstellen gefunden"
    gemeldet. Das wäre ein gefährlicher falscher Sicherheitsanspruch: ein technischer
    Fehlschlag des Scans ist etwas anderes als ein sauberes Scan-Ergebnis.
    """
    attempted: bool
    vulnerable: bool
    tool: str
    vulnerabilities: list[DependencyVulnerability] = field(default_factory=list)
    reason_skipped: str = ""


@dataclass
class CoverageReport:
    """
    Ergebnis einer echten Coverage-Messung (`coverage.py`) – ersetzt die bisher rein
    behauptete Fähigkeit "Code-Coverage-Analyse" im System-Prompt des tester-Agenten
    (agents/tester_agent.py), die nirgends im echten Code tatsächlich AUSGEFÜHRT wurde.

    Wie bei DockerBuildReport/DependencyAuditReport/LintReport gilt: fehlendes Tool, ein
    technischer Fehlschlag der Messung selbst, oder gar keine Python-Testdateien sind KEIN
    Fehler, nur nicht messbar (attempted=False) – niemals fälschlich als "0% Coverage"
    gemeldet. `passed` vergleicht gegen MIN_TEST_COVERAGE_PERCENT (config.py), beeinflusst
    aber – wie check_lint()/check_dependency_vulnerabilities() – bewusst NICHT
    verification_ok: ein KI-generiertes Projekt mit niedriger Coverage soll die reale Zahl
    sichtbar machen, nicht hart blockiert werden.
    """
    attempted: bool
    passed: bool
    percent_covered: float
    threshold: float
    reason_skipped: str = ""


@dataclass
class LintIssue:
    """Ein einzelnes, aus einer echten ruff-/ESLint-/tsc-Ausgabe geparstes Fundstück."""
    file_path: str
    line_number: int
    message: str
    rule: str = ""


@dataclass
class LintReport:
    """
    Ergebnis eines echten Lint-/Type-Check-Laufs (ruff für Python; ESLint/tsc für Node) –
    ersetzt keine LLM-Einschätzung, sondern liefert erstmals überhaupt eine automatische
    Stil-/Fehlerprüfung für generierten Code (ruff.toml lief bisher NUR gegen den
    Framework-Code selbst, workspace/ dort bewusst ausgeschlossen).

    Python wird IMMER geprüft, wenn .py-Dateien existieren und ruff verfügbar ist – ruff
    braucht keine Projekt-Konfiguration. ESLint/tsc laufen dagegen NUR, wenn das Projekt
    sie selbst bereits als Dev-Abhängigkeit UND Konfiguration mitbringt (siehe
    _ESLINT_CONFIG_NAMES) – keine ungefragte Meinungsänderung an einem Projekt, das sich
    nie für diese Tools entschieden hat.

    Wie bei DockerBuildReport/DependencyAuditReport gilt: fehlendes Tool oder ein
    technischer Fehlschlag des Lint-Laufs selbst sind KEIN Fehler, nur nicht prüfbar
    (attempted=False) – und werden NIEMALS fälschlich als "keine Probleme" gemeldet.
    """
    attempted: bool
    passed: bool
    tool: str
    issues: list[LintIssue] = field(default_factory=list)
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
        Installiert echte Abhängigkeiten für JEDEN im Projekt gefundenen Stack:
        - Python: legt bei vorhandener requirements.txt eine isolierte venv an und
          installiert per pip.
        - Node: für jedes gefundene package.json mit "test"-Skript per `npm ci`
          (bei vorhandener package-lock.json, deterministisch) oder `npm install`.
        Gibt eine kombinierte Statuszeile zurück (leer, wenn nichts zu tun war, z.B.
        ein reines Textprojekt ohne requirements.txt/package.json).
        """
        logs: list[str] = []
        req_file = self._requirements_file()
        if req_file:
            logs.append(self._ensure_python_environment(req_file, timeout_seconds))
        for node_dir in self._find_node_projects():
            logs.append(self._ensure_node_environment(node_dir, timeout_seconds))
        return "\n".join(log for log in logs if log)

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

    def _resolve_python(self) -> str:
        venv_python = self._venv_python()
        return str(venv_python) if venv_python.exists() else sys.executable

    def _find_python_test_files(self) -> list[Path]:
        return [
            f for f in list(self.project_dir.rglob("test_*.py")) + list(self.project_dir.rglob("*_test.py"))
            if not any(part in _IGNORED_DIRS for part in f.parts)
        ]

    def run_tests(self, timeout_seconds: float = 60.0) -> VerificationReport:
        """
        Führt die echte Testsuite JEDES im Projekt gefundenen Stacks aus. Kein Keyword-
        Matching – reales exit_code/stdout/stderr, kombiniert über alle Stacks. Ein Projekt
        gilt insgesamt als bestanden, wenn ALLE gefundenen Testsuiten (Python UND/ODER Node)
        bestehen – ein grüner Backend-Test bei rotem Frontend-Test darf nicht als "bestanden"
        durchgehen.
        """
        start = time.monotonic()
        python_test_files = self._find_python_test_files()
        node_projects = self._find_node_projects()
        npm_available = shutil.which("npm") is not None
        runnable_node_projects = node_projects if npm_available else []

        if not python_test_files and not runnable_node_projects:
            if node_projects and not npm_available:
                reason = "npm-Test-Skript(e) gefunden, aber `npm` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            else:
                reason = 'Keine Testdateien (test_*.py) und kein npm-Test-Skript (package.json mit "scripts.test") im Projekt gefunden – Verifikation übersprungen.'
            return VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="",
                duration_seconds=time.monotonic() - start, reason_skipped=reason,
            )

        passed = True
        exit_code = 0
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        failures: list[TestFailure] = []

        if python_test_files:
            python_exe = self._resolve_python()
            exec_result = self._run_pytest_or_unittest(python_exe, timeout_seconds)
            stdout_chunks.append(f"--- Python (pytest/unittest) ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.extend(self._parse_python_failures(exec_result))

        for node_dir in runnable_node_projects:
            exec_result = CodeSandbox.run_command(
                ["npm", "test", "--silent"], cwd=node_dir, timeout_seconds=timeout_seconds,
            )
            rel = self._relative_label(node_dir)
            stdout_chunks.append(f"--- npm test ({rel}) ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.extend(self._parse_node_failures(exec_result, node_dir))

        if node_projects and not npm_available:
            stdout_chunks.insert(0, "⚠️ npm nicht verfügbar – gefundene npm-Test-Skripte wurden übersprungen.")

        return VerificationReport(
            ran=True, passed=passed, exit_code=exit_code,
            stdout="\n".join(stdout_chunks), stderr="\n".join(stderr_chunks),
            duration_seconds=time.monotonic() - start, failures=failures,
        )

    def check_coverage(self, timeout_seconds: float = 60.0) -> CoverageReport:
        """
        Misst echte Test-Coverage per `coverage.py` – ersetzt die bisher rein behauptete
        Fähigkeit im System-Prompt des tester-Agenten durch eine tatsächliche Messung.
        NUR für Python (analog zu check_lint()s bewusster Python-Priorität – Node-Coverage
        bräuchte eine andere Toolchain wie nyc/istanbul). Installiert `coverage` bei Bedarf
        in dieselbe venv wie run_tests() und liest das reale JSON-Ergebnis – kein Parsen
        von Freitext-Prozentzahlen.
        """
        if not self._find_python_test_files():
            return CoverageReport(
                attempted=False, passed=True, percent_covered=0.0, threshold=MIN_TEST_COVERAGE_PERCENT,
                reason_skipped="Keine Testdateien (test_*.py) im Projekt gefunden – Coverage nicht messbar.",
            )

        python_exe = self._resolve_python()
        install_result = CodeSandbox.run_command(
            [python_exe, "-m", "pip", "install", "-q", "coverage"],
            cwd=self.project_dir, timeout_seconds=60.0,
        )
        if install_result.exit_code != 0:
            return CoverageReport(
                attempted=False, passed=True, percent_covered=0.0, threshold=MIN_TEST_COVERAGE_PERCENT,
                reason_skipped=f"`coverage`-Paket konnte nicht installiert werden: {install_result.stderr[:300]}",
            )

        data_file = self.project_dir / ".ai_team_coverage_data"
        json_file = self.project_dir / ".ai_team_coverage.json"
        try:
            pytest_check = CodeSandbox.run_command([python_exe, "-c", "import pytest"], cwd=self.project_dir, timeout_seconds=10.0)
            if pytest_check.exit_code == 0:
                run_command = [python_exe, "-m", "coverage", "run", f"--data-file={data_file}", "-m", "pytest", "-q", str(self.project_dir)]
            else:
                run_command = [python_exe, "-m", "coverage", "run", f"--data-file={data_file}", "-m", "unittest",
                                "discover", "-s", str(self.project_dir), "-p", "test_*.py"]
            run_result = CodeSandbox.run_command(run_command, cwd=self.project_dir, timeout_seconds=timeout_seconds)

            # coverage run's eigener exit_code spiegelt nur den Testlauf-Exit-Code wider
            # (Testfehler selbst sind bereits Gegenstand von run_tests() oben) - hier zählt
            # nur, ob überhaupt Coverage-Daten geschrieben wurden.
            if not data_file.exists():
                tail = (run_result.stdout + run_result.stderr).strip()[-500:]
                return CoverageReport(
                    attempted=False, passed=True, percent_covered=0.0, threshold=MIN_TEST_COVERAGE_PERCENT,
                    reason_skipped=f"Coverage-Messung lieferte keine Daten (Testlauf evtl. abgestürzt): {tail}",
                )

            json_result = CodeSandbox.run_command(
                [python_exe, "-m", "coverage", "json", f"--data-file={data_file}", "-o", str(json_file), "-q"],
                cwd=self.project_dir, timeout_seconds=30.0,
            )
            try:
                report_data = json.loads(json_file.read_text(encoding="utf-8"))
                percent = float(report_data["totals"]["percent_covered"])
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                return CoverageReport(
                    attempted=False, passed=True, percent_covered=0.0, threshold=MIN_TEST_COVERAGE_PERCENT,
                    reason_skipped=f"Coverage-JSON-Report konnte nicht gelesen werden: {json_result.stderr[:300]}",
                )
        finally:
            data_file.unlink(missing_ok=True)
            json_file.unlink(missing_ok=True)

        return CoverageReport(
            attempted=True, passed=percent >= MIN_TEST_COVERAGE_PERCENT,
            percent_covered=percent, threshold=MIN_TEST_COVERAGE_PERCENT,
        )

    def check_docker_build(self, timeout_seconds: float = 180.0) -> DockerBuildReport:
        """
        Versucht einen echten `docker build` des Projekts, falls ein Dockerfile existiert
        und `docker` lokal verfügbar ist – ein generiertes Dockerfile, das nie tatsächlich
        baut, bringt ein Projekt nicht näher an ein echtes Deployment. Baut NIE `docker run`
        oder gar einen echten Deploy aus – nur die Build-Fähigkeit wird geprüft. Das
        tatsächliche lokale Deployment (Docker Compose bzw. `docker run`) übernimmt bei Bedarf
        core/deployment.py, manuell ausgelöst über `/deploy` – bewusst getrennt von dieser
        automatischen Verifikationsprüfung, da eine echte Container-Ausführung Ports belegt
        und einen laufenden Prozess startet, eine reine Build-Prüfung dagegen nicht.
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

    def check_dependency_vulnerabilities(self, timeout_seconds: float = 120.0) -> list[DependencyAuditReport]:
        """
        Führt für JEDEN im Projekt gefundenen Stack einen echten Vulnerability-Scan gegen
        eine öffentliche Advisory-Datenbank aus: `pip-audit` für Python (requirements.txt),
        `npm audit` für Node (dieselben package.json-Verzeichnisse wie run_tests(), inkl.
        derselben package-lock.json, die ensure_environment() dort bereits angelegt hat).
        Ersetzt die rein LLM-basierte Sicherheitseinschätzung durch einen echten Abgleich –
        gibt eine Liste zurück, da ein Projekt mehrere Stacks/Node-Unterprojekte haben kann.
        """
        reports: list[DependencyAuditReport] = []
        req_file = self._requirements_file()
        if req_file:
            reports.append(self._audit_python_dependencies(req_file, timeout_seconds))
        for node_dir in self._find_node_projects():
            reports.append(self._audit_node_dependencies(node_dir, timeout_seconds))
        return reports

    def _audit_python_dependencies(self, req_file: Path, timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("pip-audit") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="pip-audit",
                reason_skipped="`pip-audit` ist auf diesem System nicht installiert/verfügbar "
                               "(`pip install pip-audit`).",
            )
        # `-r <requirements.txt>` löst Versionen direkt aus der Datei auf – braucht KEINE
        # lokale Installation der Pakete, funktioniert also unabhängig von der isolierten
        # venv (die für ein frisches Projekt evtl. noch gar nicht existiert).
        result = CodeSandbox.run_command(
            ["pip-audit", "-r", str(req_file), "-f", "json"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_pip_audit_result(result)

    def _parse_pip_audit_result(self, result: ExecutionResult) -> DependencyAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="pip-audit",
                reason_skipped=f"pip-audit lieferte kein gültiges Ergebnis (z. B. keine "
                               f"Netzwerkverbindung zur Advisory-Datenbank): {tail}",
            )

        vulnerabilities = [
            DependencyVulnerability(
                package=dep.get("name", "?"),
                version=dep.get("version", "?"),
                vulnerability_id=vuln.get("id", "?"),
                description=(vuln.get("description") or "").strip()[:300],
            )
            for dep in data.get("dependencies", [])
            for vuln in dep.get("vulns", [])
        ]
        return DependencyAuditReport(
            attempted=True, vulnerable=len(vulnerabilities) > 0, tool="pip-audit",
            vulnerabilities=vulnerabilities,
        )

    def _audit_node_dependencies(self, node_dir: Path, timeout_seconds: float) -> DependencyAuditReport:
        rel = self._relative_label(node_dir)
        if shutil.which("npm") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm` ist auf diesem System nicht installiert/verfügbar ({rel}).",
            )
        if not (node_dir / "package-lock.json").exists():
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"Keine package-lock.json ({rel}) – `npm audit` benötigt eine Lockfile "
                               f"(wird normalerweise von ensure_environment() angelegt).",
            )

        result = CodeSandbox.run_command(
            ["npm", "audit", "--json"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_npm_audit_result(result, rel)

    def _parse_npm_audit_result(self, result: ExecutionResult, label: str) -> DependencyAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm audit` ({label}) lieferte kein gültiges Ergebnis: {tail}",
            )

        # `npm audit` meldet einen technischen Fehlschlag (z. B. Registry nicht erreichbar)
        # als {"error": {...}} OHNE "vulnerabilities"-Schlüssel – das darf NIE stillschweigend
        # als "keine Schwachstellen" durchgehen.
        if "error" in data and "vulnerabilities" not in data:
            error_detail = json.dumps(data.get("error", {}))[:500]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm audit` ({label}) meldete einen Fehler statt eines Scan-Ergebnisses: {error_detail}",
            )

        vulnerabilities: list[DependencyVulnerability] = []
        for pkg_name, pkg_info in data.get("vulnerabilities", {}).items():
            for via in pkg_info.get("via", []):
                if not isinstance(via, dict):
                    continue  # String-Eintrag = Verweis auf eine andere betroffene Abhängigkeit, keine eigene Advisory
                vuln_id = via.get("url", "").rsplit("/", 1)[-1] or via.get("title", "?")
                vulnerabilities.append(DependencyVulnerability(
                    package=pkg_name,
                    version=pkg_info.get("range", "?"),
                    vulnerability_id=vuln_id,
                    description=(via.get("title") or "").strip()[:300],
                    severity=via.get("severity", ""),
                ))
        total = data.get("metadata", {}).get("vulnerabilities", {}).get("total", len(vulnerabilities))
        return DependencyAuditReport(
            attempted=True, vulnerable=total > 0, tool="npm audit", vulnerabilities=vulnerabilities,
        )

    def check_lint(self, timeout_seconds: float = 60.0) -> list[LintReport]:
        """
        Prüft generierten Code JEDES gefundenen Stacks mit echten Tools statt LLM-Meinung:
        - Python: IMMER per ruff, wenn .py-Dateien existieren (braucht keine Projekt-
          Konfiguration, läuft isoliert von der eigenen ruff.toml des Frameworks).
        - Node: ESLint/tsc NUR, wenn das jeweilige Projekt sie selbst bereits als Dev-
          Abhängigkeit UND Konfiguration mitbringt – keine ungefragte Meinungsänderung an
          einem Projekt, das sich nie für diese Tools entschieden hat.
        Gibt eine Liste zurück (mehrere Stacks/Node-Unterprojekte, ESLint UND tsc möglich).
        """
        reports: list[LintReport] = []
        if self._has_python_files():
            reports.append(self._lint_python(timeout_seconds))
        for node_dir in self._find_node_projects():
            eslint_report = self._lint_node_eslint(node_dir, timeout_seconds)
            if eslint_report is not None:
                reports.append(eslint_report)
            tsc_report = self._typecheck_node_tsc(node_dir, timeout_seconds)
            if tsc_report is not None:
                reports.append(tsc_report)
        return reports

    def _has_python_files(self) -> bool:
        return any(
            f for f in self.project_dir.rglob("*.py")
            if not any(part in _IGNORED_DIRS for part in f.parts)
        )

    def _lint_python(self, timeout_seconds: float) -> LintReport:
        if shutil.which("ruff") is None:
            return LintReport(
                attempted=False, passed=True, tool="ruff",
                reason_skipped="`ruff` ist auf diesem System nicht installiert/verfügbar (`pip install ruff`).",
            )
        # --isolated: ignoriert JEDE gefundene Konfigurationsdatei (auch die eigene
        # ruff.toml des Frameworks, falls das Projekt innerhalb des Repos liegt) und nutzt
        # ruffs neutrale Standardregeln – die eigenen, für den Framework-Code kuratierten
        # Regeln (z. B. E501-Ausnahme für deutschsprachige Docstrings) sollen einem
        # beliebigen generierten Projekt nicht aufgezwungen werden.
        command = ["ruff", "check", str(self.project_dir), "--isolated", "--output-format=json"]
        command += [f"--extend-exclude={d}" for d in sorted(_IGNORED_DIRS)]
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_ruff_result(result)

    def _parse_ruff_result(self, result: ExecutionResult) -> LintReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="ruff",
                reason_skipped=f"ruff lieferte kein gültiges Ergebnis: {tail}",
            )

        issues: list[LintIssue] = []
        for entry in data:
            raw_path = entry.get("filename", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            issues.append(LintIssue(
                file_path=rel,
                line_number=entry.get("location", {}).get("row", 0),
                message=entry.get("message", ""),
                rule=entry.get("code") or "",
            ))
        return LintReport(attempted=True, passed=len(issues) == 0, tool="ruff", issues=issues)

    def _node_bin(self, node_dir: Path, name: str) -> Path | None:
        """Löst ein lokal in node_modules/.bin installiertes Node-Tool auf (kein globales npx-
        Auto-Install, kein interaktiver Prompt) – nur, wenn das Projekt es selbst installiert hat."""
        candidates = [node_dir / "node_modules" / ".bin" / name]
        if sys.platform == "win32":
            candidates.append(node_dir / "node_modules" / ".bin" / f"{name}.cmd")
        return next((c for c in candidates if c.exists()), None)

    def _lint_node_eslint(self, node_dir: Path, timeout_seconds: float) -> LintReport | None:
        if not any((node_dir / name).exists() for name in _ESLINT_CONFIG_NAMES):
            return None  # Projekt nutzt erkennbar kein ESLint - keine ungefragte Meinungsänderung
        rel = self._relative_label(node_dir)
        eslint_bin = self._node_bin(node_dir, "eslint")
        if eslint_bin is None:
            return LintReport(
                attempted=False, passed=True, tool="eslint",
                reason_skipped=f"ESLint-Konfiguration gefunden, aber ESLint nicht in node_modules "
                               f"installiert ({rel}).",
            )
        result = CodeSandbox.run_command(
            [str(eslint_bin), ".", "--format=json"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_eslint_result(result, node_dir)

    def _parse_eslint_result(self, result: ExecutionResult, node_dir: Path) -> LintReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="eslint",
                reason_skipped=f"ESLint lieferte kein gültiges Ergebnis: {tail}",
            )

        issues: list[LintIssue] = []
        for file_entry in data:
            raw_path = file_entry.get("filePath", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            for msg in file_entry.get("messages", []):
                if msg.get("severity", 0) < 2:
                    continue  # severity 1 = Warnung, nur echte Fehler (2) zählen als "nicht bestanden"
                issues.append(LintIssue(
                    file_path=rel, line_number=msg.get("line", 0),
                    message=msg.get("message", ""), rule=msg.get("ruleId") or "",
                ))
        return LintReport(attempted=True, passed=len(issues) == 0, tool="eslint", issues=issues)

    def _typecheck_node_tsc(self, node_dir: Path, timeout_seconds: float) -> LintReport | None:
        if not (node_dir / "tsconfig.json").exists():
            return None  # Projekt nutzt erkennbar kein TypeScript - nichts zu typprüfen
        rel = self._relative_label(node_dir)
        tsc_bin = self._node_bin(node_dir, "tsc")
        if tsc_bin is None:
            return LintReport(
                attempted=False, passed=True, tool="tsc",
                reason_skipped=f"tsconfig.json gefunden, aber TypeScript nicht in node_modules "
                               f"installiert ({rel}).",
            )
        result = CodeSandbox.run_command(
            [str(tsc_bin), "--noEmit", "--pretty", "false"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_tsc_result(result, node_dir)

    def _parse_tsc_result(self, result: ExecutionResult, node_dir: Path) -> LintReport:
        # tsc hat kein natives JSON-Format (anders als ruff/ESLint) - ein leerer Output bei
        # exit_code 0 bedeutet "keine Fehler", jedes andere Ergebnis wird per _TSC_ERROR_PATTERN
        # geparst. Kein strukturiertes Muster gefunden trotz Fehlschlag -> generischer Fallback,
        # analog zu den anderen best-effort geparsten Ausgaben (z. B. _parse_node_failures).
        output = f"{result.stdout}\n{result.stderr}"
        matches = list(_TSC_ERROR_PATTERN.finditer(output))

        if not matches:
            if result.exit_code == 0:
                return LintReport(attempted=True, passed=True, tool="tsc")
            tail = output.strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="tsc",
                reason_skipped=f"tsc lieferte kein auswertbares Ergebnis (exit_code={result.exit_code}): {tail}",
            )

        issues: list[LintIssue] = []
        for m in matches:
            raw_path, line_no, _col, _level, code, message = m.groups()
            path = Path(raw_path)
            try:
                abs_path = path if path.is_absolute() else (node_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            issues.append(LintIssue(file_path=rel, line_number=int(line_no), message=message.strip(), rule=code))

        return LintReport(attempted=True, passed=False, tool="tsc", issues=issues)

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

    def _parse_python_failures(self, exec_result: ExecutionResult) -> list[TestFailure]:
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

    def _parse_node_failures(self, exec_result: ExecutionResult, node_dir: Path) -> list[TestFailure]:
        """
        Best-effort-Parsing echter `npm test`-Ausgaben – anders als bei pytest/unittest gibt
        es kein einheitliches Node-Test-Ausgabeformat (Jest, Vitest, Mocha, ... unterscheiden
        sich). Erkennt das verbreitete "FAIL <datei>"-Muster (Jest/Vitest) sowie Dateipfade
        aus Stack-Traces; liefert sonst denselben generischen Fallback wie bei unparsbarer
        Python-Ausgabe (siehe _parse_python_failures).
        """
        output = f"{exec_result.stdout}\n{exec_result.stderr}"
        failures: dict[str, TestFailure] = {}

        for m in _NODE_FAIL_FILE_PATTERN.finditer(output):
            test_id = m.group(1)
            failures.setdefault(test_id, TestFailure(test_id=test_id, message=""))

        implicated_files: list[str] = []
        for fp in _NODE_STACK_FILE_PATTERN.findall(output):
            path = Path(fp)
            if "node_modules" in path.parts:
                continue
            try:
                abs_path = path if path.is_absolute() else (node_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                continue
            if rel not in implicated_files:
                implicated_files.append(rel)

        if not failures:
            failures["<npm test>"] = TestFailure(test_id="<npm test>", message=output.strip()[-800:])

        for failure in failures.values():
            failure.files = implicated_files

        return list(failures.values())
