"""
tests/test_verifier_dev_dependency_sync.py – Testet die Sandbox-Dependency-Synchronisation
(core/verifier/environment.py, core/verifier/security.py)

Realer Fund (Nutzerauftrag): der Tester-Agent legt Testabhängigkeiten (httpx,
pytest-asyncio) oft in requirements-dev.txt statt requirements.txt ab. `_requirements_files()`
installierte diese bereits korrekt in der Sandbox-venv (core/verifier/environment.py), aber
`check_dependency_vulnerabilities()` prüfte trotzdem nur die ERSTE gefundene Requirements-Datei
gegen die CVE-Datenbank – Testabhängigkeiten wie httpx blieben so unbemerkt von jedem
Sicherheits-Scan ausgeschlossen. Testet außerdem, dass core/manifest_guard.py bereits als
gültig anerkannte Requirements-Dateinamen (requirements-test.txt/requirements-prod.txt) jetzt
auch von der Sandbox-Installation/dem Audit erfasst werden, nicht nur requirements.txt/-dev.txt.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


class TestRequirementsFileDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_recognizes_all_manifest_guard_python_requirement_names(self):
        """Dieselben Namen, die core/manifest_guard.py._PYTHON_REQUIREMENTS_MANIFESTS bereits
        als gültige Python-Requirements-Dateien anerkennt, müssen auch hier gefunden werden -
        sonst installiert/scannt die Sandbox eine vom Korruptions-Schutz akzeptierte Datei nie."""
        (self.project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (self.project_dir / "requirements-dev.txt").write_text("httpx\n", encoding="utf-8")
        (self.project_dir / "requirements-test.txt").write_text("pytest-asyncio\n", encoding="utf-8")
        (self.project_dir / "requirements-prod.txt").write_text("gunicorn\n", encoding="utf-8")

        verifier = ProjectVerifier(self.project_dir)
        found_names = {f.name for f in verifier._requirements_files()}

        self.assertEqual(
            found_names,
            {"requirements.txt", "requirements-dev.txt", "requirements-test.txt", "requirements-prod.txt"},
        )

    def test_ignores_empty_requirements_files(self):
        (self.project_dir / "requirements.txt").write_text("", encoding="utf-8")
        verifier = ProjectVerifier(self.project_dir)
        self.assertEqual(verifier._requirements_files(), [])


class TestDependencyAuditCoversAllRequirementsFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "requirements.txt").write_text("fastapi==0.100.0\n", encoding="utf-8")
        (self.project_dir / "requirements-dev.txt").write_text("httpx==0.23.0\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-audit")
    def test_pip_audit_receives_every_requirements_file(self, mock_which, mock_run):
        """pip-audit muss -r für JEDE gefundene Requirements-Datei bekommen (wiederholbares
        Flag) - ein Aufruf nur mit requirements.txt würde Testabhängigkeiten aus
        requirements-dev.txt (z.B. httpx) unbemerkt von der CVE-Prüfung ausschließen."""
        mock_run.return_value = ExecutionResult(
            exit_code=0, stdout='{"dependencies": []}', stderr="", duration_seconds=0.1,
        )
        verifier = ProjectVerifier(self.project_dir)

        verifier.check_dependency_vulnerabilities()

        mock_run.assert_called_once()
        command = mock_run.call_args[0][0]
        self.assertEqual(command[0], "pip-audit")
        r_args = [command[i + 1] for i, arg in enumerate(command) if arg == "-r"]
        r_names = {Path(p).name for p in r_args}
        self.assertEqual(r_names, {"requirements.txt", "requirements-dev.txt"})


class TestBanditExcludesTestNoiseButNotRealFindings(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "app.py").write_text("import subprocess\n", encoding="utf-8")
        (self.project_dir / "tests").mkdir()
        (self.project_dir / "tests" / "test_app.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/bandit")
    def test_skips_b101_and_excludes_tests_dir(self, mock_which, mock_run):
        """B101 (assert-used) ist bei pytest-Testdateien das vom Team selbst vorgeschriebene
        Idiom (agents/tester_agent.py), keine echte Sicherheitslücke - `-s B101` UND der
        Ausschluss des tests/-Verzeichnisses verhindern den False-Positive doppelt."""
        mock_run.return_value = ExecutionResult(
            exit_code=0, stdout='{"errors": [], "results": []}', stderr="", duration_seconds=0.1,
        )
        verifier = ProjectVerifier(self.project_dir)

        verifier.check_sast()

        command = mock_run.call_args[0][0]
        self.assertIn("-s", command)
        self.assertEqual(command[command.index("-s") + 1], "B101")
        exclude_value = command[command.index("-x") + 1]
        self.assertIn(str(self.project_dir / "tests"), exclude_value.split(","))
        # Echte Sicherheitsregeln bleiben unberührt - bandit wird weiterhin rekursiv auf das
        # gesamte Projekt losgelassen, nur B101 wird projektweit übersprungen.
        self.assertEqual(command[:3], ["bandit", "-r", str(self.project_dir)])


if __name__ == "__main__":
    unittest.main()
