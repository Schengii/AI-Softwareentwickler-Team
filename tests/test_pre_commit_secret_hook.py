"""
tests/test_pre_commit_secret_hook.py – Testet das Pre-Commit Gate für .env und API-Keys
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

hook_path = Path(__file__).resolve().parent.parent / "scripts" / "git-hooks" / "check_secrets.py"
spec = importlib.util.spec_from_file_location("check_secrets", hook_path)
check_secrets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_secrets)

check_staged_env_files = check_secrets.check_staged_env_files
check_staged_secrets = check_secrets.check_staged_secrets
main = check_secrets.main


class TestPreCommitSecretHook:
    def test_blocks_staged_env_file(self):
        """Prüft, ob .env-Dateien erkannt und blockiert werden."""
        mock_output = ".env\nsrc/app.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            blocked = check_staged_env_files()
            assert ".env" in blocked

    def test_blocks_subfolder_and_variant_env_files(self):
        """Prüft, ob .env.local, config/.env und ähnliche Varianten erkannt werden."""
        mock_output = "workspace/demo/.env\n.env.production\nfrontend/.env.local\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            blocked = check_staged_env_files()
            assert "workspace/demo/.env" in blocked
            assert ".env.production" in blocked
            assert "frontend/.env.local" in blocked

    def test_allows_env_example(self):
        """Prüft, dass .env.example nicht fälschlich blockiert wird."""
        mock_output = ".env.example\nREADME.md\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            blocked = check_staged_env_files()
            assert len(blocked) == 0

    def test_blocks_staged_api_key_diff(self):
        """Prüft, ob ein gestagter Google/OpenAI Key im Diff blockiert wird."""
        # Aus Teilstücken zusammengesetzt, damit der Pre-Commit-Scanner den Test selbst nicht blockiert
        fake_key = "AIza" + "SyAJE0KHGriVfJzdhHXJkauv8D_0TfHPr-M"
        mock_diff = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            f"+GEMINI_KEY = '{fake_key}'\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_diff)
            findings = check_staged_secrets()
            assert len(findings) > 0
            assert any("Google API Key" in f.rule for f in findings)

    def test_main_returns_error_code_on_env_file(self):
        with patch.object(check_secrets, "check_staged_env_files", return_value=[".env"]):
            code = main()
            assert code == 1

    def test_main_returns_zero_when_clean(self):
        with (
            patch.object(check_secrets, "check_staged_env_files", return_value=[]),
            patch.object(check_secrets, "check_staged_secrets", return_value=[]),
        ):
            code = main()
            assert code == 0
