"""
tests/test_verifier_load_test.py – Testet den echten Lastentest-Lauf
(core/verifier.py.check_load_test())

Realer Fund: der performance-Agent schreibt vollständige k6-/Locust-Lastentest-Skripte, die
aber NIE ausgeführt wurden – anders als run_tests() landeten sie ungeprüft im Projekt, niemand
wusste, ob sie überhaupt liefen. `locust`/`k6` werden dabei ECHT über
`shutil.which()`/`CodeSandbox.run_command` gemockt, der App-Start über
`subprocess.Popen`/`urllib.request.urlopen` (dasselbe Muster, das check_runtime_smoke() für
den http_api-Zweig real verwendet). Die Fixture-CSV/JSON sind an den echten
`locust --csv`- bzw. `k6 run --summary-export`-Ausgabeformaten orientiert.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier

_LOCUST_CSV_HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
    "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%\n"
)


def _locust_row(name: str, count: int, failures: int, p95: str = "20") -> str:
    return f"None,{name},{count},{failures},12,13.5,5,30,120,3.0,0.0,12,13,14,15,18,{p95},22,25,30,30,30\n"


def _fake_running_process() -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = None
    return proc


class TestStartPythonWebApp(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_none_without_web_entrypoint(self):
        verifier = ProjectVerifier(self.project_dir)
        self.assertIsNone(verifier._start_python_web_app(timeout_seconds=1.0))

    @patch("core.verifier.urllib.request.urlopen")
    @patch("core.verifier.subprocess.Popen")
    def test_starts_and_returns_proc_and_port_when_app_responds(self, mock_popen, mock_urlopen):
        (self.project_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        mock_popen.return_value = _fake_running_process()
        mock_urlopen.return_value.__enter__.return_value = MagicMock()

        verifier = ProjectVerifier(self.project_dir)
        result = verifier._start_python_web_app(timeout_seconds=2.0)

        self.assertIsNotNone(result)
        proc, port = result
        self.assertIsInstance(port, int)
        mock_popen.assert_called_once()


class TestCheckLoadTestDetection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_report_without_load_test_script(self):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_load_test()
        self.assertFalse(report.attempted)
        self.assertIn("Kein Lastentest-Skript", report.reason_skipped)

    @patch("core.verifier.shutil.which", return_value=None)
    def test_skipped_gracefully_when_tool_not_installed(self, mock_which):
        load_dir = self.project_dir / "tests" / "load"
        load_dir.mkdir(parents=True)
        (load_dir / "locustfile.py").write_text("# locust\n", encoding="utf-8")

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_load_test()

        self.assertFalse(report.attempted)
        self.assertEqual(report.tool, "locust")
        self.assertIn("nicht installiert", report.reason_skipped)

    @patch("core.verifier.shutil.which", return_value="/usr/bin/locust")
    def test_skipped_when_no_web_app_to_start(self, mock_which):
        load_dir = self.project_dir / "tests" / "load"
        load_dir.mkdir(parents=True)
        (load_dir / "locustfile.py").write_text("# locust\n", encoding="utf-8")

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_load_test()

        self.assertFalse(report.attempted)
        self.assertIn("startfähiger Python-Web-Einstiegspunkt", report.reason_skipped)

    @patch("core.verifier.shutil.which", return_value=None)
    def test_locustfile_takes_priority_over_k6_script(self, mock_which):
        load_dir = self.project_dir / "tests" / "load"
        load_dir.mkdir(parents=True)
        (load_dir / "locustfile.py").write_text("# locust\n", encoding="utf-8")
        (load_dir / "script.js").write_text("// k6\n", encoding="utf-8")

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_load_test()

        self.assertEqual(report.tool, "locust")

    @patch("core.verifier.ProjectVerifier._terminate_process")
    @patch("core.verifier.ProjectVerifier._run_locust_load_test")
    @patch("core.verifier.ProjectVerifier._start_python_web_app")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/locust")
    def test_dispatches_to_locust_and_tears_down_process(self, mock_which, mock_start, mock_run_locust, mock_terminate):
        load_dir = self.project_dir / "tests" / "load"
        load_dir.mkdir(parents=True)
        (load_dir / "locustfile.py").write_text("# locust\n", encoding="utf-8")
        fake_proc = _fake_running_process()
        mock_start.return_value = (fake_proc, 8000)

        verifier = ProjectVerifier(self.project_dir)
        verifier.check_load_test()

        mock_run_locust.assert_called_once()
        mock_terminate.assert_called_once_with(fake_proc)


class TestParseLocustStats(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.verifier = ProjectVerifier(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_stats(self, body: str) -> Path:
        stats_file = Path(self.temp_dir) / "loadtest_stats.csv"
        stats_file.write_text(_LOCUST_CSV_HEADER + body, encoding="utf-8")
        return stats_file

    def test_parses_clean_run_with_no_failures(self):
        stats_file = self._write_stats(_locust_row("/", 15, 0, "20") + _locust_row("Aggregated", 15, 0, "20"))

        report = self.verifier._parse_locust_stats(stats_file, "tests/load/locustfile.py")

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.tool, "locust")
        self.assertEqual(report.total_requests, 15)
        self.assertEqual(report.failed_requests, 0)
        self.assertEqual(report.p95_ms, 20.0)

    def test_parses_run_with_failures_as_not_passed(self):
        stats_file = self._write_stats(_locust_row("/", 15, 3, "500") + _locust_row("Aggregated", 15, 3, "500"))

        report = self.verifier._parse_locust_stats(stats_file, "tests/load/locustfile.py")

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(report.failed_requests, 3)

    def test_missing_aggregated_row_is_not_reported_as_passed(self):
        stats_file = self._write_stats(_locust_row("/", 15, 0, "20"))

        report = self.verifier._parse_locust_stats(stats_file, "tests/load/locustfile.py")

        self.assertFalse(report.attempted)
        self.assertFalse(report.passed)
        self.assertIn("Aggregated", report.reason_skipped)


class TestRunLocustLoadTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        load_dir = self.project_dir / "tests" / "load"
        load_dir.mkdir(parents=True)
        self.locustfile = load_dir / "locustfile.py"
        self.locustfile.write_text("# locust\n", encoding="utf-8")
        self.verifier = ProjectVerifier(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_writes_and_parses_real_tool_output(self, mock_run):
        def _fake_run(command, cwd, timeout_seconds):
            csv_prefix = command[command.index("--csv") + 1]
            Path(f"{csv_prefix}_stats.csv").write_text(
                _LOCUST_CSV_HEADER + _locust_row("Aggregated", 10, 0, "15"), encoding="utf-8",
            )
            return ExecutionResult(exit_code=0, stdout="", stderr="", duration_seconds=1.0)
        mock_run.side_effect = _fake_run

        report = self.verifier._run_locust_load_test(self.locustfile, port=8000, load_seconds=5.0, timeout_seconds=30.0)

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.total_requests, 10)
        self.assertIn("--host", mock_run.call_args[0][0])
        self.assertIn("http://127.0.0.1:8000", mock_run.call_args[0][0])

    @patch("core.verifier.CodeSandbox.run_command")
    def test_no_csv_written_is_never_reported_as_passed(self, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=1, stdout="", stderr="crashed", duration_seconds=1.0)

        report = self.verifier._run_locust_load_test(self.locustfile, port=8000, load_seconds=5.0, timeout_seconds=30.0)

        self.assertFalse(report.attempted)
        self.assertFalse(report.passed)
        self.assertIn("kein auswertbares Ergebnis", report.reason_skipped)


class TestParseK6Summary(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.verifier = ProjectVerifier(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_summary(self, content: str) -> Path:
        summary_file = Path(self.temp_dir) / "summary.json"
        summary_file.write_text(content, encoding="utf-8")
        return summary_file

    def test_parses_nested_values_format_clean_run(self):
        import json
        summary_file = self._write_summary(json.dumps({
            "metrics": {
                "http_reqs": {"values": {"count": 15, "rate": 3.0}},
                "http_req_failed": {"values": {"rate": 0.0}},
                "http_req_duration": {"values": {"p(95)": 20.5}},
            },
        }))

        report = self.verifier._parse_k6_summary(summary_file, "tests/load/script.js", exit_code=0)

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.total_requests, 15)
        self.assertEqual(report.failed_requests, 0)
        self.assertEqual(report.p95_ms, 20.5)

    def test_parses_flat_legacy_format(self):
        import json
        summary_file = self._write_summary(json.dumps({
            "metrics": {
                "http_reqs": {"count": 15, "rate": 3.0},
                "http_req_failed": {"rate": 0.2},
                "http_req_duration": {"p(95)": 20.5},
            },
        }))

        report = self.verifier._parse_k6_summary(summary_file, "tests/load/script.js", exit_code=0)

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(report.total_requests, 15)
        self.assertEqual(report.failed_requests, 3)

    def test_missing_metrics_degrade_gracefully_instead_of_crashing(self):
        import json
        summary_file = self._write_summary(json.dumps({"metrics": {}}))

        report = self.verifier._parse_k6_summary(summary_file, "tests/load/script.js", exit_code=0)

        self.assertTrue(report.attempted)
        self.assertEqual(report.total_requests, 0)
        self.assertIsNone(report.p95_ms)

    def test_corrupted_json_is_not_reported_as_passed(self):
        summary_file = self._write_summary("not valid json {{{")

        report = self.verifier._parse_k6_summary(summary_file, "tests/load/script.js", exit_code=0)

        self.assertFalse(report.attempted)
        self.assertFalse(report.passed)


if __name__ == "__main__":
    unittest.main()
