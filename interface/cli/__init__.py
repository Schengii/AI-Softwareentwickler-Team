"""
interface/cli/ – Interaktives Terminal-Interface für das KI-Softwareentwickler-Team (33 Spezialisten)

Bietet:
- Live-Statusanzeige mit aktuellem Bearbeitungsschritt, Phasen und arbeitenden Agenten
- Farbige Rich-Ausgabe
- Automatischer GitHub-Commit & Push Dialog (mit Bestätigungs-Gate & Diff-Vorschau)
- Workspace- & Projekt-Dateiverwaltung (/workspace, /export, /delete-project)
- Test-Runner (/run-tests)

P6-5 (ROADMAP_TEMP.md): früher eine einzelne 2396-Zeilen-Datei mit einer ~50-Methoden-Klasse -
nach demselben Mixin-Muster aufgeteilt, das agents/orchestrator/ bereits etabliert hat (siehe
dortiger Modul-Docstring). Jede Mixin-Datei deckt eine Verantwortlichkeit ab (Sitzungsstart,
Aufgaben-Verarbeitung, Git/Release, Projekt-Verwaltung, Learnings/Backlog, Projekt-Doku,
Befehls-Dispatch). Alle bisherigen Importpfade (`from interface.cli import CLIInterface`,
`patch("interface.cli.console.print")` usw.) bleiben unveraendert nutzbar - dieses Modul re-
exportiert dieselben Namen, unter denen bestehende Tests sie patchen.
"""

from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from config import BACKLOG_WIP_LIMIT_IN_PROGRESS, ENABLE_PLAN_CONFIRMATION, ENABLE_STARTUP_MODEL_PREFLIGHT
from core import framework_release
from core.notifier import notify_external
from interface.cli._shared import BANNER, HELP_TEXT, _pending_console_input, console
from interface.cli.command_dispatch import CLICommandDispatchMixin
from interface.cli.git_release import CLIGitReleaseMixin
from interface.cli.learnings_backlog import CLILearningsBacklogMixin
from interface.cli.project_docs import CLIProjectDocsMixin
from interface.cli.project_management import CLIProjectManagementMixin
from interface.cli.startup import CLIStartupMixin
from interface.cli.task_processing import CLITaskProcessingMixin

# Diese Namen werden von den Mixin-Dateien NICHT importiert, sondern bewusst zur AUFRUFZEIT
# per `from interface.cli import <name>` (oder als Klassen-/Modul-Attribut wie `Confirm.ask`,
# `framework_release.create_release`) aus DIESEM Modul re-gelesen, weil bestehende Tests sie
# als `interface.cli.<name>` patchen (siehe interface/cli/startup.py & Co. fuer den
# Hintergrund). ruff kennt diese indirekte Nutzung nicht und meldet sie faelschlich als
# unbenutzt - __all__ macht die Absicht explizit, statt die Warnung zu unterdruecken.
__all__ = [
    "CLIInterface",
    "console",
    "BANNER",
    "HELP_TEXT",
    "Confirm",
    "Live",
    "Panel",
    "Prompt",
    "framework_release",
    "notify_external",
    "BACKLOG_WIP_LIMIT_IN_PROGRESS",
    "ENABLE_PLAN_CONFIRMATION",
    "ENABLE_STARTUP_MODEL_PREFLIGHT",
    "_pending_console_input",
]


class CLIInterface(
    CLIStartupMixin,
    CLITaskProcessingMixin,
    CLIGitReleaseMixin,
    CLIProjectManagementMixin,
    CLILearningsBacklogMixin,
    CLIProjectDocsMixin,
    CLICommandDispatchMixin,
):
    """Das interaktive Kommandozeilen-Interface."""

    AUDIT_REMINDER_INTERVAL = 5  # Nach je N abgeschlossenen Aufgaben an /audit-projekt erinnern
