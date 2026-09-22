"""
agents/orchestrator/verification.py – VerificationMixin: echte Verifikations-/Fix-Schleife.

_run_verification_loop() installiert Abhängigkeiten isoliert, führt die echte Testsuite aus und
schickt bei Fehlschlägen einen GEZIELTEN Korrekturauftrag an die Agenten, deren Dateien laut
Traceback betroffen sind. Danach laufen die weiteren Checks (Docker-Build, Audits, Lint,
Coverage, Runtime-Smoke, Lastentest, Browser/A11y); Runtime-Smoke, Lastentest und Browser/UI
lösen über _run_runtime_check_with_fix() ebenfalls gezielte Fixes aus.

Die zustandslosen Diagnose-/Routing-Funktionen leben in failure_diagnosis.py (hier re-exportiert),
die Governance-Fix-Schleife in governance.py.

P6-5 (ROADMAP_TEMP.md), Teil 3/3: die zuvor 2589 Zeilen lange `VerificationMixin`-Klasse wurde
nach Verantwortlichkeiten auf fünf Mixin-Dateien aufgeteilt, exakt dasselbe Muster, das für
`interface/cli/` und `core/llm_providers/` bereits erfolgreich angewendet wurde:

- verification_loop.py       – VerificationLoopMixin: zentraler Einstiegspunkt/Orchestrierung
- verification_fix_dispatch.py – VerificationFixDispatchMixin: Fix-Dispatch/Eskalation der
  Haupt-Fixschleife (die vier per continue/break-Signal extrahierten Blöcke + Eskalationsleiter)
- verification_completeness.py – VerificationCompletenessMixin: Vollständigkeits-Check-Schleife
- verification_preflight.py    – VerificationPreflightMixin: Smoke-Gate, Pre-Flight-, Vorab-
  Import-Check (alles VOR der Haupt-Testschleife)
- verification_post_checks.py  – VerificationPostChecksMixin: Docker-/Frontend-Build, Runtime-
  Smoke, Lastentest, Browser/UI, Accessibility, Fachlogik-Testtiefe, Coverage (NACH der
  Haupt-Testschleife) - nicht zu verwechseln mit dem bereits vorher existierenden
  verification_checks.py (CheckContext/reconcile_verification_ok/run_informational_checks)

Dieses Modul bleibt die stabile Importoberfläche: `VerificationMixin` UND jeder Name, den
bestehender Code bisher direkt aus `agents.orchestrator.verification` importiert hat (die
Re-Exports aus failure_diagnosis.py unten, plus `_classify_browser_failure_owner` aus
verification_post_checks.py), sind hier unverändert importierbar.
"""

from agents.orchestrator.failure_diagnosis import (
    _diagnose_import_failure,  # noqa: F401 - re-exportiert, siehe tests/test_import_name_error_learning.py
    _diagnose_no_tests_ran,  # noqa: F401 - re-exportiert, siehe tests/test_no_tests_ran_diagnosis.py
    _diagnose_runtime_failure,  # noqa: F401 - re-exportiert, siehe tests/test_runtime_failure_diagnosis.py
    _failure_fingerprint,  # noqa: F401 - re-exportiert
    _format_failures_for_agent,  # noqa: F401 - re-exportiert
    _import_name_error_target,  # noqa: F401 - re-exportiert
    _issue_signature,  # noqa: F401 - re-exportiert, siehe tests/test_no_progress_signature_helpers.py
    _no_progress,  # noqa: F401 - re-exportiert, siehe tests/test_no_progress_signature_helpers.py
    _prior_run_context,  # noqa: F401 - re-exportiert, siehe tests/test_cross_run_ticket_context.py
    _record_instance_attribute_learning,  # noqa: F401 - re-exportiert
    _record_verification_learning,  # noqa: F401 - re-exportiert
    _route_failure_owners,  # noqa: F401 - re-exportiert, siehe tests/test_failure_owner_routing.py
)
from agents.orchestrator.verification_completeness import VerificationCompletenessMixin
from agents.orchestrator.verification_fix_dispatch import VerificationFixDispatchMixin
from agents.orchestrator.verification_loop import VerificationLoopMixin
from agents.orchestrator.verification_post_checks import (
    VerificationPostChecksMixin,
    _classify_browser_failure_owner,  # noqa: F401 - re-exportiert, siehe tests/test_browser_failure_routing.py
)
from agents.orchestrator.verification_preflight import VerificationPreflightMixin
from config import MAX_VERIFICATION_ITERATIONS, MIN_TEST_COVERAGE
from core.backlog_store import upsert_ticket
from core.pre_flight_check import run_pre_flight_check
from core.team_board import unmet_requirements
from core.test_depth import analyze_test_depth
from core.verifier import ProjectVerifier

__all__ = [
    "MAX_VERIFICATION_ITERATIONS", "MIN_TEST_COVERAGE",
    "ProjectVerifier", "VerificationMixin", "_classify_browser_failure_owner",
    "_diagnose_import_failure", "_diagnose_no_tests_ran", "_diagnose_runtime_failure",
    "_failure_fingerprint", "_format_failures_for_agent", "_import_name_error_target",
    "_issue_signature", "_no_progress", "_prior_run_context", "_record_instance_attribute_learning",
    "_record_verification_learning", "_route_failure_owners", "analyze_test_depth",
    "run_pre_flight_check", "unmet_requirements", "upsert_ticket",
]


class VerificationMixin(
    VerificationLoopMixin,
    VerificationFixDispatchMixin,
    VerificationCompletenessMixin,
    VerificationPreflightMixin,
    VerificationPostChecksMixin,
):
    """Governance-Fix-Schleife und echte Test-/Deployment-Verifikations-Schleife."""
