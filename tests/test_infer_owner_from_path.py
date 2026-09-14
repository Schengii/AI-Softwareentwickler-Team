"""
tests/test_infer_owner_from_path.py – Testet Orchestrator._infer_owner_from_path()
(agents/orchestrator/reporting.py).

Realer Fund (NexusForge-Lauf, Schwachstelle 2): Vollständigkeits-Funde aus
core/verifier/completeness.py, die sich auf das GESAMTE Projekt statt eine einzelne Datei
beziehen (z.B. fehlendes `pytest-asyncio` im Dependency-Manifest, fehlende README), melden
`file_path="."`. Weder `file_owners.get(".")` noch die bisherige rein Pfad-basierte
Heuristik in `_infer_owner_from_path()` konnten damit etwas anfangen - der Fund blieb als
"keinem Agenten eindeutig zuordenbar" ungelöst und blockierte `verification_ok`, obwohl die
Fehlermeldung selbst den zuständigen Bereich klar erkennen lässt.
"""

import unittest

from agents.orchestrator import Orchestrator


class TestInferOwnerFromPathExistingPathHeuristics(unittest.TestCase):
    """Bestehendes Verhalten (konkrete Dateipfade) darf durch den neuen Fallback nicht brechen."""

    def test_frontend_file_maps_to_frontend(self):
        self.assertEqual(Orchestrator._infer_owner_from_path("frontend/src/App.tsx"), "frontend")

    def test_package_json_maps_to_frontend(self):
        self.assertEqual(Orchestrator._infer_owner_from_path("frontend/package.json"), "frontend")

    def test_test_file_maps_to_tester(self):
        self.assertEqual(Orchestrator._infer_owner_from_path("tests/test_app.py"), "tester")

    def test_python_file_maps_to_backend(self):
        self.assertEqual(Orchestrator._infer_owner_from_path("app/main.py"), "backend")

    def test_readme_maps_to_readme(self):
        self.assertEqual(Orchestrator._infer_owner_from_path("README.md"), "readme")

    def test_unrecognizable_concrete_path_returns_none(self):
        self.assertIsNone(Orchestrator._infer_owner_from_path("assets/logo.svg"))


class TestInferOwnerFromPathGenericProjectWideFindings(unittest.TestCase):
    """Neuer Fallback für file_path in (".", "", None) - geroutet anhand der Fehlermeldung."""

    def test_dot_path_with_pytest_asyncio_message_maps_to_backend(self):
        owner = Orchestrator._infer_owner_from_path(
            ".",
            "Testdateien enthalten `@pytest.mark.asyncio`/`async def test_...`, aber weder "
            "`pytest-asyncio` noch `anyio` sind im Dependency-Manifest gelistet.",
        )
        self.assertEqual(owner, "backend")

    def test_dot_path_with_missing_requirements_message_maps_to_backend(self):
        owner = Orchestrator._infer_owner_from_path(
            ".",
            "Projekt importiert Drittanbieter-Pakete (fastapi, pydantic), liefert aber kein "
            "Dependency-Manifest (requirements.txt/pyproject.toml/Pipfile).",
        )
        self.assertEqual(owner, "backend")

    def test_dot_path_with_readme_message_maps_to_readme(self):
        owner = Orchestrator._infer_owner_from_path(
            ".", "README.md referenziert `docs/setup.md`, das im Projekt nicht existiert.",
        )
        self.assertEqual(owner, "readme")

    def test_dot_path_with_unrecognizable_message_falls_back_to_dev_lead(self):
        owner = Orchestrator._infer_owner_from_path(".", "Irgendein generischer Projektfund.")
        self.assertEqual(owner, "dev_lead")

    def test_empty_string_path_behaves_like_dot(self):
        owner = Orchestrator._infer_owner_from_path("", "kein Dependency-Manifest gefunden.")
        self.assertEqual(owner, "backend")

    def test_none_path_does_not_crash_and_falls_back_to_dev_lead(self):
        owner = Orchestrator._infer_owner_from_path(None, "Irgendein generischer Projektfund.")
        self.assertEqual(owner, "dev_lead")

    def test_dot_path_without_message_falls_back_to_dev_lead(self):
        self.assertEqual(Orchestrator._infer_owner_from_path("."), "dev_lead")


if __name__ == "__main__":
    unittest.main()
