"""
scratch/run_gui_enhancements_task.py – Echter End-to-End-Lauf gegen workspace/gui-enhancements,
um die frisch implementierten Fixes (Design-Kontrakt-Weitergabe, Import-Vertragsprüfung,
Test-Isolation der Lauf-Historie) unter echten API-Aufrufen zu validieren.
"""

import asyncio
import io
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestrator import Orchestrator

TASK = (
    "Baue eine kleine, echt lauffähige Demo-Seite, die die bereits in workspace/gui-enhancements "
    "vorbereiteten Bausteine (AnimatedBox-Komponente, designTokens, theme) tatsächlich verwendet: "
    "ein animiertes 3x3-Kachel-Grid (Framer Motion, gestaffeltes Einblenden über AnimatedBox) mit "
    "denselben 9 Kacheln wie im Finanzportfolio-Dashboard (Depotwert, Performance, "
    "Asset-Verteilung, Top Performer, Transaktionen, Dividenden, Risiko-Analyse, Markt-News, "
    "Einstellungen). Responsive (1/2/3 Spalten je Breakpoint), TypeScript, inkl. echtem Test, "
    "der prüft, dass alle 9 Kacheln gerendert werden."
)

PROJECT_DIR = str(Path("workspace/gui-enhancements").resolve())


async def main():
    orch = Orchestrator()
    print(f"=== STARTE ECHTEN LAUF gegen {PROJECT_DIR} ===\n{TASK}\n")

    def status(msg: str) -> None:
        print(msg)

    result = await orch.process(
        TASK,
        status_callback=status,
        forced_project_dir=PROJECT_DIR,
    )
    print("\n\n=== ENDERGEBNIS ===\n")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
