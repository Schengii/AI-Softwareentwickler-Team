"""
tests/test_evals.py – Testet das Benchmark- & Evaluations-Framework (evals/)
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from evals.runner import (
    BenchmarkSuiteResult,
    BenchmarkTaskResult,
    run_benchmark,
    run_single_task,
    save_benchmark_result,
)
from evals.tasks import get_task, list_tasks


class TestBenchmarkTasks(unittest.TestCase):
    def test_list_tasks_returns_all_canonical_tasks(self):
        tasks = list_tasks()
        self.assertGreaterEqual(len(tasks), 5)
        slugs = {t.slug for t in tasks}
        self.assertIn("fastapi_ping", slugs)
        self.assertIn("cli_calculator", slugs)
        self.assertIn("notes_api_sqlite", slugs)

    def test_get_task_valid(self):
        task = get_task("fastapi_ping")
        self.assertEqual(task.slug, "fastapi_ping")
        self.assertEqual(task.category, "micro")

    def test_get_task_invalid_raises_key_error(self):
        with self.assertRaises(KeyError):
            get_task("non_existing_task_xyz")


class TestBenchmarkRunner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.history_file = Path(self.temp_dir) / "eval_history.json"

    def test_save_and_load_benchmark_result(self):
        suite = BenchmarkSuiteResult(
            timestamp="2026-08-22 15:00:00",
            total_tasks=2,
            passed_tasks=2,
            total_tokens=5000,
            total_duration_seconds=12.5,
            results=[
                BenchmarkTaskResult(
                    slug="fastapi_ping",
                    name="FastAPI Ping",
                    category="micro",
                    success=True,
                    verification_ok=True,
                    duration_seconds=5.0,
                    total_tokens=2000,
                )
            ],
        )

        save_benchmark_result(suite, self.history_file)
        self.assertTrue(self.history_file.exists())

        data = json.loads(self.history_file.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["total_tasks"], 2)
        self.assertEqual(data[0]["passed_tasks"], 2)

    def test_suite_formatting_table_and_markdown(self):
        suite = BenchmarkSuiteResult(
            timestamp="2026-08-22 15:00:00",
            total_tasks=1,
            passed_tasks=1,
            total_tokens=1500,
            total_duration_seconds=4.2,
            results=[
                BenchmarkTaskResult(
                    slug="fastapi_ping",
                    name="FastAPI Ping",
                    category="micro",
                    success=True,
                    verification_ok=True,
                    duration_seconds=4.2,
                    total_tokens=1500,
                )
            ],
        )

        table = suite.format_terminal_table()
        self.assertIn("BENCHMARK-ERGEBNISSE", table)
        self.assertIn("fastapi_ping", table)

        md = suite.format_markdown_report()
        self.assertIn("# 🎯 Benchmark-Bericht", md)
        self.assertIn("| `fastapi_ping` |", md)

    @patch("evals.runner.WorkspaceManager")
    def test_run_single_task_mocked(self, mock_ws_cls):
        # Die erwarteten Dateien muessen WAEHREND des Laufs entstehen. Frueher legte dieser Test
        # sie vorab an - genau das Muster, das den Benchmark unbrauchbar machte: Dateien eines
        # frueheren Laufs liessen einen spaeteren, gescheiterten Lauf bestehen. run_single_task
        # archiviert ein vorhandenes Verzeichnis deshalb jetzt vor dem Lauf.
        mock_ws = MagicMock()
        proj_dir = Path(self.temp_dir) / "ping_service"
        mock_ws.get_project_dir.return_value = proj_dir
        mock_ws_cls.return_value = mock_ws

        async def _erzeuge_projekt(*args, **kwargs):
            proj_dir.mkdir(parents=True, exist_ok=True)
            (proj_dir / "main.py").write_text("# app", encoding="utf-8")
            (proj_dir / "requirements.txt").write_text("fastapi", encoding="utf-8")
            (proj_dir / "test_main.py").write_text("# test", encoding="utf-8")
            return "✅ Verifikation erfolgreich abgeschlossen."

        fake_orch = MagicMock()
        fake_orch.process = _erzeuge_projekt
        fake_orch.last_verification_ok = True
        fake_orch.last_agent_results = [SimpleNamespace(total_tokens=4200)]

        task = get_task("fastapi_ping")
        res = asyncio.run(run_single_task(task, orchestrator=fake_orch))

        self.assertTrue(res.success)
        self.assertTrue(res.verification_ok)
        self.assertEqual(res.missing_files, [])
        self.assertIn("main.py", res.found_files)
        # total_tokens wurde frueher nie zugewiesen und war in jedem Report 0.
        self.assertEqual(res.total_tokens, 4200)

    @patch("evals.runner.WorkspaceManager")
    def test_gescheiterte_verifikation_faellt_durch(self, mock_ws_cls):
        """Kernbefund: Der Marker "Verifikations-Protokoll" steht auch in GESCHEITERTEN
        Berichten - er darf einen Lauf nie mehr als bestanden werten."""
        mock_ws = MagicMock()
        proj_dir = Path(self.temp_dir) / "ping_service"
        mock_ws.get_project_dir.return_value = proj_dir
        mock_ws_cls.return_value = mock_ws

        fake_orch = MagicMock()
        fake_orch.process = AsyncMock(
            return_value="### 🧪 Verifikations-Protokoll\n- ⚠️ pip install (exit_code=1)"
        )
        fake_orch.last_verification_ok = False
        fake_orch.last_agent_results = [SimpleNamespace(total_tokens=100)]

        res = asyncio.run(run_single_task(get_task("fastapi_ping"), orchestrator=fake_orch))
        self.assertFalse(res.verification_ok)
        self.assertFalse(res.success)

    @patch("evals.runner.WorkspaceManager")
    def test_run_benchmark_mocked_suite(self, mock_ws_cls):
        mock_ws = MagicMock()
        proj_dir = Path(self.temp_dir) / "ping_service"
        mock_ws.get_project_dir.return_value = proj_dir
        mock_ws_cls.return_value = mock_ws

        async def _erzeuge_projekt(*args, **kwargs):
            proj_dir.mkdir(parents=True, exist_ok=True)
            for f in ["main.py", "requirements.txt", "test_main.py"]:
                (proj_dir / f).write_text("# code", encoding="utf-8")
            return "🧪 Verifikations-Protokoll: Alles bestanden."

        fake_orch = MagicMock()
        fake_orch.process = _erzeuge_projekt
        fake_orch.last_verification_ok = True
        fake_orch.last_agent_results = [SimpleNamespace(total_tokens=1000)]

        with patch("evals.runner.EVALS_HISTORY_FILE", self.history_file):
            suite_res = asyncio.run(
                run_benchmark(task_slugs=["fastapi_ping"], orchestrator=fake_orch, save_history=True)
            )

        self.assertEqual(suite_res.total_tasks, 1)
        self.assertEqual(suite_res.passed_tasks, 1)
        self.assertEqual(suite_res.pass_rate, 100.0)


if __name__ == "__main__":
    unittest.main()


class TestExpectedFileLookup(unittest.TestCase):
    """Realer Fund (fastapi_ping, 2026-09-16): tests/test_main.py galt als fehlend."""

    def test_file_in_subdirectory_counts_as_found(self):
        import tempfile
        from pathlib import Path

        from evals.runner import _expected_file_exists

        root = Path(tempfile.mkdtemp())
        (root / "tests").mkdir()
        (root / "tests" / "test_main.py").write_text("def test_x(): pass\n", encoding="utf-8")
        (root / "main.py").write_text("x = 1\n", encoding="utf-8")
        self.assertTrue(_expected_file_exists(root, "test_main.py"))
        self.assertTrue(_expected_file_exists(root, "main.py"))
        self.assertFalse(_expected_file_exists(root, "fehlt.py"))

    def test_virtualenv_contents_do_not_count(self):
        import tempfile
        from pathlib import Path

        from evals.runner import _expected_file_exists

        root = Path(tempfile.mkdtemp())
        (root / ".ai_team_venv" / "Lib").mkdir(parents=True)
        (root / ".ai_team_venv" / "Lib" / "main.py").write_text("x = 1\n", encoding="utf-8")
        self.assertFalse(_expected_file_exists(root, "main.py"))
