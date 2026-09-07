"""
core/verifier/testrunner.py – TestRunnerMixin: führt die tatsächliche Testsuite JEDES im
Projekt gefundenen Stacks aus (pytest/unittest, npm test, cargo test, go test) und parst bei
Fehlschlägen die echten Test-Ausgaben/Tracebacks, um herauszufinden, WELCHE Quelldateien
betroffen sind – als Grundlage dafür, den Fix gezielt an den Agenten zurückzuspielen, der
genau diese Datei geschrieben hat (statt an alle Dev-Agenten blind).

Erkennt außerdem unvollständig abgebrochene Projekt-Generierungsläufe (siehe
_find_incomplete_project_reason), bei denen bisher fälschlich "nichts zu testen" statt
"Generierung abgebrochen" gemeldet wurde.
"""

import re
import shutil
import time
from pathlib import Path

from core.code_sandbox import CodeSandbox, ExecutionResult
from core.verifier.models import (
    _IGNORED_DIRS,
    _NODE_ENV_ERROR_PATTERN,
    _NODE_FAIL_FILE_PATTERN,
    _NODE_STACK_FILE_PATTERN,
    VENV_DIRNAME,
    TestFailure,
    VerificationReport,
)

_MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")


class TestRunnerMixin:
    """Führt die reale Testsuite eines Projekts aus (kein Keyword-Raten)."""

    def _find_python_test_files(self) -> list[Path]:
        return [
            f for f in list(self.project_dir.rglob("test_*.py")) + list(self.project_dir.rglob("*_test.py"))
            if not any(part in _IGNORED_DIRS for part in f.parts)
        ]

    # Erkennbare Einstiegspunkte für ein deployable Python-Backend/-Skript. Eine einzelne
    # `app.py` OHNE jedes dieser Signale ist trotzdem ein legitimes Mini-Skript (siehe
    # test_skips_when_no_test_files_present) - die Heuristik unten greift deshalb bewusst nur,
    # wenn ZUSÄTZLICH ein starkes "das hier sollte eine echte Anwendung sein"-Signal vorliegt.
    _PYTHON_ENTRYPOINT_NAMES = {"main.py", "app.py", "manage.py", "run.py", "wsgi.py", "asgi.py", "__main__.py"}

    def _find_incomplete_project_reason(self) -> str:
        """
        Realer Fund (Workspace-Audit): `verification_ok` galt bisher schon als "bestanden",
        sobald schlicht keine Testdateien gefunden wurden - das ist für ein triviales Skript
        richtig, hat aber zwei echte, mehrteilige Backend-Läufe unbemerkt durchgewunken, die
        mitten in der Generierung abgebrochen wirken: ein Projekt mit `requirements.txt` und
        mehreren Python-Modulen, aber OHNE jeden Einstiegspunkt (kein main.py/app.py/...), und
        ein Projekt mit einem tests/-Ordner, der nur eine conftest.py aber keine einzige echte
        Testdatei enthält. Beides sind starke Signale für einen unvollständig abgebrochenen Lauf,
        keine legitime "hier gibt es nichts zu testen"-Situation - anders als das schon bestehende
        Beispiel eines einzelnen Skripts ohne requirements.txt.
        """
        python_files = [
            f for f in self.project_dir.rglob("*.py")
            if not any(part in _IGNORED_DIRS for part in f.parts)
        ]
        if not python_files:
            has_specs_only = (self.project_dir / "docs" / "adr").exists() or any(
                f for f in self.project_dir.rglob("*.md")
                if not any(part in _IGNORED_DIRS for part in f.parts)
            )
            has_other_code = self._find_node_projects() or self._has_rust_project() or self._has_go_project()
            if has_specs_only and not has_other_code:
                return (
                    "Es existieren Architektur-/ADR-/Doku-Dateien (docs/, docs/adr/), aber KEIN "
                    "einziger Quellcode (kein *.py, kein Node/Rust/Go-Projekt) - die Generierung "
                    "wurde offenbar nach der Planungs-/Architekturphase abgebrochen, bevor Backend- "
                    "und Tester-Agent tatsächlich Code geliefert haben."
                )
            return ""

        has_manifest = any(
            (self.project_dir / name).exists() for name in ("requirements.txt", "pyproject.toml")
        )
        has_entrypoint = any(f.name in self._PYTHON_ENTRYPOINT_NAMES for f in python_files)

        if has_manifest and len(python_files) >= 2 and not has_entrypoint:
            return (
                f"{len(python_files)} Python-Quelldateien und eine Abhängigkeitsliste "
                "(requirements.txt/pyproject.toml) gefunden, aber kein erkennbarer Einstiegspunkt "
                f"({'/'.join(sorted(self._PYTHON_ENTRYPOINT_NAMES))}) - sieht nach einem mitten in "
                "der Generierung abgebrochenen Backend-Projekt aus, nicht nach einem fertigen Skript."
            )

        conftest_files = [f for f in python_files if f.name == "conftest.py"]
        if conftest_files and not self._find_python_test_files():
            return (
                "Ein tests/-Verzeichnis mit conftest.py existiert, aber keine einzige echte "
                "Testdatei (test_*.py/*_test.py) - sieht nach einer abgebrochenen Testsuite aus, "
                "nicht nach einem Projekt, das bewusst auf Tests verzichtet."
            )
        return ""

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

        has_rust = self._has_rust_project()
        has_go = self._has_go_project()
        cargo_available = shutil.which("cargo") is not None
        go_available = shutil.which("go") is not None

        if not python_test_files and not runnable_node_projects and not (has_rust and cargo_available) and not (has_go and go_available):
            if node_projects and not npm_available:
                reason = "npm-Test-Skript(e) gefunden, aber `npm` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            elif has_rust and not cargo_available:
                reason = "Cargo.toml gefunden, aber `cargo` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            elif has_go and not go_available:
                reason = "go.mod gefunden, aber `go` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            else:
                incomplete_reason = self._find_incomplete_project_reason()
                if incomplete_reason:
                    return VerificationReport(
                        ran=False, passed=False, exit_code=1, stdout="", stderr="",
                        duration_seconds=time.monotonic() - start,
                        reason_skipped=f"Unvollständiges Projekt erkannt: {incomplete_reason}",
                    )
                reason = 'Keine Testdateien (test_*.py), kein npm-Test-Skript und kein Rust/Go-Projekt gefunden – Verifikation übersprungen.'
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
            if exec_result.exit_code != 0:
                fallback_log = self._fallback_install_missing_modules(exec_result, python_exe, timeout_seconds)
                if fallback_log:
                    stdout_chunks.append(fallback_log)
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

        if has_rust and cargo_available:
            exec_result = CodeSandbox.run_command(
                ["cargo", "test"], cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
            stdout_chunks.append(f"--- cargo test ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.append(TestFailure(test_id="cargo test", message=(exec_result.stderr or exec_result.stdout)[-800:]))

        if has_go and go_available:
            exec_result = CodeSandbox.run_command(
                ["go", "test", "-v", "./..."], cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
            stdout_chunks.append(f"--- go test ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.append(TestFailure(test_id="go test", message=(exec_result.stderr or exec_result.stdout)[-800:]))

        if node_projects and not npm_available:
            stdout_chunks.insert(0, "⚠️ npm nicht verfügbar – gefundene npm-Test-Skripte wurden übersprungen.")

        return VerificationReport(
            ran=True, passed=passed, exit_code=exit_code,
            stdout="\n".join(stdout_chunks), stderr="\n".join(stderr_chunks),
            duration_seconds=time.monotonic() - start, failures=failures,
        )

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

    def _fallback_install_missing_modules(
        self, exec_result: ExecutionResult, python_exe: str, timeout_seconds: float,
    ) -> str:
        """
        Realer Fund: der Tester-Agent importiert legitime Testwerkzeuge (httpx,
        pytest-asyncio, ...), trägt sie aber manchmal nur in requirements-dev.txt statt in
        JEDE tatsächlich installierte requirements-Datei ein (oder vergisst den Eintrag ganz).
        `ensure_environment()` installiert zwar bereits alle gefundenen requirements*.txt
        (siehe core/verifier/environment.py), das deckt diesen vergessenen Fall aber nicht ab.
        Best-effort-Fallback: parst ModuleNotFoundError aus dem fehlgeschlagenen Testlauf und
        installiert das fehlende Top-Level-Paket einmalig direkt in die Sandbox-Umgebung, statt
        den Testlauf an einem künstlichen Abhängigkeitsfehler scheitern zu lassen. Gibt eine
        Statuszeile für den Verifikationsbericht zurück, oder "" wenn nichts zu tun war.
        """
        output = f"{exec_result.stdout}\n{exec_result.stderr}"
        missing = {m.group(1).split(".")[0] for m in _MODULE_NOT_FOUND_RE.finditer(output)}
        # Lokale Projekt-Module herausfiltern - das sind echte Code-/Import-Bugs, keine
        # fehlenden Abhängigkeiten, und sollen weiterhin als Testfehler gemeldet werden.
        missing = {
            m for m in missing
            if not (self.project_dir / f"{m}.py").exists() and not (self.project_dir / m).is_dir()
        }
        if not missing:
            return ""
        install_result = CodeSandbox.run_command(
            [python_exe, "-m", "pip", "install", "-q", *sorted(missing)],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        return (
            f"{status} Zur Laufzeit fehlende Module erkannt und nachinstalliert: "
            f"{', '.join(sorted(missing))} - sollten dauerhaft in requirements.txt/"
            "requirements-dev.txt ergänzt werden."
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
            # Bugfix (realer Fund am Pong-Projekt): message blieb hier bisher IMMER die leere
            # Zeichenkette ("") - der Fix-Agent im Governance-/Verifikations-Fix-Loop (siehe
            # agents/orchestrator.py._run_verification_loop) bekam dadurch nie die tatsächliche
            # Fehlermeldung zu sehen, nur test_id und Dateiname, und musste blind raten. Wie
            # beim generischen <npm test>-Fallback direkt unten: die letzten 800 Zeichen der
            # rohen Ausgabe sind zwar nicht chirurgisch präzise pro Suite, aber IMMER
            # informativer als eine leere Zeichenkette.
            failures.setdefault(test_id, TestFailure(test_id=test_id, message=output.strip()[-800:]))

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

        # Bei einer erkannten Umgebungs-/Konfigurations-Fehlerklasse (siehe
        # _NODE_ENV_ERROR_PATTERN) zusätzlich package.json des betroffenen Node-Projekts als
        # implizierte Datei ergänzen, damit auch dessen Owner (i.d.R. frontend/devops, nicht
        # zwingend tester) im Fix-Loop adressiert wird - ZUSÄTZLICH zur Testdatei aus dem
        # Stack-Trace oben, nicht statt ihr, da beide plausible Fix-Orte sind.
        if _NODE_ENV_ERROR_PATTERN.search(output):
            pkg_json = node_dir / "package.json"
            if pkg_json.exists():
                try:
                    rel_pkg = str(pkg_json.resolve().relative_to(self.project_dir)).replace("\\", "/")
                    if rel_pkg not in implicated_files:
                        implicated_files.append(rel_pkg)
                except ValueError:
                    pass

        if not failures:
            failures["<npm test>"] = TestFailure(test_id="<npm test>", message=output.strip()[-800:])

        for failure in failures.values():
            failure.files = implicated_files

        return list(failures.values())
