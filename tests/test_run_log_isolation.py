"""
tests/test_run_log_isolation.py – Lauf-Logs: Testisolation und idempotenter Abschluss

Realer Fund (Framework-Analyse 2026-09-10): 189 von 200 Dateien in logs/runs stammten aus
Testläufen; die Rotation (MAX_RUN_LOGS_KEPT) löschte dadurch echte Lauf-Logs. Siehe die
autouse-Fixture `_isolate_run_logs` in tests/conftest.py.
"""

import json
import unittest
from pathlib import Path

import core.run_logger as rl
from config import BASE_DIR


class TestRunLogIsolation(unittest.TestCase):
    def test_test_runs_never_write_into_the_real_logs_directory(self):
        logger = rl.RunLogger(project_slug="isolation_check")
        real_logs = (Path(BASE_DIR) / "logs").resolve()
        self.assertNotIn(real_logs, logger.run_log_path.resolve().parents)
        self.assertNotIn(real_logs, logger.verification_log_path.resolve().parents)

    def test_close_is_idempotent(self):
        logger = rl.RunLogger(project_slug="close_twice")
        logger.close(verification_ok=True)
        logger.close(verification_ok=False, aborted=True)

        events = [json.loads(line) for line in logger.run_log_path.read_text(encoding="utf-8").splitlines()]
        closed = [e for e in events if e["event"] == "run_closed"]
        self.assertEqual(len(closed), 1)
        self.assertTrue(closed[0]["verification_ok"])
        self.assertTrue(logger.closed)


if __name__ == "__main__":
    unittest.main()
