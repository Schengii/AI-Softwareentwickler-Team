"""
tests/test_cli_cancel_handler.py – Testet den Strg+C-Abbruch-Handler in interface/cli.py

Vorher stürzte Strg+C während eines laufenden Agenten-Teams das gesamte Programm mit einem
rohen KeyboardInterrupt-Traceback ab. CLIInterface._install_cancel_handler() installiert für
die Dauer eines Laufs einen eigenen SIGINT-Handler: erstes Strg+C setzt nur ein Flag
(kooperativer Abbruch, siehe tests/test_run_cancellation.py für die Orchestrator-Seite),
zweites Strg+C erzwingt den ursprünglichen (Programm-)Abbruch. Der ursprüngliche Handler wird
danach IMMER wiederhergestellt - sonst bliebe Strg+C für den Rest der Sitzung verändert.
"""

import asyncio
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import core.backlog_store as backlog_store
from interface.cli import CLIInterface


class TestInstallCancelHandler(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self._original_handler = signal.getsignal(signal.SIGINT)
        # _process_task() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen ein
        # temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def tearDown(self):
        signal.signal(signal.SIGINT, self._original_handler)

    def test_first_invocation_sets_cancel_event_without_raising(self):
        with patch("interface.cli.console.print"):
            previous = self.cli._install_cancel_handler()
            handler = signal.getsignal(signal.SIGINT)
            handler(signal.SIGINT, None)  # simuliert das erste Strg+C

        self.assertTrue(self.cli._cancel_event.is_set())
        signal.signal(signal.SIGINT, previous)

    def test_second_invocation_calls_through_to_original_handler(self):
        original_calls = []

        def fake_original(signum, frame):
            original_calls.append((signum, frame))

        with patch("interface.cli.console.print"):
            # signal.getsignal() nur für die Installation selbst fälschen (liefert den
            # "vorherigen" Handler) - danach mit dem ECHTEN signal.getsignal() den
            # TATSÄCHLICH installierten Handler abfragen, nicht den gefälschten Rückgabewert.
            with patch("signal.getsignal", return_value=fake_original):
                self.cli._install_cancel_handler()
            handler = signal.getsignal(signal.SIGINT)
            handler(signal.SIGINT, None)  # erstes Strg+C -> setzt nur das Flag
            handler(signal.SIGINT, None)  # zweites Strg+C -> muss durchgereicht werden

        self.assertEqual(len(original_calls), 1)

    def test_clears_stale_cancel_event_from_a_previous_run(self):
        self.cli._cancel_event.set()  # simuliert Rest eines vorherigen, abgebrochenen Laufs
        with patch("interface.cli.console.print"):
            previous = self.cli._install_cancel_handler()
        self.assertFalse(self.cli._cancel_event.is_set())
        signal.signal(signal.SIGINT, previous)


class TestProcessTaskCancelWiring(unittest.TestCase):
    def setUp(self):
        # _process_task() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen ein
        # temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def _run_process_task(self):
        cli = CLIInterface()
        cli._orchestrator.process = AsyncMock(return_value="### ok")
        with patch("interface.cli.console.print"), patch("interface.cli.Live"), \
                patch("interface.cli.Confirm.ask", return_value=False):
            asyncio.run(cli._process_task("Baue etwas"))
        return cli

    def test_passes_cancel_event_is_set_as_cancel_requested(self):
        cli = self._run_process_task()
        callback = cli._orchestrator.process.call_args.kwargs.get("cancel_requested")
        self.assertEqual(callback, cli._cancel_event.is_set)

    def test_sigint_handler_is_restored_after_run_completes(self):
        original_handler = signal.getsignal(signal.SIGINT)
        self._run_process_task()
        self.assertEqual(signal.getsignal(signal.SIGINT), original_handler)

    def test_sigint_handler_is_restored_even_when_process_raises(self):
        original_handler = signal.getsignal(signal.SIGINT)
        cli = CLIInterface()
        cli._orchestrator.process = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("interface.cli.console.print"), patch("interface.cli.Live"):
            asyncio.run(cli._process_task("Baue etwas"))

        self.assertEqual(signal.getsignal(signal.SIGINT), original_handler)


if __name__ == "__main__":
    unittest.main()
