"""
core/verifier/coverage.py – CoverageMixin: misst die echte Python-Testabdeckung per
`pytest-cov`, wenn das Projekt es bereits selbst mitbringt (siehe CoverageReport-Docstring).
"""

import json

from core.code_sandbox import CodeSandbox
from core.verifier.models import CoverageReport


class CoverageMixin:
    """Misst die echte Testabdeckung eines Projekts."""

    def check_coverage(self, timeout_seconds: float = 60.0) -> CoverageReport:
        """
        Misst die echte Python-Testabdeckung per `pytest-cov`, WENN das Projekt es bereits
        selbst als Abhängigkeit mitbringt (siehe CoverageReport-Docstring) UND echte
        Python-Testdateien existieren. Bewusst kein separater Node/Coverage-Zweig - anders als
        Testausführung/Lint gibt es kein annähernd einheitliches Coverage-Tool über die
        verschiedenen Node-Test-Runner hinweg (Jest/Vitest/Mocha je eigenes Format).
        """
        if not self._find_python_test_files():
            return CoverageReport(attempted=False, reason_skipped="Keine Python-Testdateien gefunden.")

        python_exe = self._resolve_python()
        cov_check = CodeSandbox.run_command(
            [python_exe, "-c", "import pytest_cov"], cwd=self.project_dir, timeout_seconds=10.0,
        )
        if cov_check.exit_code != 0:
            return CoverageReport(
                attempted=False,
                reason_skipped="`pytest-cov` ist in diesem Projekt nicht installiert - das "
                               "Framework fügt es nicht selbst nachträglich hinzu.",
            )

        report_file = self.project_dir / "coverage_report.json"
        try:
            result = CodeSandbox.run_command(
                [python_exe, "-m", "pytest", "-q", "--tb=no",
                 f"--cov={self.project_dir}", f"--cov-report=json:{report_file}"],
                cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
            if not report_file.exists():
                tail = (result.stdout + result.stderr).strip()[-500:]
                return CoverageReport(attempted=False, reason_skipped=f"pytest-cov lieferte kein Ergebnis: {tail}")
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                return CoverageReport(attempted=False, reason_skipped=f"Coverage-JSON nicht lesbar: {e}")
            percent = round(data.get("totals", {}).get("percent_covered", 0.0), 1)
            return CoverageReport(attempted=True, percent=percent)
        finally:
            report_file.unlink(missing_ok=True)
