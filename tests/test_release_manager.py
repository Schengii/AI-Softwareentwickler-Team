"""
tests/test_release_manager.py – Testet core/release_manager.py (automatisches Release-Tagging
für generierte Projekte nach einem echten Merge)

Realer struktureller Fund: der PR-Workflow deckt Feature-Branch -> Pull Request -> Merge
vollständig ab, aber danach passierte bisher nichts mehr – ein echtes Team markiert einen
gemergten Meilenstein als Release (Versions-Tag + Release-Notes). Die `gh`-CLI ist in der
CI-Testumgebung nicht installiert – alle Aufrufe werden über `agents.github_agent.subprocess.run`
bzw. `core.release_manager.subprocess.run` gemockt.
"""

import base64
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from core.release_manager import tag_release, update_project_changelog


class TestTagRelease(unittest.TestCase):
    def setUp(self):
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        # update_project_changelog() (neuer, zusätzlicher Best-Effort-Schritt nach einem
        # erfolgreichen Release) soll in diesen bestehenden Tests sofort no-open, ohne
        # weitere subprocess.run-Aufrufe - die side_effect-Listen unten decken bewusst nur
        # die beiden ursprünglichen Aufrufe (release list/create) ab, siehe
        # TestUpdateProjectChangelog unten für die dedizierten Tests dieses Schritts.
        self.fake_github.get_repo_slug.return_value = None

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


