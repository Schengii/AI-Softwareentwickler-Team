"""
tests/test_pr_workflow.py – Testet den PR-Workflow (Feature-Branch + Pull Request statt
Direct-Push auf einen Hauptbranch)

Realer struktureller Unterschied zu einem echten Team: github_agent.push() committete
bisher IMMER direkt auf den gerade ausgecheckten Branch – bei einem frischen/geladenen
Projekt i.d.R. "main". Ein echtes Team committet nicht direkt auf den Hauptbranch, sondern
legt pro Aufgabe einen Feature-Branch an und öffnet einen Pull Request.

Zwei Ebenen:
1. GitHubAgent.build_feature_branch_name()/create_branch()/checkout()/gh_ready() – echtes
   lokales Git-Repo (kein Mock), da Branch-Wechsel genau die Art von Git-Interaktion ist,
   die ein Mock nicht glaubwürdig simulieren kann (siehe test_github_agent_push.py für
   dasselbe Prinzip). create_pull_request() ruft die `gh`-CLI auf, die in der CI-Umgebung
   nicht installiert ist – hier über subprocess.run gemockt.
2. interface/cli.py._ask_for_git_push() – entscheidet anhand des aktuellen Branches und
   gh_ready(), ob Feature-Branch+PR statt Direct-Push genutzt wird, und wechselt danach
   wieder zum ursprünglichen Hauptbranch zurück.
"""

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from agents.github_agent import GitHubAgent
from interface.cli import CLIInterface


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


