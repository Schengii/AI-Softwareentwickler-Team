"""
tests/test_roadmap_advisor.py – Testet core/roadmap_advisor.py (product_owner denkt read-only
über den nächsten sinnvollen Schritt eines bestehenden Projekts nach)

KI-Team-Zustandsbericht 2026-09-08, "Product-Owner-Weiterdenken": der product_owner-Agent
bearbeitet bisher AUSSCHLIESSLICH die konkret gestellte Aufgabe - propose_next_steps() lässt
ihn read-only über ein bestehendes Projekt nachdenken und legt seine Vorschläge als niedrig
priorisierte, NICHT automatisch umgesetzte Backlog-Tickets an.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store_module
from core.backlog_store import list_tickets
from core.message_bus import AgentResult
from core.roadmap_advisor import PROPOSAL_TICKET_SOURCE, propose_next_steps

_WELL_FORMED_RESPONSE = (
    "1. **Passwort-Reset-Flow** - Login existiert bereits, aber Nutzer können ihr Passwort "
    "nicht selbst zurücksetzen.\n"
    "2. **Rate-Limiting für die öffentliche API** - Die API ist öffentlich erreichbar, hat "
    "aber keine Begrenzung gegen Missbrauch.\n"
)


def _fake_orchestrator(content: str = _WELL_FORMED_RESPONSE, success: bool = True, error: str | None = None) -> MagicMock:
    orch = MagicMock()
    orch._run_single_agent = AsyncMock(return_value=AgentResult(
        task_id="t", agent_id="product_owner", agent_name="product_owner",
        success=success, content=content, error=error,
    ))
    return orch


class TestProposeNextSteps(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

        self.workspace_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.workspace_dir) / "meinprojekt"
        self.project_dir.mkdir()
        self._ws_patcher = patch("core.roadmap_advisor.WorkspaceManager")
        mock_ws_cls = self._ws_patcher.start()
        mock_ws_cls.return_value.get_project_dir.return_value = self.project_dir
        self.addCleanup(self._ws_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def test_nonexistent_project_returns_error_without_calling_agent(self):
        self._ws_patcher.stop()
        ws_patcher = patch("core.roadmap_advisor.WorkspaceManager")
        mock_ws_cls = ws_patcher.start()
        mock_ws_cls.return_value.get_project_dir.return_value = Path(self.workspace_dir) / "existiert-nicht"
        self.addCleanup(ws_patcher.stop)

        orch = _fake_orchestrator()
        report = asyncio.run(propose_next_steps(orch, "existiert-nicht"))

        self.assertFalse(report.ok)
        self.assertIn("existiert nicht", report.error)
        orch._run_single_agent.assert_not_called()

    def test_well_formed_response_creates_one_ticket_per_proposal(self):
        orch = _fake_orchestrator()
        report = asyncio.run(propose_next_steps(orch, "meinprojekt"))

        self.assertTrue(report.ok)
        self.assertEqual(len(report.proposals), 2)
        self.assertEqual(report.proposals[0].title, "Passwort-Reset-Flow")
        self.assertEqual(len(report.ticket_ids), 2)
        tickets = list_tickets()
        self.assertEqual(len(tickets), 2)

    def test_tickets_use_proposal_source_not_autonomous(self):
        """Vorschläge dürfen NICHT von --work-backlog automatisch umgesetzt werden - ob ein
        Feature sinnvoll ist, ist eine menschliche Produktentscheidung."""
        from core.backlog_worker import _AUTONOMOUS_SOURCES

        self.assertNotIn(PROPOSAL_TICKET_SOURCE, _AUTONOMOUS_SOURCES)

        orch = _fake_orchestrator()
        asyncio.run(propose_next_steps(orch, "meinprojekt"))

        for t in list_tickets():
            self.assertEqual(t.source, PROPOSAL_TICKET_SOURCE)
            self.assertEqual(t.status, "todo")
            self.assertEqual(t.priority, 3)

    def test_agent_reads_project_read_only(self):
        orch = _fake_orchestrator()
        asyncio.run(propose_next_steps(orch, "meinprojekt"))

        task = orch._run_single_agent.call_args.args[0]
        self.assertEqual(task.agent_id, "product_owner")
        self.assertEqual(task.project_dir, str(self.project_dir))
        self.assertTrue(task.tools_read_only)

    def test_repeated_run_updates_same_tickets_instead_of_duplicating(self):
        orch = _fake_orchestrator()
        asyncio.run(propose_next_steps(orch, "meinprojekt"))
        asyncio.run(propose_next_steps(orch, "meinprojekt"))

        self.assertEqual(len(list_tickets()), 2)

    def test_agent_failure_is_reported_without_crashing(self):
        orch = _fake_orchestrator(content="", success=False, error="Kein Modell verfügbar")
        report = asyncio.run(propose_next_steps(orch, "meinprojekt"))

        self.assertFalse(report.ok)
        self.assertIn("Kein Modell verfügbar", report.error)
        self.assertEqual(list_tickets(), [])

    def test_unparseable_response_is_reported_without_crashing(self):
        orch = _fake_orchestrator(content="Ich habe keine konkreten Vorschläge für dieses Projekt.")
        report = asyncio.run(propose_next_steps(orch, "meinprojekt"))

        self.assertFalse(report.ok)
        self.assertEqual(list_tickets(), [])

    def test_orchestrator_exception_is_reported_without_crashing(self):
        orch = MagicMock()
        orch._run_single_agent = AsyncMock(side_effect=RuntimeError("boom"))
        report = asyncio.run(propose_next_steps(orch, "meinprojekt"))

        self.assertFalse(report.ok)
        self.assertIn("boom", report.error)


if __name__ == "__main__":
    unittest.main()
