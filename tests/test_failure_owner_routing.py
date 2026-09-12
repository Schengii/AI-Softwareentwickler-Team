"""
tests/test_failure_owner_routing.py – Ursachen-basiertes Routing im Test-Fix-Loop

Realer Fund (logipulse-Lauf 2026-09-10, logs/verification/20260910_084833_logipulse.log):
`assert 404 == 202` (nicht gemounteter Router) und `AttributeError: module 'jwt' has no
attribute 'encode'` (toxische Paket-Kollision) wurden an den `tester` delegiert, weil die
fehlschlagende Zeile in tests/test_*.py lag. Der tester kann weder app.include_router in
src/main.py ergänzen noch requirements.txt bereinigen. Diese Tests sichern die Zuordnung in
agents/orchestrator/verification._route_failure_owners() ab.
"""

import tempfile
import unittest
from pathlib import Path

from agents.orchestrator.verification import _diagnose_runtime_failure, _route_failure_owners

_ROUTE_404_MESSAGE = (
    "tests\\test_events.py:33: in test_post_event_success\n"
    "    assert response.status_code == 202\n"
    "E   assert 404 == 202\n"
    "E    +  where 404 = <Response [404 Not Found]>.status_code"
)
_JWT_MESSAGE = (
    "src\\main.py:36: in login\n"
    "    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)\n"
    "E   AttributeError: module 'jwt' has no attribute 'encode'"
)
_FILE_OWNERS = {
    "src/main.py": "backend",
    "src/config.py": "backend",
    "tests/test_events.py": "tester",
    "tests/test_auth.py": "tester",
    "requirements.txt": "refactoring",
}
_AGENTS = {"backend", "refactoring", "tester", "database"}


def _route(message, files, file_owners=None, agents=None, tester_participated=True):
    return _route_failure_owners(
        message, files, _FILE_OWNERS if file_owners is None else file_owners,
        _AGENTS if agents is None else agents, tester_participated,
    )


class TestRouteNotFoundRouting(unittest.TestCase):
    def test_404_in_test_file_goes_to_backend_not_tester(self):
        self.assertEqual(_route(_ROUTE_404_MESSAGE, ["tests/test_events.py"]), {"backend"})

    def test_unittest_style_404_goes_to_backend(self):
        message = "AssertionError: 404 != 200"
        self.assertEqual(_route(message, ["tests/test_events.py"]), {"backend"})

    def test_fastapi_default_not_found_body_goes_to_backend(self):
        message = "AssertionError: assert {'detail': 'Not Found'} == {'status': 'accepted'}"
        self.assertEqual(_route(message, ["tests/test_events.py"]), {"backend"})

    def test_without_backend_agent_falls_back_to_main_py_owner(self):
        owners = {"app/main.py": "dev_lead", "tests/test_events.py": "tester"}
        self.assertEqual(
            _route(_ROUTE_404_MESSAGE, ["tests/test_events.py"], owners, {"dev_lead", "tester"}),
            {"dev_lead"},
        )

    def test_test_expecting_404_but_getting_200_stays_with_tester(self):
        message = "E   assert 200 == 404\nE    +  where 200 = <Response [200 OK]>.status_code"
        self.assertEqual(_route(message, ["tests/test_events.py"]), {"tester"})


class TestDependencyErrorRouting(unittest.TestCase):
    def test_jwt_namespace_collision_goes_to_manifest_owner(self):
        files = ["src/main.py", "tests/test_auth.py"]
        self.assertEqual(_route(_JWT_MESSAGE, files), {"refactoring"})

    def test_dependency_error_ignores_tester_as_manifest_owner(self):
        owners = {**_FILE_OWNERS, "requirements.txt": "tester"}
        self.assertEqual(_route(_JWT_MESSAGE, ["tests/test_auth.py"], owners), {"backend"})

    def test_dependency_error_without_backend_goes_to_refactoring(self):
        owners = {"tests/test_auth.py": "tester"}
        self.assertEqual(
            _route(_JWT_MESSAGE, ["tests/test_auth.py"], owners, {"refactoring", "tester"}),
            {"refactoring"},
        )

    def test_missing_third_party_module_is_a_dependency_error(self):
        message = "E   ModuleNotFoundError: No module named 'jose'"
        self.assertEqual(_route(message, ["tests/test_auth.py"]), {"refactoring"})

    def test_attribute_error_on_local_module_is_not_a_dependency_error(self):
        message = "E   AttributeError: module 'src.config' has no attribute 'settings'"
        self.assertEqual(_route(message, ["src/main.py", "tests/test_auth.py"]), {"backend"})


