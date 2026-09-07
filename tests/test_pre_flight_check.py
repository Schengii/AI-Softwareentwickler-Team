"""
tests/test_pre_flight_check.py – Tests fuer core/pre_flight_check.py

Testet den deterministischen Vorab-Import-Check:
- PreFlightReport.passed / has_blocking_issues
- Syntax-Fehler-Erkennung
- Fehlende __init__.py-Erkennung
- Missing-Dependency-Erkennung gegen requirements.txt
- Deduplizierung identischer Befunde
- Best-Effort-Verhalten bei nicht-existentem Verzeichnis
- format_for_agent() / format_pre_flight_issues_for_fix()
- Leeres Projektverzeichnis (kein Python-Code)
- Verzeichnisse in _SKIP_DIRS werden uebersprungen
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.pre_flight_check import (
    PreFlightIssue,
    PreFlightReport,
    format_pre_flight_issues_for_fix,
    run_pre_flight_check,
)


def _write(path: Path, content: str) -> None:
    """Hilfsfunktion: Schreibt content nach path (erstellt Elternverzeichnisse)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestPreFlightReportProperties(unittest.TestCase):
    """Einheits-Tests fuer PreFlightReport-Properties."""

    def test_passed_when_no_issues_and_no_error(self):
        report = PreFlightReport(project_dir="/tmp/test")
        self.assertTrue(report.passed)

    def test_not_passed_when_issues_present(self):
        report = PreFlightReport(project_dir="/tmp/test")
        report.issues.append(
            PreFlightIssue(file="x.py", line=1, issue_type="syntax_error", message="oops")
        )
        self.assertFalse(report.passed)

    def test_not_passed_when_error_set(self):
        report = PreFlightReport(project_dir="/tmp/test", error="crash")
        self.assertTrue(report.passed is False)

    def test_has_blocking_issues_for_syntax_error(self):
        report = PreFlightReport(project_dir="/tmp/test")
        report.issues.append(
            PreFlightIssue(file="x.py", line=1, issue_type="syntax_error", message="bad")
        )
        self.assertTrue(report.has_blocking_issues)

    def test_has_blocking_issues_for_missing_init(self):
        report = PreFlightReport(project_dir="/tmp/test")
        report.issues.append(
            PreFlightIssue(file="x.py", line=0, issue_type="missing_init", message="no init")
        )
        self.assertTrue(report.has_blocking_issues)

    def test_has_no_blocking_issues_for_missing_dependency_only(self):
        report = PreFlightReport(project_dir="/tmp/test")
        report.issues.append(
            PreFlightIssue(file="x.py", line=1, issue_type="missing_dependency", message="pkg")
        )
        self.assertFalse(report.has_blocking_issues)

    def test_format_for_agent_passed(self):
        report = PreFlightReport(project_dir="/tmp/test", files_checked=5)
        text = report.format_for_agent()
        self.assertIn("5", text)
        self.assertIn("bestanden", text.lower())

    def test_format_for_agent_with_error(self):
        report = PreFlightReport(project_dir="/tmp/test", error="crash!")
        text = report.format_for_agent()
        self.assertIn("crash!", text)

    def test_format_for_agent_with_issues(self):
        report = PreFlightReport(project_dir="/tmp/test", files_checked=3)
        report.issues.append(
            PreFlightIssue(file="app/main.py", line=5, issue_type="syntax_error",
                           message="bad syntax", suggestion="fix it")
        )
        text = report.format_for_agent()
        self.assertIn("syntax_error", text)
        self.assertIn("app/main.py", text)
        self.assertIn("fix it", text)


