"""
tests/test_test_suite_isolation.py – Regressionsschutz für die STRUKTURELLE Test-Isolation aus
tests/__init__.py.

Realer Fund (Team-Retrospektive, 2026-09-04): core/backlog_store.py.BACKLOG_FILE war NICHT
strukturell isoliert (anders als memory/run_history.py.RUN_HISTORY_FILE, das genau dafür bereits
einen Fix bekommen hatte) - mindestens 6 Testdateien schrieben dadurch bei JEDEM Testlauf live in
die echte memory/backlog.json. Ergebnis: von 200 (MAX_TICKETS_KEPT) gespeicherten Tickets waren
~183 Test-Artefakte (project_slug "test_proj"/"notizen_api", Titel wie "Goal: Testziel"), die
echte, seltene Tickets teils sogar per FIFO-Kappung verdrängten. tests/__init__.py leitet
BACKLOG_FILE (wie schon RUN_HISTORY_FILE) jetzt vor jedem Testlauf strukturell auf ein
Temp-Verzeichnis um. Dieser Test stellt sicher, dass diese Umleitung nicht versehentlich wieder
entfernt wird - kein Aufruf hier patcht BACKLOG_FILE/RUN_HISTORY_FILE selbst, die Prüfung greift
also ausschließlich, wenn die globale Umleitung aus tests/__init__.py aktiv ist.
"""

import unittest
from pathlib import Path

import core.backlog_store as backlog_store
import memory.run_history as run_history


class TestSuiteIsolatesSharedProductionFiles(unittest.TestCase):
    def test_backlog_file_points_outside_the_real_repo(self):
        # BASE_DIR ist das echte Projekt-Wurzelverzeichnis (config.py) - BACKLOG_FILE darf
        # NICHT mehr darunter liegen, sobald tests/__init__.py geladen wurde.
        from config import BASE_DIR

        self.assertNotEqual(backlog_store.BACKLOG_FILE, Path(BASE_DIR) / "memory" / "backlog.json")
        self.assertIn("ai_team_test_backlog_", str(backlog_store.BACKLOG_FILE))

    def test_run_history_file_points_outside_the_real_repo(self):
        from config import BASE_DIR

        self.assertNotEqual(run_history.RUN_HISTORY_FILE, Path(BASE_DIR) / "memory" / "run_history.json")
        self.assertIn("ai_team_test_run_history_", str(run_history.RUN_HISTORY_FILE))

    def test_upsert_ticket_never_touches_the_real_backlog_json(self):
        from config import BASE_DIR

        real_backlog = Path(BASE_DIR) / "memory" / "backlog.json"
        before = real_backlog.read_bytes() if real_backlog.exists() else None

        backlog_store.upsert_ticket(
            ticket_id="isolation-canary", title="Sollte nie in der echten Datei landen",
            source="cli", status="todo",
        )

        after = real_backlog.read_bytes() if real_backlog.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
