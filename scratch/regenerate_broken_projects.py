"""
scratch/regenerate_broken_projects.py - Lässt das KI-Team drei unvollständige/leere
Workspace-Projekte neu generieren (forced_project_dir haelt sie im bestehenden Ordner,
statt einen neuen, fragmentierten Slug anzulegen - siehe reale Erkenntnis aus der
quickpoll/realtime_polling_platform-Aufspaltung).
"""
import asyncio
import sys

sys.path.insert(0, ".")

from agents.orchestrator import Orchestrator

TASKS = [
    (
        "workspace/realtime_polling_platform",
        "Das Projekt ist aktuell nur ein Fragment (nur models.py und security.py, kein "
        "main.py, keine requirements.txt, keine Tests). Baue eine vollstaendige, lauffaehige "
        "Echtzeit-Umfrage-Plattform (FastAPI + WebSockets, SQLAlchemy async, Pydantic v2 "
        "Schemas) mit main.py, requirements.txt und einer echten pytest-Testsuite, die auch "
        "wirklich gruen laeuft.",
    ),
    (
        "workspace/fastapi-task-mgmt",
        "Das Projekt ist aktuell komplett leer (nur alte __pycache__-Reste, kein "
        "Quellcode mehr vorhanden). Baue eine vollstaendige Task-Management-API (FastAPI, "
        "SQLAlchemy/SQLModel, SQLite) mit CRUD-Endpunkten fuer Tasks, requirements.txt und "
        "einer echten pytest-Testsuite, die auch wirklich gruen laeuft.",
    ),
    (
        "workspace/gui-enhancements",
        "Das Projekt ist aktuell komplett leer (nur ein verwaister node_modules-Ordner ohne "
        "eigenen Quellcode). Baue eine kleine, lauffaehige Web-GUI mit CSS-Animationen "
        "(HTML/CSS/JS) inklusive einer echten Jest-Testsuite fuer die reinen JS-Funktionen, "
        "die auch wirklich gruen laeuft.",
    ),
]


async def main():
    for project_dir, task in TASKS:
        print(f"\n{'=' * 70}\n=== {project_dir} ===\n{'=' * 70}")
        orchestrator = Orchestrator()
        try:
            result = await orchestrator.process(
                task,
                status_callback=print,
                forced_project_dir=project_dir,
            )
            print(f"\n--- Ergebnis {project_dir} ---\n{result}\n")
            print(f"verification_ok={orchestrator.last_verification_ok}")
        except Exception as e:
            print(f"!!! FEHLER bei {project_dir}: {e!r}")


if __name__ == "__main__":
    asyncio.run(main())
