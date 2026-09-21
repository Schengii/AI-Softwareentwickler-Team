"""
tests/test_run_postmortem.py – Testet P3-1 (ROADMAP_TEMP.md): "Es gibt keinen Projekt-
Abschlussbericht als Artefakt"

core/run_postmortem.py.generate_postmortem() führt DoD-Ergebnis, Fix-Ökonomie
(Produktion vs. Verifikations-/Governance-Reparatur), Rollen-Bilanz (geplant vs. eingesetzt)
und offene Root-Cause-Tickets zu EINEM deterministischen Bericht ohne LLM-Aufruf zusammen.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.message_bus import AgentResult
from core.verification_outcome import VerificationOutcome


class TestGeneratePostmortem(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def _read_report(self, relative_path: str) -> str:
        return (self.project_dir / relative_path).read_text(encoding="utf-8")

    def test_writes_report_without_any_llm_call_and_returns_relative_path(self):
        from core.run_postmortem import generate_postmortem

        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=1000, files_written=["main.py"]),
            AgentResult(task_id="verify_fix_backend_1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=300),
            AgentResult(task_id="t2", agent_id="tester", agent_name="Tester", success=False, content="", error="Timeout", total_tokens=50),
        ]
        outcome = VerificationOutcome()
        outcome.record("tests", True, "ok")
        outcome.record("lint", False, "F841")

        rel_path = generate_postmortem(
            project_dir=self.project_dir, project_slug="demoproj", results=results,
            planned_agent_ids=["backend", "tester", "frontend"], total_duration=42.0,
            verification_ok=True, outcome=outcome, stamp="20260921_120000",
        )

        self.assertEqual(rel_path, ".ai_team_runs/20260921_120000_postmortem.md")
        report = self._read_report(rel_path)
        self.assertIn("demoproj", report)
        self.assertIn("42.0s", report)
        self.assertIn("1,350", report)  # Tokens gesamt
        self.assertIn("✅ bestanden", report)
        self.assertIn("Nur informativ fehlgeschlagen (kein Blocker): lint", report)
        self.assertIn("❌ Tester (tester): Timeout", report)

    def test_fix_economy_splits_production_from_repair_tokens(self):
        from core.run_postmortem import generate_postmortem

        results = [
            AgentResult(task_id="backend_impl", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=1000),
            AgentResult(task_id="verify_fix_backend_1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=200),
            AgentResult(task_id="governance_recheck_backend_1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=100),
        ]
        rel_path = generate_postmortem(
            project_dir=self.project_dir, project_slug="demoproj", results=results,
            planned_agent_ids=["backend"], total_duration=1.0, verification_ok=True,
            outcome=None, stamp="20260921_130000",
        )
        report = self._read_report(rel_path)
        self.assertIn("Produktion: 1,000 Tokens (1 Aufruf(e))", report)
        self.assertIn("Reparatur (Verifikations-/Governance-Fixloop): 300 Tokens (2 Aufruf(e))", report)

    def test_role_balance_marks_planned_but_unused_roles(self):
        from core.run_postmortem import generate_postmortem

        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=10, files_written=["a.py"]),
        ]
        rel_path = generate_postmortem(
            project_dir=self.project_dir, project_slug="demoproj", results=results,
            planned_agent_ids=["backend", "frontend"], total_duration=1.0, verification_ok=True,
            outcome=None, stamp="20260921_140000",
        )
        report = self._read_report(rel_path)
        self.assertIn("| backend | ✅ | 1 | 1 | 1 |", report)
        self.assertIn("| frontend | ✅ | 0 | 0 | 0 |", report)

    def test_lists_open_root_cause_tickets_for_this_project(self):
        from core.run_postmortem import generate_postmortem

        with patch("core.backlog_store.list_tickets") as mock_list:
            ticket = type("T", (), {
                "id": "root-cause-demoproj-abc", "title": "Import-Fehler in main.py",
                "source": "root_cause_analysis", "project_slug": "demoproj", "status": "todo",
            })()
            other_project_ticket = type("T", (), {
                "id": "root-cause-otherproj-xyz", "title": "irrelevant",
                "source": "root_cause_analysis", "project_slug": "otherproj", "status": "todo",
            })()
            mock_list.return_value = [ticket, other_project_ticket]

            rel_path = generate_postmortem(
                project_dir=self.project_dir, project_slug="demoproj", results=[],
                planned_agent_ids=[], total_duration=0.0, verification_ok=False,
                outcome=None, stamp="20260921_150000",
            )
        report = self._read_report(rel_path)
        self.assertIn("root-cause-demoproj-abc", report)
        self.assertNotIn("root-cause-otherproj-xyz", report)


if __name__ == "__main__":
    unittest.main()