class TestGitHubAgentBranchOperations(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.mkdtemp()
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "README.md").write_text("init\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_build_feature_branch_name_is_slugified_and_unique(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            name_a = agent.build_feature_branch_name("Baue eine Login-Seite!")
            name_b = agent.build_feature_branch_name("Baue eine Login-Seite!")

        self.assertTrue(name_a.startswith("feat/baue-eine-login-seite-"))
        self.assertNotEqual(name_a, name_b)  # UUID-Suffix macht jeden Aufruf eindeutig

    def test_create_branch_checks_out_new_branch_from_head(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            success, output = agent.create_branch("feat/new-thing-123")
            self.assertTrue(success, output)
            self.assertEqual(agent.get_current_branch(), "feat/new-thing-123")

    def test_checkout_switches_back_to_existing_branch(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            agent.create_branch("feat/some-work-456")
            success, output = agent.checkout("main")
            self.assertTrue(success, output)
            self.assertEqual(agent.get_current_branch(), "main")

    def test_gh_ready_is_false_without_gh_cli_installed(self):
        # In der CI-Testumgebung ist die `gh`-CLI nicht installiert - gh_ready() muss das
        # sauber als False melden statt zu crashen.
        with patch("agents.github_agent.BASE_DIR", self.work_dir), \
             patch("agents.github_agent.shutil.which", return_value=None):
            agent = GitHubAgent()
            self.assertFalse(agent.gh_ready())

    def test_create_pull_request_returns_pr_url_on_success(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir), \
             patch("agents.github_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="https://github.com/x/y/pull/42\n", stderr="",
            )
            agent = GitHubAgent()
            success, output = agent.create_pull_request(
                title="feat: x", body="body", base="main", head="feat/x-123",
            )
        self.assertTrue(success)
        self.assertEqual(output, "https://github.com/x/y/pull/42")
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args[:3], ["gh", "pr", "create"])
        self.assertIn("main", call_args)
        self.assertIn("feat/x-123", call_args)

    def test_create_pull_request_reports_failure_without_crashing(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir), \
             patch("agents.github_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="permission denied")
            agent = GitHubAgent()
            success, output = agent.create_pull_request(
                title="feat: x", body="body", base="main", head="feat/x-123",
            )
        self.assertFalse(success)
        self.assertIn("permission denied", output)


class TestCLIUsesPRWorkflowOnProtectedBranch(unittest.TestCase):
    """
    interface/cli.py._ask_for_git_push() – Branch-Entscheidung. Der GitHub-Agent selbst ist
    hier gemockt (siehe tests/test_cli_push_gate.py für dasselbe Prinzip bei der reinen
    Bestätigungs-Gate-Logik) – Gegenstand ist die Entscheidung "Feature-Branch+PR vs.
    Direct-Push", nicht die echten Git-Kommandos.
    """

    def setUp(self):
        self.cli = CLIInterface()
        self.fake_github = MagicMock()
        self.fake_github.get_status.return_value = "M some_file.py"
        self.fake_github.get_diff.return_value = "some_file.py | 3 +--"
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.create_branch.return_value = (True, "branch ok")
        self.fake_github.checkout.return_value = (True, "checkout ok")
        self.fake_github.create_pull_request.return_value = (True, "https://github.com/x/y/pull/1")
        self.fake_github.build_feature_branch_name.return_value = "feat/some-task-abc123"
        self.fake_github.scan_for_secrets.return_value = []
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))
        self.cli._orchestrator._agents["github"] = self.fake_github
        self.cli._orchestrator.last_verification_ok = True
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)
        # _ask_for_git_push() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen
        # ein temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_falls_back_to_direct_push_when_gh_not_ready(self, _mock_confirm):
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.gh_ready.return_value = False
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        self.fake_github.create_branch.assert_not_called()
        self.fake_github.create_pull_request.assert_not_called()
        self.fake_github.push.assert_called_once_with(branch=None)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_direct_push_when_already_on_feature_branch(self, _mock_confirm):
        # Bereits auf einem Feature-/Worktree-Branch (kein Hauptbranch) - ganz normal direkt
        # darauf committen/pushen, kein zusätzlicher Branch nötig.
        self.fake_github.get_current_branch.return_value = "ai-team/some-feature-abc123"
        self.fake_github.gh_ready.return_value = True
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        self.fake_github.create_branch.assert_not_called()
        self.fake_github.create_pull_request.assert_not_called()
        self.fake_github.push.assert_called_once_with(branch=None)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_falls_back_to_direct_push_when_branch_creation_fails(self, _mock_confirm):
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.gh_ready.return_value = True
        self.fake_github.create_branch.return_value = (False, "branch already exists")
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        self.fake_github.push.assert_called_once_with(branch=None)
        self.fake_github.create_pull_request.assert_not_called()
        self.fake_github.checkout.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_uses_pr_workflow_on_leftover_feat_branch_from_a_previous_run(self, _mock_confirm):
        # Realer Fund: das Arbeitsverzeichnis bleibt nach einem PR-Workflow-Lauf jetzt bewusst
        # auf dem Feature-Branch stehen (kein Checkout zurück mehr, siehe unten in dieser
        # Datei) - ein "feat/"-Branch ist damit fast immer unser eigener Leftover-Zustand,
        # kein bewusst vom Menschen ausgecheckter Branch, den es zu respektieren gälte.
        self.fake_github.get_current_branch.return_value = "feat/vorheriger-lauf-abc123"
        self.fake_github.gh_ready.return_value = True
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        # Neuer Branch wird explizit vom konfigurierten Hauptbranch abgezweigt, NICHT vom
        # Leftover-Branch selbst.
        self.fake_github.create_branch.assert_called_once_with("feat/some-task-abc123", base="main")
        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertEqual(pr_kwargs["base"], "main")
        self.fake_github.checkout.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_unverified_run_opens_draft_pr_with_warning_in_title_and_body(self, _mock_confirm):
        # Realer Fund (Pong-Projekt): ein PR, dessen echte Testsuite nie bestätigt bestanden
        # hatte, sah auf GitHub optisch IDENTISCH zu einem echt verifizierten PR aus - kein
        # Titel-Hinweis, kein Body-Hinweis, kein Draft-Status. Nur last_verification_ok=False
        # zu setzen (ohne last_verification_summary) muss trotzdem funktionieren (getattr mit
        # Default in _ask_for_git_push), analog zu den bestehenden last_verification_ok-only-
        # Setups in dieser Datei.
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.gh_ready.return_value = True
        self.cli._orchestrator.last_verification_ok = False
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertTrue(pr_kwargs["draft"])
        self.assertIn("UNVERIFIZIERT", pr_kwargs["title"])
        self.assertIn("Nicht verifiziert", pr_kwargs["body"])

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_verified_run_opens_normal_non_draft_pr(self, _mock_confirm):
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.gh_ready.return_value = True
        self.cli._orchestrator.last_verification_ok = True
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertFalse(pr_kwargs["draft"])
        self.assertNotIn("UNVERIFIZIERT", pr_kwargs["title"])


