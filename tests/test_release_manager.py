"""
tests/test_release_manager.py – Testet core/release_manager.py (automatisches Release-Tagging
für generierte Projekte nach einem echten Merge)

Realer struktureller Fund: der PR-Workflow deckt Feature-Branch -> Pull Request -> Merge
vollständig ab, aber danach passierte bisher nichts mehr – ein echtes Team markiert einen
gemergten Meilenstein als Release (Versions-Tag + Release-Notes). Die `gh`-CLI ist in der
CI-Testumgebung nicht installiert – alle Aufrufe werden über `agents.github_agent.subprocess.run`
bzw. `core.release_manager.subprocess.run` gemockt.
"""

import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from core.release_manager import tag_release


class TestTagRelease(unittest.TestCase):
    def setUp(self):
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True

    def test_returns_false_when_gh_not_ready(self):
        self.fake_github.gh_ready.return_value = False
        success, reason = tag_release("notizen_api", "Feature X", github_agent=self.fake_github)
        self.assertFalse(success)
        self.assertIn("gh", reason)

    @patch("core.release_manager.subprocess.run")
    def test_first_release_starts_at_v0_1_0(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),  # gh release list -> keine vorhandenen
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.0\n", stderr=""),
        ]
        success, url = tag_release("notizen_api", "Erstes Feature", github_agent=self.fake_github)

        self.assertTrue(success)
        self.assertEqual(url, "https://github.com/x/y/releases/tag/notizen_api-v0.1.0")
        create_call_args = mock_run.call_args_list[1][0][0]
        self.assertEqual(create_call_args[:3], ["gh", "release", "create"])
        self.assertIn("notizen_api-v0.1.0", create_call_args)

    @patch("core.release_manager.subprocess.run")
    def test_increments_patch_version_from_existing_matching_releases(self, mock_run):
        existing = json.dumps([
            {"tagName": "notizen_api-v0.1.0"},
            {"tagName": "notizen_api-v0.1.2"},  # höchste vorhandene Patch-Version
            {"tagName": "notizen_api-v0.1.1"},
            {"tagName": "anderes_projekt-v0.9.0"},  # anderes Projekt - darf nicht mitzählen
        ])
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=existing, stderr=""),
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.3\n", stderr=""),
        ]
        success, url = tag_release("notizen_api", "Bugfix", github_agent=self.fake_github)

        self.assertTrue(success)
        create_call_args = mock_run.call_args_list[1][0][0]
        self.assertIn("notizen_api-v0.1.3", create_call_args)

    @patch("core.release_manager.subprocess.run")
    def test_release_list_failure_falls_back_to_v0_1_0(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="network error"),
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.0\n", stderr=""),
        ]
        success, _url = tag_release("notizen_api", "Feature", github_agent=self.fake_github)
        self.assertTrue(success)
        create_call_args = mock_run.call_args_list[1][0][0]
        self.assertIn("notizen_api-v0.1.0", create_call_args)

    @patch("core.release_manager.subprocess.run")
    def test_malformed_release_list_json_falls_back_to_v0_1_0(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="not json", stderr=""),
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.0\n", stderr=""),
        ]
        success, _url = tag_release("notizen_api", "Feature", github_agent=self.fake_github)
        self.assertTrue(success)

    @patch("core.release_manager.subprocess.run")
    def test_reports_failure_when_release_create_fails(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="HTTP 422: tag already exists"),
        ]
        success, reason = tag_release("notizen_api", "Feature", github_agent=self.fake_github)
        self.assertFalse(success)
        self.assertIn("tag already exists", reason)

    @patch("core.release_manager.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 30))
    def test_timeout_does_not_crash(self, _mock_run):
        success, _reason = tag_release("notizen_api", "Feature", github_agent=self.fake_github)
        self.assertFalse(success)

    @patch("core.release_manager.subprocess.run")
    def test_notes_include_ticket_title_and_pr_url(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.0\n", stderr=""),
        ]
        tag_release("notizen_api", "Notiz-Feature X", pr_url="https://github.com/x/y/pull/9", github_agent=self.fake_github)

        create_call_args = mock_run.call_args_list[1][0][0]
        notes_index = create_call_args.index("--notes") + 1
        notes = create_call_args[notes_index]
        self.assertIn("Notiz-Feature X", notes)
        self.assertIn("https://github.com/x/y/pull/9", notes)


if __name__ == "__main__":
    unittest.main()
