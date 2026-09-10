"""
tests/test_pre_commit_hook.py – Das Lint-Gate prüft nur gestagte Dateien

Realer Fund (Framework-Analyse 2026-09-10, Backlog-Tickets cli-9b95ab3e/cli-034e08e5):
scripts/git-hooks/pre-commit lief `ruff check .` über das gesamte Repository - eine nicht
gestagte Datei (scratch/test_keys.py) blockierte dadurch Commits, die sie gar nicht enthielten.
Führt den echten Hook in einem temporären Git-Repository aus.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from config import BASE_DIR

HOOK = Path(BASE_DIR) / "scripts" / "git-hooks" / "pre-commit"


def _find_sh() -> str | None:
    sh = shutil.which("sh")
    if sh:
        return sh
    git = shutil.which("git")
    if git:
        git_root = Path(git).resolve().parents[1]
        for candidate in (git_root / "bin" / "sh.exe", git_root / "usr" / "bin" / "sh.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


SH = _find_sh()


@unittest.skipUnless(SH and shutil.which("git") and shutil.which("ruff"), "sh/git/ruff nicht verfügbar")
class TestPreCommitHookLintsOnlyStagedFiles(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self._git("init", "-q")
        (self.repo / "good module.py").write_text('print("ok")\n', encoding="utf-8")
        (self.repo / "unstaged_bad.py").write_text("import os\n", encoding="utf-8")  # F401

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, timeout=30)

    def _run_hook(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [SH, str(HOOK)], cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
        )

    def test_unstaged_lint_error_does_not_block_commit_of_clean_file(self):
        self._git("add", "good module.py")
        result = self._run_hook()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_lint_error_still_blocks_commit(self):
        self._git("add", "good module.py", "unstaged_bad.py")
        result = self._run_hook()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unstaged_bad.py", result.stdout + result.stderr)

    def test_no_staged_python_files_skips_the_gate(self):
        (self.repo / "README.md").write_text("# x\n", encoding="utf-8")
        self._git("add", "README.md")
        self.assertEqual(self._run_hook().returncode, 0)


if __name__ == "__main__":
    unittest.main()