class TestCLIFullPRWorkflowAgainstRealRepo(unittest.TestCase):
    """
    Echtes lokales Git-Repo (kein Mock) für den vollständigen Branch-Wechsel-Zyklus, weil
    genau das (Feature-Branch anlegen -> Push -> zurück auf den Hauptbranch wechseln) die Art
    von zustandsbehafteter Git-Interaktion ist, die ein MagicMock nicht glaubwürdig
    simulieren kann (get_current_branch() müsste sich sonst künstlich synchron zu
    create_branch()/checkout() "mitbewegen"). Nur die `gh`-CLI (gh_ready()/
    create_pull_request(), in der CI-Umgebung nicht installiert) wird auf der Instanz
    gemockt – alle Branch-/Push-Operationen laufen über echtes `git`.
    """

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.remote_dir = str(Path(self.temp_root) / "remote.git")
        self.work_dir = str(Path(self.temp_root) / "work")
        Path(self.work_dir).mkdir()

        _run(["init", "--bare", "-b", "main", self.remote_dir], cwd=self.temp_root)
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "README.md").write_text("init\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)
        _run(["remote", "add", "origin", self.remote_dir], cwd=self.work_dir)
        _run(["push", "-u", "origin", "main"], cwd=self.work_dir)

        # _ask_for_git_push() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen
        # ein temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_root) / "backlog.json")
        self._backlog_patcher.start()

    def tearDown(self):
        self._backlog_patcher.stop()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _remote_branches(self) -> list[str]:
        result = _run(["branch"], cwd=self.remote_dir)
        return [line.strip(" *") for line in result.stdout.splitlines() if line.strip()]

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_creates_feature_branch_pr_and_stays_on_it(self, _mock_confirm):
        """
        Realer Fund: ein Checkout zurück zu `main` nach Push+PR entfernt jede Datei, die NUR
        auf dem Feature-Branch committet ist, aus dem Arbeitsverzeichnis - ein gerade erst
        generiertes Projekt wäre bis zum PR-Merge lokal komplett verschwunden. Das
        Arbeitsverzeichnis bleibt deshalb jetzt bewusst auf dem Feature-Branch stehen.
        """
        (Path(self.work_dir) / "new_file.py").write_text("x = 1\n", encoding="utf-8")

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            agent.gh_ready = lambda: True
            agent.create_pull_request = MagicMock(return_value=(True, "https://github.com/x/y/pull/1"))
            agent.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))

            cli = CLIInterface()
            cli._orchestrator._agents["github"] = agent
            cli._orchestrator.last_verification_ok = True

            with patch("interface.cli.console.print"):
                asyncio.run(cli._ask_for_git_push("Testaufgabe"))

            # Feature-Branch wurde tatsächlich auf den Remote gepusht ...
            self.assertIn(True, [b.startswith("feat/testaufgabe-") for b in self._remote_branches()])
            # ... und der PR wurde mit dem echten Feature-Branch als head angelegt.
            pr_kwargs = agent.create_pull_request.call_args.kwargs
            self.assertEqual(pr_kwargs["base"], "main")
            self.assertTrue(pr_kwargs["head"].startswith("feat/testaufgabe-"))
            # Arbeitsverzeichnis bleibt auf dem Feature-Branch ...
            self.assertTrue(agent.get_current_branch().startswith("feat/testaufgabe-"))
            # ... und die gerade erst committete Datei ist lokal weiterhin sichtbar.
            self.assertTrue((Path(self.work_dir) / "new_file.py").exists())

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_second_run_still_branches_from_main_despite_leftover_feat_branch(self, _mock_confirm):
        """
        Folge-Test zum obigen Fund: Da das Arbeitsverzeichnis nach einem Lauf jetzt auf dem
        Feature-Branch stehen bleibt, muss der ZWEITE Lauf trotzdem korrekt vom echten
        Hauptbranch abzweigen - nicht vom Leftover-Feature-Branch des ersten Laufs (sonst
        würde jeder PR versehentlich auf dem vorherigen aufbauen).
        """
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            agent.gh_ready = lambda: True
            agent.create_pull_request = MagicMock(return_value=(True, "https://github.com/x/y/pull/1"))
            agent.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))

            cli = CLIInterface()
            cli._orchestrator._agents["github"] = agent
            cli._orchestrator.last_verification_ok = True

            (Path(self.work_dir) / "first.py").write_text("x = 1\n", encoding="utf-8")
            with patch("interface.cli.console.print"):
                asyncio.run(cli._ask_for_git_push("Erste Aufgabe"))
            first_branch = agent.get_current_branch()
            self.assertTrue(first_branch.startswith("feat/"))

            agent.create_pull_request.reset_mock()
            (Path(self.work_dir) / "second.py").write_text("y = 2\n", encoding="utf-8")
            with patch("interface.cli.console.print"):
                asyncio.run(cli._ask_for_git_push("Zweite Aufgabe"))
            second_branch = agent.get_current_branch()

            self.assertNotEqual(first_branch, second_branch)
            pr_kwargs = agent.create_pull_request.call_args.kwargs
            self.assertEqual(pr_kwargs["base"], "main")  # vom Hauptbranch abgezweigt, nicht von first_branch
            # Der zweite Branch enthält NUR second.py, nicht das Ergebnis des ersten Laufs -
            # Beweis, dass er wirklich von main und nicht von first_branch abgezweigt wurde.
            diff = _run(["diff", "main", second_branch, "--name-only"], cwd=self.work_dir)
            changed_files = diff.stdout.split()
            self.assertIn("second.py", changed_files)
            self.assertNotIn("first.py", changed_files)


if __name__ == "__main__":
    unittest.main()
