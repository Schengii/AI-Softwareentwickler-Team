"""
tests/test_p0_structured_verification.py – Regressionstests für die P0-Funde der Team-Analyse 2026-09-15:

1. Pre-Flight schlug `jwt` statt `PyJWT` vor (zwei auseinanderlaufende Zuordnungstabellen).
2. Die Definition of Done ließ ungeprüfte Pflichtkriterien durch (`is_done=True` bei roter Verifikation).
3. Status wurde per Textsuche aus dem Markdown-Protokoll gelesen (`ui_ok` konnte nie True werden).
4. Test-/Werkzeugpakete landeten in den Produktions-Abhängigkeiten.
5. Fehlerprotokolle wurden mitten im Satz auf 500 Zeichen gekappt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.definition_of_done import build_definition_of_done
from core.dependency_manifest import add_requirement, manifest_for_package, package_from_finding
from core.known_pitfalls import IMPORT_TO_PACKAGE, is_dev_only_package, is_test_path, package_for_import
from core.pre_flight_check import run_pre_flight_check
from core.project_status import read_full_detail, read_status, record_run, truncate_on_line_boundary
from core.secret_scanner import scan_directory
from core.verification_outcome import CHECK_KEYS, VerificationOutcome, parse_install_exit_code
from core.verifier.models import _IMPORT_TO_PACKAGE_NAME


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestPackageNameResolution:
    def test_jwt_import_suggests_pyjwt_not_toxic_jwt(self, tmp_path):
        _write(tmp_path / "app" / "__init__.py", "")
        _write(tmp_path / "app" / "auth.py", "import jwt\n")
        _write(tmp_path / "requirements.txt", "fastapi\n")
        report = run_pre_flight_check(tmp_path)
        dep = [i for i in report.issues if i.issue_type == "missing_dependency"]
        assert len(dep) == 1
        assert package_from_finding(dep[0].suggestion) == "PyJWT"

    @pytest.mark.parametrize("import_name,package", [("yaml", "pyyaml"), ("PIL", "pillow"), ("cv2", "opencv-python")])
    def test_suggestion_uses_real_pypi_name(self, tmp_path, import_name, package):
        _write(tmp_path / "tool.py", f"import {import_name}\n")
        _write(tmp_path / "requirements.txt", "\n")
        report = run_pre_flight_check(tmp_path)
        suggestions = [package_from_finding(i.suggestion) for i in report.issues if i.issue_type == "missing_dependency"]
        assert package in suggestions

    def test_verifier_map_is_derived_from_single_registry(self):
        assert set(_IMPORT_TO_PACKAGE_NAME) == set(IMPORT_TO_PACKAGE)
        assert _IMPORT_TO_PACKAGE_NAME["jwt"] == "pyjwt"

    def test_transitive_namespace_not_flagged_but_framework_process_modules_are_irrelevant(self, tmp_path):
        # starlette kommt mit fastapi; `rich` ist im Framework-Prozess geladen, im Projekt aber nicht deklariert.
        _write(tmp_path / "main.py", "from starlette.responses import JSONResponse\nimport rich\n")
        _write(tmp_path / "requirements.txt", "fastapi\n")
        report = run_pre_flight_check(tmp_path)
        flagged = {package_from_finding(i.suggestion) for i in report.issues if i.issue_type == "missing_dependency"}
        assert "starlette" not in flagged
        assert "rich" in flagged

    def test_package_for_import_fallback(self):
        assert package_for_import("some_pkg.sub") == "some-pkg"


class TestDevDependencyRouting:
    def test_dev_only_and_test_paths(self):
        assert is_dev_only_package("pytest-asyncio") and is_dev_only_package("Locust")
        assert not is_dev_only_package("fastapi")
        assert is_test_path("tests/test_api.py") and is_test_path("app/conftest.py")
        assert not is_test_path("app/testing_utils.py")

    def test_manifest_for_package_routes_test_imports_to_dev_manifest(self, tmp_path):
        _write(tmp_path / "requirements.txt", "fastapi\n")
        assert manifest_for_package(tmp_path, "locust").name == "requirements-dev.txt"
        assert manifest_for_package(tmp_path, "respx", "tests/test_client.py").name == "requirements-dev.txt"
        assert manifest_for_package(tmp_path, "httpx", "app/client.py").name == "requirements.txt"

    def test_runtime_import_wins_over_earlier_test_import(self, tmp_path):
        _write(tmp_path / "requirements.txt", "\n")
        _write(tmp_path / "a_tests" / "placeholder.txt", "")
        _write(tmp_path / "tests" / "test_x.py", "import httpx\n")
        _write(tmp_path / "zz_app.py", "import httpx\n")
        report = run_pre_flight_check(tmp_path)
        issue = next(i for i in report.issues if i.issue_type == "missing_dependency" and "httpx" in i.message)
        target = manifest_for_package(tmp_path, package_from_finding(issue.suggestion), issue.file)
        assert target.name == "requirements.txt"

    def test_no_manifest_is_never_created(self, tmp_path):
        assert manifest_for_package(tmp_path, "pytest") is None

    def test_add_to_dev_manifest_creates_it(self, tmp_path):
        _write(tmp_path / "requirements.txt", "fastapi\n")
        target = manifest_for_package(tmp_path, "pytest")
        assert add_requirement(target, "pytest")
        assert "pytest" in (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8")
        assert "pytest" not in (tmp_path / "requirements.txt").read_text(encoding="utf-8")


class TestVerificationOutcome:
    def test_record_and_status(self):
        outcome = VerificationOutcome()
        outcome.record("tests", True)
        outcome.record("frontend_build", False, "TS1127")
        outcome.record("browser_ui", None)
        assert outcome.status("tests") is True
        assert outcome.status("frontend_build") is False
        assert outcome.status("browser_ui") is None and not outcome.ran("browser_ui")
        assert outcome.failed_checks == ["frontend_build"]

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError):
            VerificationOutcome().record("testz", True)

    def test_roundtrip(self):
        outcome = VerificationOutcome(skipped_reason="Budget")
        for key in sorted(CHECK_KEYS)[:3]:
            outcome.record(key, False, "x")
        again = VerificationOutcome.from_dict(json.loads(json.dumps(outcome.to_dict())))
        assert again.to_dict() == outcome.to_dict()

    @pytest.mark.parametrize("log,expected", [
        ("✅ pip install -r requirements.txt (exit_code=0)", 0),
        ("✅ pip (exit_code=0)\n⚠️ npm install (exit_code=1)", 1),
        ("keine Installation", None),
        (None, None),
    ])
    def test_parse_install_exit_code(self, log, expected):
        assert parse_install_exit_code(log) == expected


class TestDefinitionOfDoneHonesty:
    def _dod(self, tmp_path, **kwargs):
        _write(tmp_path / "app" / "main.py", "app = object()\n")
        _write(tmp_path / "tests" / "test_x.py", "def test_x():\n    assert True\n")
        base = {"files_written": 3, "tests_ran": True, "tests_passed": True, "user_request": "Baue eine API"}
        base.update(kwargs)
        return build_definition_of_done("p", tmp_path, **base)

    def test_red_verification_is_never_done(self, tmp_path):
        dod = self._dod(tmp_path, verification_ok=False, failed_checks=["frontend_build"])
        assert not dod.is_done
        assert "verification_ok" in [c.key for c in dod.blocking_criteria]

    def test_failed_build_blocks(self, tmp_path):
        dod = self._dod(tmp_path, build_passes=False, verification_ok=False)
        assert "build_passes" in [c.key for c in dod.blocking_criteria]

    def test_failed_ui_blocks_when_frontend_was_planned(self, tmp_path):
        _write(tmp_path / "static" / "index.html", "<html></html>")
        assert "ui_ok" in [c.key for c in self._dod(tmp_path, ui_ok=False, frontend_planned=True).blocking_criteria]
        assert "ui_ok" not in [c.key for c in self._dod(tmp_path, ui_ok=False, frontend_planned=False).blocking_criteria]

    def test_green_run_with_all_checks_is_done(self, tmp_path):
        dod = self._dod(tmp_path, deps_installable=True, app_starts=True, secrets_clean=True, verification_ok=True)
        assert dod.is_done

    def test_skipped_verification_does_not_add_verification_veto(self, tmp_path):
        dod = self._dod(tmp_path, tests_ran=False, tests_passed=False, verification_ok=False, verification_skipped=True)
        assert "verification_ok" not in [c.key for c in dod.criteria]


class TestSecretScanDirectory:
    def test_finds_hardcoded_secret_but_ignores_tests_and_env_example(self, tmp_path):
        _write(tmp_path / "app" / "config.py", 'SECRET_KEY = "a8f5f167f44f4964e6c998dee827110c"\n')
        _write(tmp_path / "tests" / "test_auth.py", 'password = "supersecretpassword123"\n')
        _write(tmp_path / ".env.example", "SECRET_KEY=abcdefghijklmnopqrstuvwxyz\n")
        findings = scan_directory(tmp_path)
        assert [f.file_path for f in findings] == ["app/config.py"]

    def test_clean_project(self, tmp_path):
        _write(tmp_path / "app" / "config.py", 'SECRET_KEY = os.environ["SECRET_KEY"]\n')
        assert scan_directory(tmp_path) == []


class TestFullProtocolPersistence:
    def test_truncation_happens_on_line_boundary(self):
        text = "\n".join(f"- Zeile {i}: " + "x" * 40 for i in range(30))
        short = truncate_on_line_boundary(text, 200)
        assert len(short) <= 200
        assert short.splitlines()[-1].startswith("…")
        assert all(line.startswith("- Zeile") for line in short.splitlines()[:-1])

    def test_full_protocol_file_and_failed_checks(self, tmp_path):
        summary = "### Protokoll\n" + "\n".join(f"- Schritt {i}: " + "y" * 60 for i in range(40))
        outcome = VerificationOutcome()
        outcome.record("tests", False, "3 Testfehler")
        record_run(str(tmp_path), "Aufgabe", False, False, 5, verification_summary=summary,
                   verification_outcome=outcome.to_dict(), run_stamp="20260915_120000")
        entry = read_status(str(tmp_path))[0]
        assert entry["failed_checks"] == ["tests"]
        assert entry["detail_file"] == ".ai_team_runs/20260915_120000_verification.md"
        full = read_full_detail(str(tmp_path), entry)
        assert "Schritt 39" in full and '"tests"' in full
        assert len(entry["failure_detail"]) <= 500
