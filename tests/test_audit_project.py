"""
tests/test_audit_project.py – Testet /audit-projekt: echte Agenten-Analyse (gemockt im Test,
um keine echten API-Kosten zu erzeugen), aber ein ECHTES Bestätigungs-Gate vor jeder Löschung.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.message_bus import AgentResult
from interface.cli import CLIInterface

FAKE_REPORT_WITH_DELETIONS = """## 🧹 Projekt-Hygiene & Aufräum-Report

### 2. 🗑️ Zur Löschung empfohlene Dateien
| Pfad | Grund |
|---|---|
| `old_script.py` | Nirgends referenziert |

```deletions
old_script.py
```
"""

FAKE_REPORT_NO_DELETIONS = """## 🧹 Projekt-Hygiene & Aufräum-Report

Alles sauber, keine Empfehlungen.

```deletions
```
"""


class TestAuditProject(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_dir = tempfile.mkdtemp()
        (Path(self.temp_dir) / "old_script.py").write_text("# tot")
        self.fake_cleaner = self.cli._orchestrator._agents["project_cleaner"]
        self.fake_cleaner.execute = AsyncMock()
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _fake_result(self, content: str) -> AgentResult:
        return AgentResult(
            task_id="manual_audit", agent_id="project_cleaner", agent_name="Projekt-Hygiene",
            success=True, content=content,
        )

    def test_declining_confirmation_deletes_nothing(self):
        import config
        original_base_dir = config.BASE_DIR
        config.BASE_DIR = self.temp_dir
        try:
            self.fake_cleaner.execute.return_value = self._fake_result(FAKE_REPORT_WITH_DELETIONS)
            with patch("interface.cli.Confirm.ask", return_value=False) as mock_confirm:
                asyncio.run(self.cli._audit_project(None))
                mock_confirm.assert_called_once()
            self.assertTrue((Path(self.temp_dir) / "old_script.py").exists())
        finally:
            config.BASE_DIR = original_base_dir

    def test_accepting_confirmation_deletes_recommended_path(self):
        import config
        original_base_dir = config.BASE_DIR
        config.BASE_DIR = self.temp_dir
        try:
            self.fake_cleaner.execute.return_value = self._fake_result(FAKE_REPORT_WITH_DELETIONS)
            with patch("interface.cli.Confirm.ask", return_value=True):
                asyncio.run(self.cli._audit_project(None))
            self.assertFalse((Path(self.temp_dir) / "old_script.py").exists())
        finally:
            config.BASE_DIR = original_base_dir

    def test_no_recommendations_skips_confirmation_entirely(self):
        import config
        original_base_dir = config.BASE_DIR
        config.BASE_DIR = self.temp_dir
        try:
            self.fake_cleaner.execute.return_value = self._fake_result(FAKE_REPORT_NO_DELETIONS)
            with patch("interface.cli.Confirm.ask") as mock_confirm:
                asyncio.run(self.cli._audit_project(None))
                mock_confirm.assert_not_called()
        finally:
            config.BASE_DIR = original_base_dir

    def test_task_is_built_read_only(self):
        """Der Audit-Task darf dem Agenten NIEMALS Schreibrechte geben."""
        import config
        original_base_dir = config.BASE_DIR
        config.BASE_DIR = self.temp_dir
        try:
            self.fake_cleaner.execute.return_value = self._fake_result(FAKE_REPORT_NO_DELETIONS)
            asyncio.run(self.cli._audit_project(None))
            passed_task = self.fake_cleaner.execute.call_args[0][0]
            self.assertTrue(passed_task.tools_read_only)
        finally:
            config.BASE_DIR = original_base_dir


if __name__ == "__main__":
    unittest.main()
