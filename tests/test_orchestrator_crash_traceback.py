"""
tests/test_orchestrator_crash_traceback.py – Testet die Traceback-Erhaltung bei unbehandelten
Abstürzen in Orchestrator.process() (Gesamtsystem-Analyse 2026-09-14, "verlorene Tracebacks").

Realer Fund: `workspace/ecochef` brach am 13.09.2026 drei Läufe hintereinander mit demselben
`abort_reason: "exception:TypeError"` ab (`logs/runs/20260913_{124114,140359,163546}_ecochef.
jsonl`) - aus dem Lauf-Log ging aber NUR der Exception-KLASSENNAME hervor, nie Zeile, Modul
oder Nachricht. Der Fehler war dadurch aus den Logs allein nicht diagnostizierbar.
Orchestrator.process() muss deshalb bei jedem unbehandelten Absturz sowohl den vollen
(gedeckelten) Traceback im Lauf-Log persistieren als auch ein eigenes, NICHT-autonomes
Backlog-Ticket (source="orchestrator_crash") mit demselben Traceback anlegen.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import core.backlog_store as backlog_store
from agents.orchestrator import Orchestrator
from core.backlog_store import get_ticket
from core.backlog_worker import _AUTONOMOUS_SOURCES


class TestOrchestratorCrashTraceback(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.backlog_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.backlog_file.close()

        backlog_patch = patch.object(backlog_store, "BACKLOG_FILE", Path(self.backlog_file.name))
        backlog_patch.start()
        self.addCleanup(backlog_patch.stop)

        self.orchestrator = Orchestrator()
        self.orchestrator.last_project_slug = "ecochef"

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_crash_persists_traceback_in_run_log_and_reraises(self):
        """process() muss den Traceback (nicht nur den Exception-Klassennamen) an
        run_logger.close() übergeben UND die ursprüngliche Exception weiter nach oben
        durchreichen (bestehendes Verhalten darf sich nicht ändern)."""
        fake_logger = MagicMock()
        fake_logger.closed = False
        # Der echte RunLogger.close() setzt self.closed = True (idempotent, siehe core/
        # run_logger.py) - ohne diese Nachbildung würde der finally-Zweig in process() den Mock
        # ein zweites Mal schließen und die call_count-Prüfung unten faelschlich verfaelschen.
        fake_logger.close.side_effect = lambda **kw: setattr(fake_logger, "closed", True)

        # Realer Fund beim Schreiben dieses Tests: process() setzt self._run_logger ganz am
        # Anfang IMMER auf None zurück (siehe process()-Docstring: verhindert, dass frühe
        # Agenten-Aufrufe ins Log des VORHERIGEN Laufs derselben Instanz schreiben). Ein VOR
        # process() gesetzter fake_logger würde deshalb sofort überschrieben - _process_impl
        # muss ihn deshalb (wie im echten Code) erst SELBST setzen, bevor es abstürzt.
        async def _boom(*args, **kwargs):
            self.orchestrator._run_logger = fake_logger
            raise TypeError("Simulierter unerwarteter Fehler ohne erkennbare Ursache im Log")

        with patch.object(self.orchestrator, "_process_impl", side_effect=_boom):
            with self.assertRaises(TypeError):
                asyncio.run(self.orchestrator.process(user_request="baue etwas"))

        # Genau EIN close()-Aufruf (kein doppelter aus dem finally-Zweig, da bereits geschlossen).
        self.assertEqual(fake_logger.close.call_count, 1)
        _, close_kwargs = fake_logger.close.call_args
        self.assertEqual(close_kwargs.get("abort_reason"), "exception:TypeError")
        self.assertIn("traceback", close_kwargs)
        self.assertIn("Simulierter unerwarteter Fehler", close_kwargs["traceback"])
        # Die eigentliche Fehler-Ausloeselinie (nicht nur der Klassenname) muss im Traceback
        # stehen - genau das, was im ecochef-Vorfall gefehlt hat.
        self.assertIn("_boom", close_kwargs["traceback"])
        self.assertIn("raise TypeError", close_kwargs["traceback"])

    def test_crash_opens_non_autonomous_backlog_ticket_with_traceback(self):
        """Ein Absturz muss ein Ticket mit vollem Traceback anlegen, dessen source NICHT in
        core.backlog_worker._AUTONOMOUS_SOURCES steht - core/backlog_worker.py darf einen
        Framework-Crash niemals selbstständig als Programmierauftrag umsetzen (dieselbe
        Vorsicht wie bei core/production_monitor.py-Tickets, siehe dortiger Docstring)."""
        async def _boom(*args, **kwargs):
            self.orchestrator._run_logger = MagicMock(closed=False)
            raise ValueError("kaputte Konfiguration in einem Fachbereichsschritt")

        with patch.object(self.orchestrator, "_process_impl", side_effect=_boom):
            with self.assertRaises(ValueError):
                asyncio.run(self.orchestrator.process(user_request="baue etwas anderes"))

        ticket = get_ticket("orchestrator-crash-ValueError-ecochef")
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.source, "orchestrator_crash")
        self.assertNotIn(ticket.source, _AUTONOMOUS_SOURCES)
        self.assertEqual(ticket.status, "blocked")
        self.assertEqual(ticket.project_slug, "ecochef")
        self.assertIn("kaputte Konfiguration", ticket.detail)
        self.assertIn("_boom", ticket.detail)

    def test_repeated_crash_of_same_cause_updates_single_ticket(self):
        """Wiederholte Abstürze DERSELBEN Ursache (gleiche Exception-Klasse + Projekt, wie die
        drei aufeinanderfolgenden ecochef-Läufe) müssen dasselbe Ticket aktualisieren statt bei
        jedem Lauf ein neues, gleich lautendes anzulegen - dieselbe Update-statt-Neuanlage-Logik
        wie bei den "recurring-failure-"-Tickets in agents/orchestrator/verification.py."""
        async def _boom(*args, **kwargs):
            raise TypeError("Absturz Nummer X")

        for _ in range(3):
            self.orchestrator._run_logger = MagicMock(closed=False)
            with patch.object(self.orchestrator, "_process_impl", side_effect=_boom):
                with self.assertRaises(TypeError):
                    asyncio.run(self.orchestrator.process(user_request="baue etwas"))

        from core.backlog_store import list_tickets
        crash_tickets = [t for t in list_tickets() if t.source == "orchestrator_crash"]
        self.assertEqual(len(crash_tickets), 1)

    def test_close_unfinished_run_log_without_traceback_omits_field(self):
        """Der reguläre 'returned_without_close'-Abschluss (kein Absturz, siehe finally-Zweig
        in process()) darf weiterhin ganz ohne traceback-Feld auskommen - traceback_text ist
        optional und ändert das bestehende Verhalten für den Nicht-Crash-Fall nicht."""
        fake_logger = MagicMock()
        fake_logger.closed = False
        self.orchestrator._run_logger = fake_logger

        self.orchestrator._close_unfinished_run_log("returned_without_close")

        _, close_kwargs = fake_logger.close.call_args
        self.assertNotIn("traceback", close_kwargs)
        self.assertEqual(close_kwargs.get("abort_reason"), "returned_without_close")


if __name__ == "__main__":
    unittest.main()
