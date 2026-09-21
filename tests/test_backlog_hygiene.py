"""
tests/test_backlog_hygiene.py – Tests für core/backlog_hygiene.py
inklusive archive_old_run_traces und HygieneReport.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from core.backlog_hygiene import (
    HygieneReport,
    archive_old_run_traces,
)


class TestBacklogHygiene(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_dir = Path(self.temp_dir)
        self.project_dir = self.workspace_dir / "my_project"
        self.project_dir.mkdir()
        self.runs_dir = self.project_dir / ".ai_team_runs"
        self.runs_dir.mkdir()

    def test_archive_old_run_traces(self):
        now_ts = time.time()
        # Erstelle einen alten Trace (> 30 Tage)
        old_trace = self.runs_dir / "20260101_000000_trace.jsonl"
        old_trace.write_text('{"event": "start"}', encoding="utf-8")
        old_time = now_ts - (35 * 86400)
        os.utime(old_trace, (old_time, old_time))

        old_verif = self.runs_dir / "20260101_000000_verification.md"
        old_verif.write_text("# Old Report", encoding="utf-8")
        os.utime(old_verif, (old_time, old_time))

        # Erstelle einen frischen Trace (< 30 Tage)
        fresh_trace = self.runs_dir / "20260921_120000_trace.jsonl"
        fresh_trace.write_text('{"event": "recent"}', encoding="utf-8")

        # Ausführen mit project_dir
        archived = archive_old_run_traces(project_dir=self.project_dir, max_age_days=30.0)
        self.assertEqual(archived, 2)

        # Prüfe, dass die alten Dateien im archive/ Unterordner liegen
        archive_subdir = self.runs_dir / "archive"
        self.assertTrue((archive_subdir / "20260101_000000_trace.jsonl").exists())
        self.assertTrue((archive_subdir / "20260101_000000_verification.md").exists())
        self.assertFalse(old_trace.exists())
        self.assertFalse(old_verif.exists())

        # Frische Datei muss weiterhin im Hauptverzeichnis sein
        self.assertTrue(fresh_trace.exists())

    def test_archive_old_run_traces_via_workspace_dir(self):
        now_ts = time.time()
        old_trace = self.runs_dir / "20260101_000000_trace.jsonl"
        old_trace.write_text('{"event": "start"}', encoding="utf-8")
        old_time = now_ts - (40 * 86400)
        os.utime(old_trace, (old_time, old_time))

        # Aufruf mit workspace_dir
        archived = archive_old_run_traces(workspace_dir=self.workspace_dir, max_age_days=30.0)
        self.assertEqual(archived, 1)
        self.assertTrue((self.runs_dir / "archive" / "20260101_000000_trace.jsonl").exists())

    def test_hygiene_report_summary_with_traces(self):
        report = HygieneReport(traces_archived=5)
        self.assertEqual(report.changed, 5)
        summary = report.format_summary()
        self.assertIn("5 alte Projekt-Traces nach archive/ verschoben", summary)


if __name__ == "__main__":
    unittest.main()