class TestTesterOnlyForPureTestCodeErrors(unittest.TestCase):
    def test_wrong_assertion_in_test_file_goes_to_tester(self):
        message = "E   assert 'Alice' == 'alice'"
        self.assertEqual(_route(message, ["tests/test_auth.py"]), {"tester"})

    def test_broken_fixture_in_conftest_goes_to_tester(self):
        owners = {**_FILE_OWNERS, "tests/conftest.py": "tester"}
        message = "E   fixture 'client' not found"
        self.assertEqual(_route(message, ["tests/conftest.py"], owners), {"tester"})

    def test_exception_raised_in_production_code_drops_tester(self):
        message = "E   ZeroDivisionError: division by zero"
        self.assertEqual(_route(message, ["tests/test_events.py", "src/main.py"]), {"backend"})

    def test_unowned_failure_falls_back_to_tester_only_if_tester_took_part(self):
        self.assertEqual(_route("E   boom", ["unknown.py"]), {"tester"})
        self.assertEqual(_route("E   boom", ["unknown.py"], tester_participated=False), set())


class TestExistingRoutingRulesStillApply(unittest.TestCase):
    def test_import_name_error_goes_to_target_module_owner(self):
        message = "ImportError: cannot import name 'settings' from 'src.config'"
        self.assertEqual(_route(message, ["tests/test_auth.py"]), {"backend"})

    def test_integrity_error_goes_to_database(self):
        message = "sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint failed: users.email"
        self.assertEqual(_route(message, ["tests/test_auth.py"]), {"database"})


class TestInstanceAttributeErrorRouting(unittest.TestCase):
    """ki_team_fehleranalyse_zusammenfassung.md, Befund 2 (chronos_ledger-Lauf 20260912_181917):
    `detector.record_metric(...)` (Aufruf in tests/test_ledger.py) schlug mit `AttributeError:
    'AnomalyDetector' object has no attribute 'record_metric'` fehl - der Traceback zeigte nur
    die Testdatei, der eigentliche Autor der Klasse (hier: ml) wurde nie mitbeauftragt."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel: str, content: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_class_owner_is_added_alongside_tester(self):
        self._write(
            "app/services/anomaly_detector.py",
            "class AnomalyDetector:\n    def check_anomaly(self, metric):\n        return False, 0.0\n",
        )
        owners = {"app/services/anomaly_detector.py": "ml", "tests/test_ledger.py": "tester"}
        message = (
            "tests/test_ledger.py:237: in test_anomaly_detector_baseline_and_outlier_detection\n"
            "    detector.record_metric(IngestionMetric(...))\n"
            "E   AttributeError: 'AnomalyDetector' object has no attribute 'record_metric'"
        )
        result = _route_failure_owners(
            message, ["tests/test_ledger.py"], owners, {"ml", "tester"}, True, project_dir=str(self.root),
        )
        self.assertEqual(result, {"tester", "ml"})

    def test_dict_attribute_error_is_not_treated_as_class_lookup(self):
        # Bleibt vom bereits existierenden dict-spezifischen Routing (-> backend) unberührt.
        owners = {"tests/test_auth.py": "tester"}
        message = "AttributeError: 'dict' object has no attribute 'email'"
        result = _route_failure_owners(
            message, ["tests/test_auth.py"], owners, {"backend", "tester"}, True, project_dir=str(self.root),
        )
        self.assertEqual(result, {"backend"})

    def test_unknown_class_falls_back_to_traceback_owner(self):
        owners = {"tests/test_ledger.py": "tester"}
        message = "AttributeError: 'AnomalyDetector' object has no attribute 'record_metric'"
        result = _route_failure_owners(
            message, ["tests/test_ledger.py"], owners, {"tester"}, True, project_dir=str(self.root),
        )
        self.assertEqual(result, {"tester"})


class TestRoutingDiagnoses(unittest.TestCase):
    def test_route_not_found_diagnosis_points_to_include_router(self):
        diagnosis = _diagnose_runtime_failure(_ROUTE_404_MESSAGE)
        self.assertIsNotNone(diagnosis)
        self.assertIn("include_router", diagnosis)

    def test_jwt_diagnosis_names_the_toxic_collision(self):
        diagnosis = _diagnose_runtime_failure(_JWT_MESSAGE)
        self.assertIsNotNone(diagnosis)
        self.assertIn("requirements.txt", diagnosis)
        self.assertIn("pyjwt", diagnosis)


if __name__ == "__main__":
    unittest.main()