class TestRunPreFlightCheckSyntaxErrors(unittest.TestCase):
    """Tests fuer Syntax-Fehler-Erkennung."""

    def test_detects_syntax_error(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "bad.py", "def foo(:\n  pass\n")
            report = run_pre_flight_check(proj)
            self.assertFalse(report.passed)
            self.assertTrue(any(i.issue_type == "syntax_error" for i in report.issues))

    def test_valid_python_file_no_issues(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "good.py", "def foo():\n    return 42\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            # Keine Syntax-Fehler (evtl. Missing-Dependency-Issues fuer stdlib-freie Imports - OK)
            syntax_issues = [i for i in report.issues if i.issue_type == "syntax_error"]
            self.assertEqual(syntax_issues, [])

    def test_syntax_error_file_not_blocking_other_files(self):
        """Syntax-Fehler in einer Datei verhindert nicht den Check der anderen Dateien."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "bad.py", "def foo(:\n  pass\n")
            _write(proj / "good.py", "import os\n")
            report = run_pre_flight_check(proj)
            self.assertEqual(report.files_checked, 2)
            self.assertTrue(any(i.file == "bad.py" and i.issue_type == "syntax_error"
                                for i in report.issues))


class TestRunPreFlightCheckMissingInit(unittest.TestCase):
    """Tests fuer fehlende __init__.py-Erkennung."""

    def test_detects_missing_init_in_package(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            # Paket-Ordner ohne __init__.py
            _write(proj / "app" / "models.py", "class User:\n    pass\n")
            _write(proj / "main.py", "from app.models import User\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            init_issues = [i for i in report.issues if i.issue_type == "missing_init"]
            self.assertTrue(len(init_issues) >= 1, f"Expected missing_init, got: {report.issues}")
            self.assertIn("app", init_issues[0].message)

    def test_no_missing_init_when_init_exists(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app" / "__init__.py", "")
            _write(proj / "app" / "models.py", "class User:\n    pass\n")
            _write(proj / "main.py", "from app.models import User\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            init_issues = [i for i in report.issues if i.issue_type == "missing_init"]
            self.assertEqual(init_issues, [], f"Unexpected missing_init: {report.issues}")

    def test_missing_init_suggestion_mentions_package(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "myapp" / "utils.py", "def helper(): pass\n")
            _write(proj / "main.py", "from myapp.utils import helper\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            init_issues = [i for i in report.issues if i.issue_type == "missing_init"]
            if init_issues:
                self.assertIn("myapp", init_issues[0].suggestion)


class TestRunPreFlightCheckHiddenRuntimeDependency(unittest.TestCase):
    """Tests fuer versteckte Laufzeit-Abhaengigkeiten (Team-Lektionen 2026-09-05):
    greenlet (create_async_engine), python-multipart (OAuth2PasswordRequestForm/Form),
    bcrypt-Versionspin (passlib CryptContext)."""

    def test_detects_missing_greenlet_for_async_engine(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "database.py", "from sqlalchemy.ext.asyncio import create_async_engine\n"
                                          "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n")
            _write(proj / "requirements.txt", "sqlalchemy\n")
            report = run_pre_flight_check(proj)
            hidden = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]
            self.assertTrue(any("greenlet" in i.message.lower() for i in hidden))

    def test_no_issue_when_greenlet_already_listed(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "database.py", "from sqlalchemy.ext.asyncio import create_async_engine\n"
                                          "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n")
            _write(proj / "requirements.txt", "sqlalchemy\ngreenlet\n")
            report = run_pre_flight_check(proj)
            hidden = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]
            self.assertFalse(any("greenlet" in i.message.lower() for i in hidden))

    def test_detects_missing_python_multipart_for_oauth2_form(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "auth.py", "from fastapi.security import OAuth2PasswordRequestForm\n"
                                      "def login(form: OAuth2PasswordRequestForm):\n    pass\n")
            _write(proj / "requirements.txt", "fastapi\n")
            report = run_pre_flight_check(proj)
            hidden = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]
            self.assertTrue(any("multipart" in i.message.lower() for i in hidden))

    def test_no_issue_when_python_multipart_already_listed(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "auth.py", "from fastapi import Form\n"
                                      "def login(username: str = Form(...)):\n    pass\n")
            _write(proj / "requirements.txt", "fastapi\npython-multipart\n")
            report = run_pre_flight_check(proj)
            hidden = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]
            self.assertFalse(any("multipart" in i.message.lower() for i in hidden))

    def test_detects_unpinned_bcrypt_with_passlib_cryptcontext(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "security.py",
                   "from passlib.context import CryptContext\n"
                   "pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')\n")
            _write(proj / "requirements.txt", "passlib\nbcrypt\n")
            report = run_pre_flight_check(proj)
            hidden = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]
            self.assertTrue(any("bcrypt<4.1" in i.suggestion for i in hidden))

    def test_no_issue_when_bcrypt_pinned_below_4_1(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "security.py",
                   "from passlib.context import CryptContext\n"
                   "pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')\n")
            _write(proj / "requirements.txt", "passlib\nbcrypt<4.1\n")
            report = run_pre_flight_check(proj)
            hidden = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]
            self.assertFalse(any("bcrypt" in i.message.lower() for i in hidden))

    def test_hidden_runtime_dependency_is_not_blocking(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "database.py", "from sqlalchemy.ext.asyncio import create_async_engine\n"
                                          "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n")
            _write(proj / "requirements.txt", "sqlalchemy\n")
            report = run_pre_flight_check(proj)
            self.assertFalse(report.has_blocking_issues)


class TestRunPreFlightCheckMissingDependency(unittest.TestCase):
    """Tests fuer fehlende Drittanbieter-Abhaengigkeiten."""

    def test_detects_missing_third_party_package(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app.py", "import fastapi\n")
            _write(proj / "requirements.txt", "# leer - kein fastapi eingetragen\n")
            report = run_pre_flight_check(proj)
            dep_issues = [i for i in report.issues if i.issue_type == "missing_dependency"]
            self.assertTrue(len(dep_issues) >= 1)
            self.assertTrue(any("fastapi" in i.message.lower() for i in dep_issues))

    def test_no_issue_when_package_in_requirements(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app.py", "import fastapi\n")
            _write(proj / "requirements.txt", "fastapi>=0.100\n")
            report = run_pre_flight_check(proj)
            dep_issues = [i for i in report.issues if i.issue_type == "missing_dependency"]
            fastapi_issues = [i for i in dep_issues if "fastapi" in i.message.lower()]
            self.assertEqual(fastapi_issues, [])

    def test_stdlib_imports_never_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app.py",
                   "import os\nimport sys\nimport json\nimport asyncio\nimport pathlib\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            dep_issues = [i for i in report.issues if i.issue_type == "missing_dependency"]
            self.assertEqual(dep_issues, [], f"Stdlib should not be flagged: {dep_issues}")

    def test_deduplication_same_package_multiple_files(self):
        """Dasselbe fehlende Paket in 5 Dateien -> nur 1 Befund."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            # Verwende ein garantiert nicht-installiertes Paket (kein sys.modules-Eintrag)
            for i in range(5):
                _write(proj / f"module_{i}.py", "import xyzzy_nonexistent_testpkg_abc\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            issues = [
                i for i in report.issues
                if i.issue_type == "missing_dependency"
                and "xyzzy_nonexistent_testpkg_abc" in i.message.lower()
            ]
            self.assertEqual(len(issues), 1,
                             f"Expected dedup to 1 issue, got {len(issues)}: {report.issues}")

    def test_version_constraint_stripping_in_requirements(self):
        """requirements.txt mit Version-Constraints korrekt geparst."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app.py", "import pydantic\nimport httpx\n")
            _write(proj / "requirements.txt", "pydantic>=2.0,<3.0\nhttpx==0.24.1\n")
            report = run_pre_flight_check(proj)
            dep_issues = [i for i in report.issues if i.issue_type == "missing_dependency"]
            pydantic_issues = [i for i in dep_issues if "pydantic" in i.message.lower()]
            httpx_issues = [i for i in dep_issues if "httpx" in i.message.lower()]
            self.assertEqual(pydantic_issues, [], "pydantic is in requirements.txt")
            self.assertEqual(httpx_issues, [], "httpx is in requirements.txt")


class TestRunPreFlightCheckEdgeCases(unittest.TestCase):
    """Edge Cases: nicht-existentes Verzeichnis, leere Projekte, Skip-Dirs."""

    def test_nonexistent_directory_returns_error_not_exception(self):
        report = run_pre_flight_check("/this/does/not/exist/xyz123")
        self.assertFalse(report.passed)
        self.assertNotEqual(report.error, "")

    def test_empty_project_directory_passes(self):
        with tempfile.TemporaryDirectory() as d:
            report = run_pre_flight_check(d)
            self.assertTrue(report.passed)
            self.assertEqual(report.files_checked, 0)

    def test_skip_dirs_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            # Syntaxfehler in .venv - darf nicht erkannt werden
            _write(proj / ".venv" / "lib" / "bad.py", "def foo(:\n  pass\n")
            # Syntaxfehler in __pycache__ - darf nicht erkannt werden
            _write(proj / "__pycache__" / "cache.py", "def foo(:\n  pass\n")
            # Echte Datei - muss erkannt werden
            _write(proj / "good.py", "import os\n")
            report = run_pre_flight_check(proj)
            syntax_issues = [i for i in report.issues if i.issue_type == "syntax_error"]
            self.assertEqual(syntax_issues, [], f"Skip dirs should be ignored: {syntax_issues}")
            self.assertEqual(report.files_checked, 1)  # nur good.py

    def test_relative_imports_not_flagged(self):
        """Relative Importe (from . import X) sollen nie als fehlend markiert werden."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app" / "__init__.py", "")
            _write(proj / "app" / "module.py", "from . import utils\nfrom .models import User\n")
            _write(proj / "requirements.txt", "")
            report = run_pre_flight_check(proj)
            dep_issues = [i for i in report.issues if i.issue_type == "missing_dependency"]
            self.assertEqual(dep_issues, [], f"Relative imports should not be flagged: {dep_issues}")

    def test_multiple_requirements_files_parsed(self):
        """requirements-dev.txt wird zusaetzlich zu requirements.txt ausgelesen."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app.py", "import pytest\n")
            _write(proj / "requirements.txt", "")
            _write(proj / "requirements-dev.txt", "pytest>=7.0\n")
            report = run_pre_flight_check(proj)
            pytest_issues = [
                i for i in report.issues
                if i.issue_type == "missing_dependency" and "pytest" in i.message.lower()
            ]
            self.assertEqual(pytest_issues, [],
                             "pytest is in requirements-dev.txt and should not be flagged")


class TestFormatPreFlightIssuesForFix(unittest.TestCase):
    """Tests fuer die Fix-Auftrags-Formatierung."""

    def test_returns_empty_string_when_no_issues(self):
        report = PreFlightReport(project_dir="/tmp", files_checked=3)
        self.assertEqual(format_pre_flight_issues_for_fix(report), "")

    def test_contains_blocking_issues_section(self):
        report = PreFlightReport(project_dir="/tmp", files_checked=1)
        report.issues.append(
            PreFlightIssue(file="main.py", line=3, issue_type="syntax_error",
                           message="bad syntax", suggestion="fix parens")
        )
        text = format_pre_flight_issues_for_fix(report)
        self.assertIn("syntax_error", text)
        self.assertIn("fix parens", text)
        self.assertIn("Behebe AUSSCHLIESSLICH", text)

    def test_contains_dependency_section(self):
        report = PreFlightReport(project_dir="/tmp", files_checked=1)
        report.issues.append(
            PreFlightIssue(file="app.py", line=1, issue_type="missing_dependency",
                           message="Paket `fastapi` fehlt", suggestion="Fuege fastapi hinzu")
        )
        text = format_pre_flight_issues_for_fix(report)
        self.assertIn("fastapi", text)

    def test_limits_issues_to_ten_blocking(self):
        """Maximal 10 blockierende Befunde im Fix-Auftrag (verhindert Token-Flooding)."""
        report = PreFlightReport(project_dir="/tmp", files_checked=20)
        for i in range(15):
            report.issues.append(
                PreFlightIssue(file=f"file_{i}.py", line=1, issue_type="syntax_error",
                               message=f"error {i}")
            )
        text = format_pre_flight_issues_for_fix(report)
        # Maximal 10 Zeilen mit "syntax_error" im Output
        syntax_lines = [line for line in text.splitlines() if "syntax_error" in line]
        self.assertLessEqual(len(syntax_lines), 10)


class TestPreFlightCheckIntegration(unittest.TestCase):
    """Integrations-Tests mit realistischen Projekt-Strukturen."""

    def test_typical_fastapi_project_with_all_requirements(self):
        """Realistisches FastAPI-Projekt mit vollstaendiger requirements.txt - kein Issue."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj / "app" / "__init__.py", "")
            _write(proj / "app" / "main.py",
                   "from fastapi import FastAPI\nfrom .models import User\napp = FastAPI()\n")
            _write(proj / "app" / "models.py",
                   "from pydantic import BaseModel\nclass User(BaseModel):\n    name: str\n")
            _write(proj / "requirements.txt", "fastapi>=0.100\npydantic>=2.0\nuvicorn\n")
            report = run_pre_flight_check(proj)
            dep_issues = [i for i in report.issues if i.issue_type == "missing_dependency"]
            init_issues = [i for i in report.issues if i.issue_type == "missing_init"]
            self.assertEqual(dep_issues, [], f"No dep issues expected: {dep_issues}")
            self.assertEqual(init_issues, [], f"No init issues expected: {init_issues}")

    def test_project_missing_init_and_dependency(self):
        """Paket ohne __init__.py UND fehlendes Drittanbieter-Paket."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            # Verwende ein garantiert nicht-installiertes Paket fuer den dep-Check
            _write(proj / "myapp" / "routes.py",
                   "import xyzzy_nonexistent_dep_xyz\nfrom myapp.models import User\n")
            _write(proj / "requirements.txt", "")  # xyzzy_nonexistent_dep_xyz fehlt
            report = run_pre_flight_check(proj)
            issue_types = {i.issue_type for i in report.issues}
            self.assertIn("missing_init", issue_types)
            self.assertIn("missing_dependency", issue_types)
            dep = next(
                (i for i in report.issues
                 if i.issue_type == "missing_dependency"
                 and "xyzzy_nonexistent_dep_xyz" in i.message.lower()),
                None
            )
            self.assertIsNotNone(dep)


if __name__ == "__main__":
    unittest.main()
