"""
tests/test_github_agent_post_pr_review.py – Testet GitHubAgent.post_pr_review()

KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-Kommentare: core_reviewer/security/
compliance-Funde (core/review_gate.py.ReviewFinding), die auch nach dem automatischen Fix-Loop
noch kritisch sind, landeten bisher NUR als Fließtext im PR-Body - post_pr_review() hinterlässt
stattdessen einen echten GitHub-PR-Review (`gh api .../pulls/<nr>/reviews`), mit Inline-
Kommentaren für Funde mit bekanntem file_path+line_number.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from agents.github_agent import GitHubAgent
from core.review_gate import ReviewFinding


def _repo_view_result() -> MagicMock:
    return MagicMock(returncode=0, stdout=json.dumps({"nameWithOwner": "acme/widget"}), stderr="")


def _pr_view_result(number: int = 42) -> MagicMock:
    return MagicMock(returncode=0, stdout=json.dumps({"number": number}), stderr="")


class TestPostPrReview(unittest.TestCase):
    def setUp(self):
        self.agent = GitHubAgent()

    def test_empty_findings_is_a_noop_success_without_any_gh_call(self):
        with patch("agents.github_agent.subprocess.run") as mock_run:
            success, output = self.agent.post_pr_review("https://github.com/x/y/pull/1", [])
        self.assertTrue(success)
        mock_run.assert_not_called()

    def test_missing_repo_slug_fails_without_gh_pr_view_call(self):
        with patch.object(self.agent, "get_repo_slug", return_value=None), \
             patch("agents.github_agent.subprocess.run") as mock_run:
            success, output = self.agent.post_pr_review(
                "1", [ReviewFinding(severity="critical", title="X")],
            )
        self.assertFalse(success)
        self.assertIn("Remote", output)
        mock_run.assert_not_called()

    def test_finding_with_file_and_line_becomes_inline_comment(self):
        finding = ReviewFinding(
            severity="critical", source_role="security", file_path="app/auth.py",
            line_number=17, title="Hartcodiertes Secret", description="SECRET_KEY im Klartext.",
        )
        review_post_result = MagicMock(returncode=0, stdout='{"id": 1}', stderr="")
        with patch.object(self.agent, "get_repo_slug", return_value="acme/widget"), \
             patch("agents.github_agent.subprocess.run", side_effect=[_pr_view_result(), review_post_result]) as mock_run:
            success, output = self.agent.post_pr_review("https://github.com/acme/widget/pull/42", [finding])

        self.assertTrue(success)
        review_call = mock_run.call_args_list[-1]
        self.assertEqual(review_call.args[0][:4], ["gh", "api", "--method", "POST"])
        self.assertIn("repos/acme/widget/pulls/42/reviews", review_call.args[0])
        payload = json.loads(review_call.kwargs["input"])
        self.assertEqual(payload["event"], "COMMENT")
        self.assertEqual(len(payload["comments"]), 1)
        self.assertEqual(payload["comments"][0]["path"], "app/auth.py")
        self.assertEqual(payload["comments"][0]["line"], 17)
        self.assertEqual(payload["comments"][0]["side"], "RIGHT")
        self.assertIn("Hartcodiertes Secret", payload["comments"][0]["body"])

    def test_finding_without_location_goes_into_general_body_not_inline_comments(self):
        finding = ReviewFinding(severity="warning", source_role="compliance", title="Fehlende Lizenzdatei")
        review_post_result = MagicMock(returncode=0, stdout="{}", stderr="")
        with patch.object(self.agent, "get_repo_slug", return_value="acme/widget"), \
             patch("agents.github_agent.subprocess.run", side_effect=[_pr_view_result(), review_post_result]) as mock_run:
            success, output = self.agent.post_pr_review("42", [finding])

        self.assertTrue(success)
        payload = json.loads(mock_run.call_args_list[-1].kwargs["input"])
        self.assertNotIn("comments", payload)
        self.assertIn("Fehlende Lizenzdatei", payload["body"])

    def test_inline_comments_rejected_falls_back_to_text_only_review(self):
        """GitHub lehnt einen Inline-Kommentar ab, wenn `line` nicht Teil des aktuellen Diffs ist
        - der best-effort aus Freitext extrahierte line_number ist das nicht immer. Ein
        Fehlschlag MIT comments muss automatisch einen zweiten Versuch OHNE comments auslösen,
        statt komplett ohne jede Rückmeldung auf dem PR zu enden."""
        finding = ReviewFinding(
            severity="critical", source_role="security", file_path="app/auth.py",
            line_number=999, title="X", description="Y",
        )
        rejected = MagicMock(returncode=1, stdout="", stderr="422 line must be part of the diff")
        accepted = MagicMock(returncode=0, stdout="{}", stderr="")
        with patch.object(self.agent, "get_repo_slug", return_value="acme/widget"), \
             patch("agents.github_agent.subprocess.run", side_effect=[_pr_view_result(), rejected, accepted]) as mock_run:
            success, output = self.agent.post_pr_review("42", [finding])

        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 3)  # pr view + fehlgeschlagener Versuch + Fallback
        fallback_payload = json.loads(mock_run.call_args_list[-1].kwargs["input"])
        self.assertNotIn("comments", fallback_payload)
        self.assertIn("Text-Review ohne Inline-Kommentare", output)

    def test_both_attempts_failing_is_reported_without_raising(self):
        finding = ReviewFinding(
            severity="critical", source_role="security", file_path="app/auth.py",
            line_number=999, title="X", description="Y",
        )
        rejected = MagicMock(returncode=1, stdout="", stderr="422 rejected")
        with patch.object(self.agent, "get_repo_slug", return_value="acme/widget"), \
             patch("agents.github_agent.subprocess.run", side_effect=[_pr_view_result(), rejected, rejected]):
            success, output = self.agent.post_pr_review("42", [finding])

        self.assertFalse(success)
        self.assertIn("rejected", output)

    def test_gh_pr_view_failure_is_reported_without_raising(self):
        failed_view = MagicMock(returncode=1, stdout="", stderr="PR not found")
        with patch.object(self.agent, "get_repo_slug", return_value="acme/widget"), \
             patch("agents.github_agent.subprocess.run", return_value=failed_view) as mock_run:
            success, output = self.agent.post_pr_review("999", [ReviewFinding(severity="critical", title="X")])

        self.assertFalse(success)
        self.assertIn("not found", output)
        mock_run.assert_called_once()

    def test_never_raises_on_subprocess_error(self):
        with patch.object(self.agent, "get_repo_slug", return_value="acme/widget"), \
             patch("agents.github_agent.subprocess.run", side_effect=OSError("gh not installed")):
            success, output = self.agent.post_pr_review("42", [ReviewFinding(severity="critical", title="X")])

        self.assertFalse(success)
        self.assertIn("gh not installed", output)


if __name__ == "__main__":
    unittest.main()
