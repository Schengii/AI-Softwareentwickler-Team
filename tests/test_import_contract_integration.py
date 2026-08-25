"""
tests/test_import_contract_integration.py – Testet, dass agents/orchestrator.py._run_verification_loop()
bei einem gefundenen Import-Vertragsbruch BEIDE betroffenen Datei-Owner (Test- und Zieldatei)
gezielt zur Korrektur beauftragt - nicht nur den Autor der Testdatei, den ein reines
Traceback-Parsing allein adressiert hätte (siehe ImportContractIssue-Docstring in
core/verifier.py für den realen Fund).

Ruft dafür gezielt _run_verification_loop() direkt auf (statt den vollen Orchestrator.process()-
Pfad zu simulieren) - file_owners ist hier eine einfache, direkt kontrollierbare Eingabe, ohne
den kompletten agentischen Werkzeug-Loop nachbauen zu müssen, um echte Dateien zu erzeugen.
Dasselbe Muster wie test_governance_fix_loop.py für die verwandte Governance-Fix-Schleife.
"""

import asyncio
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult
from core.verifier import ImportContractIssue, ImportContractReport, VerificationReport


class TestImportContractIntegration(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_both_file_owners_are_dispatched_for_fix(self):
        file_owners = {"src/App.test.jsx": "tester", "src/App.jsx": "frontend"}
        dispatched_agent_ids: list[str] = []

        async def _fake_run_agents_parallel(tasks, notify=lambda *_: None):
            dispatched_agent_ids.extend(t.agent_id for t in tasks)
            return [
                AgentResult(agent_id=t.agent_id, agent_name=t.agent_id, task_id=t.task_id,
                            success=True, content="Fix angewendet.", total_tokens=5)
                for t in tasks
            ]

        with patch("agents.orchestrator.ProjectVerifier") as mock_verifier_cls, \
             patch.object(self.orchestrator, "_run_agents_parallel", side_effect=_fake_run_agents_parallel):
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.check_import_contracts.return_value = ImportContractReport(
                attempted=True, ok=False,
                issues=[ImportContractIssue(
                    test_file="src/App.test.jsx", imported_file="src/App.jsx", missing_export="default",
                )],
            )
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_sast.return_value = []
            mock_verifier.check_licenses.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_coverage.return_value.attempted = False

            results, summary, budget_aborted, cancelled, verification_ok = asyncio.run(
                self.orchestrator._run_verification_loop(
                    project_dir="dummy_project", all_results=[], file_owners=file_owners,
                    notify=lambda *_: None,
                )
            )

        self.assertIn("frontend", dispatched_agent_ids)
        self.assertIn("tester", dispatched_agent_ids)
        self.assertIn("Import-Vertragsprüfung", summary)

    def test_issue_without_known_owner_is_reported_but_not_dispatched(self):
        dispatched_agent_ids: list[str] = []

        async def _fake_run_agents_parallel(tasks, notify=lambda *_: None):
            dispatched_agent_ids.extend(t.agent_id for t in tasks)
            return []

        with patch("agents.orchestrator.ProjectVerifier") as mock_verifier_cls, \
             patch.object(self.orchestrator, "_run_agents_parallel", side_effect=_fake_run_agents_parallel):
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.check_import_contracts.return_value = ImportContractReport(
                attempted=True, ok=False,
                issues=[ImportContractIssue(
                    test_file="src/Unowned.test.jsx", imported_file="src/Unowned.jsx", missing_export="default",
                )],
            )
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_sast.return_value = []
            mock_verifier.check_licenses.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_coverage.return_value.attempted = False

            results, summary, budget_aborted, cancelled, verification_ok = asyncio.run(
                self.orchestrator._run_verification_loop(
                    project_dir="dummy_project", all_results=[], file_owners={},
                    notify=lambda *_: None,
                )
            )

        self.assertEqual(dispatched_agent_ids, [])
        self.assertIn("keinem Agenten eindeutig zuordenbar", summary)


if __name__ == "__main__":
    unittest.main()
