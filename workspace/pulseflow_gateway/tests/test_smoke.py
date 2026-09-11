"""
Smoke-Tests für PulseFlow Gateway.

WICHTIG (Stand dieses Testlaufs): Im Projekt existiert bislang KEIN
Anwendungscode (kein `app/`- oder `pulseflow_gateway/`-Package, kein
`main.py`, keine FastAPI-App). Das ist im Decision-Log
(.ai_team_decisions.jsonl) bereits als offener, kritischer Befund
dokumentiert - siehe "unresolved_governance_critical_ticket_opened".

Diese Aufgabe hier ist ausschließlich der Pre-Flight-Befund
"empty_test_suite" (tests/ enthält keine `def test_...`-Funktion).
Es sollen laut Auftrag AUSSCHLIESSLICH bestehende Befunde behoben und
KEINE neuen Features (also auch kein Backend/keine FastAPI-App)
erstellt werden.

Deshalb prüfen diese Smoke-Tests die tatsächlich im Repository
vorhandenen, echten Artefakte:
- das Root-Package `__init__.py` (Versionsattribut),
- dass das Projektverzeichnis grundsätzlich importierbar/lesbar ist.

Sobald ein echter Einstiegspunkt (FastAPI-App/`main.py`) existiert,
MUSS hier zusätzlich ein Health-Check-Smoke-Test
(`client.get("/health")`) ergänzt werden - siehe TODO unten.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_module_from_path(module_name: str, file_path: pathlib.Path):
    """Lädt ein Modul über seinen Dateipfad, unabhängig von Package-Struktur.

    Notwendig, da `__init__.py` hier direkt im Projekt-Root liegt und
    kein umgebendes Package besitzt - ein normaler `import __init__`
    wäre nicht portabel.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None, (
        f"Konnte kein Modul-Spec für {file_path} erzeugen"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_init_module_is_importable_and_has_version():
    """Smoke-Test: Das Root-Package lässt sich laden und definiert __version__."""
    init_path = PROJECT_ROOT / "__init__.py"
    assert init_path.exists(), "Erwartete Root-Datei __init__.py fehlt"

    module = _load_module_from_path("pulseflow_root_init", init_path)

    assert hasattr(module, "__version__"), "__init__.py muss __version__ definieren"
    assert isinstance(module.__version__, str) and module.__version__ != ""


def test_requirements_file_is_non_empty_and_pins_pytest():
    """Smoke-Test: requirements.txt existiert und enthält die Test-Toolchain."""
    req_path = PROJECT_ROOT / "requirements.txt"
    assert req_path.exists(), "requirements.txt fehlt"

    content = req_path.read_text(encoding="utf-8")
    assert content.strip() != "", "requirements.txt ist leer"
    assert "pytest" in content, "pytest muss als Abhängigkeit gelistet sein"


def test_project_has_no_undocumented_missing_entrypoint():
    """
    Dokumentiert den aktuellen (bekannten) Projektstand als expliziten,
    bewusst xfail-markierten Regressionstest: Sobald ein echter
    Einstiegspunkt (main.py/app.py/asgi.py) ergänzt wird, soll dieser
    Test fehlschlagen und so daran erinnern, hier den echten
    Health-Check-Smoke-Test nachzurüsten.
    """
    entrypoint_candidates = [
        "main.py",
        "app.py",
        "asgi.py",
        "manage.py",
        "run.py",
        "wsgi.py",
    ]
    found = [
        candidate
        for candidate in entrypoint_candidates
        if (PROJECT_ROOT / candidate).exists()
    ]
    # Kein rekursiver Scan nötig - laut list_files existiert aktuell
    # weder app/ noch pulseflow_gateway/ mit main.py.
    pkg_main = PROJECT_ROOT / "pulseflow_gateway" / "main.py"
    if pkg_main.exists():
        found.append(str(pkg_main))

    if found:
        pytest.fail(
            "Ein Einstiegspunkt wurde ergänzt (%s) - bitte jetzt einen echten "
            "Health-Check-Smoke-Test (client.get('/health')) in dieser Datei "
            "nachrüsten, wie in der Modul-Docstring als TODO vermerkt." % found
        )