class TestUpdateProjectChangelog(unittest.TestCase):
    def setUp(self):
        self.fake_github = MagicMock()
        self.fake_github.get_repo_slug.return_value = "x/y"

    def test_returns_false_without_repo_slug(self):
        self.fake_github.get_repo_slug.return_value = None
        success, reason = update_project_changelog(
            "notizen_api", "notizen_api-v0.1.0", "Feature X", github_agent=self.fake_github,
        )
        self.assertFalse(success)
        self.assertIn("Remote", reason)

    @patch("core.release_manager.subprocess.run")
    def test_creates_fresh_file_with_header_when_none_exists(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="404 Not Found"),  # gh api GET -> Datei existiert nicht
            MagicMock(returncode=0, stdout="{}", stderr=""),  # gh api PUT
        ]
        success, _reason = update_project_changelog(
            "notizen_api", "notizen_api-v0.1.0", "Erstes Feature",
            pr_url="https://github.com/x/y/pull/1", github_agent=self.fake_github,
        )

        self.assertTrue(success)
        put_call_args = mock_run.call_args_list[1][0][0]
        self.assertEqual(put_call_args[:4], ["gh", "api", "--method", "PUT"])
        self.assertIn("repos/x/y/contents/workspace/notizen_api/CHANGELOG.md", put_call_args)
        payload = json.loads(mock_run.call_args_list[1][1]["input"])
        self.assertNotIn("sha", payload)  # neue Datei - kein sha zum Überschreiben nötig
        decoded = base64.b64decode(payload["content"]).decode("utf-8")
        self.assertIn("# Changelog", decoded)
        self.assertIn("notizen_api-v0.1.0", decoded)
        self.assertIn("Erstes Feature", decoded)
        self.assertIn("https://github.com/x/y/pull/1", decoded)

    @patch("core.release_manager.subprocess.run")
    def test_prepends_new_entry_after_header_and_includes_sha_when_file_exists(self, mock_run):
        existing = (
            "# Changelog\n\n"
            "Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert, neueste zuerst.\n"
            "Automatisch gepflegt durch core/release_manager.py bei jedem gemergten Release.\n"
            "\n## notizen_api-v0.1.0 - 2024-01-01\n- Erstes Feature\n"
        )
        get_response = json.dumps({
            "content": base64.b64encode(existing.encode("utf-8")).decode("ascii"), "sha": "abc123",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=get_response, stderr=""),
            MagicMock(returncode=0, stdout="{}", stderr=""),
        ]
        success, _reason = update_project_changelog(
            "notizen_api", "notizen_api-v0.1.1", "Zweites Feature", github_agent=self.fake_github,
        )

        self.assertTrue(success)
        payload = json.loads(mock_run.call_args_list[1][1]["input"])
        self.assertEqual(payload["sha"], "abc123")
        decoded = base64.b64decode(payload["content"]).decode("utf-8")
        # Neuer Eintrag steht VOR dem alten (neueste zuerst) und der alte bleibt vollständig erhalten.
        self.assertLess(decoded.index("notizen_api-v0.1.1"), decoded.index("notizen_api-v0.1.0"))
        self.assertIn("Zweites Feature", decoded)
        self.assertIn("Erstes Feature", decoded)

    @patch("core.release_manager.subprocess.run")
    def test_foreign_header_is_never_overwritten_new_entry_is_just_prepended(self, mock_run):
        existing = "# Changelog\n\nVon Hand gepflegt, anderes Format.\n\n## v1.0\n- Alt\n"
        get_response = json.dumps({
            "content": base64.b64encode(existing.encode("utf-8")).decode("ascii"), "sha": "abc123",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=get_response, stderr=""),
            MagicMock(returncode=0, stdout="{}", stderr=""),
        ]
        update_project_changelog("notizen_api", "notizen_api-v0.1.0", "Neu", github_agent=self.fake_github)

        payload = json.loads(mock_run.call_args_list[1][1]["input"])
        decoded = base64.b64decode(payload["content"]).decode("utf-8")
        self.assertIn("Von Hand gepflegt, anderes Format.", decoded)
        self.assertLess(decoded.index("notizen_api-v0.1.0"), decoded.index("Von Hand gepflegt"))

    @patch("core.release_manager.subprocess.run")
    def test_put_failure_is_reported_not_crashed(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="404 Not Found"),
            MagicMock(returncode=1, stdout="", stderr="422 Unprocessable Entity"),
        ]
        success, reason = update_project_changelog(
            "notizen_api", "notizen_api-v0.1.0", "Feature", github_agent=self.fake_github,
        )
        self.assertFalse(success)
        self.assertIn("422", reason)

    @patch("core.release_manager.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 20))
    def test_timeout_does_not_crash(self, _mock_run):
        success, _reason = update_project_changelog(
            "notizen_api", "notizen_api-v0.1.0", "Feature", github_agent=self.fake_github,
        )
        self.assertFalse(success)


class TestTagReleaseUpdatesChangelog(unittest.TestCase):
    """tag_release() ruft nach einem erfolgreichen Release zusätzlich update_project_changelog()
    auf - ein fehlgeschlagenes CHANGELOG-Update darf das bereits erfolgreiche Release-Tagging
    dabei NIE nachträglich als Fehlschlag melden (Best-Effort-Prinzip, siehe Modul-Docstring)."""

    @patch("core.release_manager.subprocess.run")
    def test_successful_release_also_updates_changelog(self, mock_run):
        fake_github = MagicMock()
        fake_github.gh_ready.return_value = True
        fake_github.get_repo_slug.return_value = "x/y"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),  # gh release list
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.0\n", stderr=""),  # gh release create
            MagicMock(returncode=1, stdout="", stderr="404 Not Found"),  # gh api GET (CHANGELOG.md existiert noch nicht)
            MagicMock(returncode=0, stdout="{}", stderr=""),  # gh api PUT
        ]

        success, url = tag_release("notizen_api", "Feature X", github_agent=fake_github)

        self.assertTrue(success)
        self.assertEqual(url, "https://github.com/x/y/releases/tag/notizen_api-v0.1.0")
        self.assertEqual(mock_run.call_count, 4)
        changelog_put_args = mock_run.call_args_list[3][0][0]
        self.assertIn("repos/x/y/contents/workspace/notizen_api/CHANGELOG.md", changelog_put_args)

    @patch("core.release_manager.subprocess.run")
    def test_failed_changelog_update_does_not_flip_release_success(self, mock_run):
        fake_github = MagicMock()
        fake_github.gh_ready.return_value = True
        fake_github.get_repo_slug.return_value = "x/y"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),
            MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/notizen_api-v0.1.0\n", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="network error"),  # gh api GET schlägt fehl
            MagicMock(returncode=1, stdout="", stderr="network error"),  # gh api PUT schlägt ebenfalls fehl
        ]

        success, url = tag_release("notizen_api", "Feature X", github_agent=fake_github)

        self.assertTrue(success)  # Release selbst bleibt erfolgreich
        self.assertEqual(url, "https://github.com/x/y/releases/tag/notizen_api-v0.1.0")


if __name__ == "__main__":
    unittest.main()
