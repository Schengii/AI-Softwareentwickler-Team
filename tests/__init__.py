"""
tests/__init__.py

Isoliert memory/run_history.py.RUN_HISTORY_FILE STRUKTURELL für die gesamte Testsuite, bevor
irgendein Testmodul geladen wird.

Realer Fund: mindestens 29 End-to-End-Testdateien (z.B. test_verification_status.py,
test_load_test_integration.py, test_governance_fix_loop.py) rufen Orchestrator.process()
komplett durch, OHNE RUN_HISTORY_FILE auf ein Temp-Verzeichnis umzubiegen - anders als z.B.
core/backlog_store.py.BACKLOG_FILE, das in tests/test_pr_workflow.py sauber gepatcht wird.
JEDER Testlauf (auch ein einfacher `python -m unittest discover`) schrieb dadurch live in die
ECHTE memory/run_history.json. Da record_run() zusätzlich auf MAX_RUNS_KEPT=200 Einträge
FIFO-kappt, wurden echte, seltene Produktivläufe über die Zeit sogar aktiv aus der Historie
VERDRÄNGT: von 200 gespeicherten Einträgen stammten zuletzt 198 aus der Testsuite selbst
(total_tokens=15, model_used="fake-model", project_slug="test_proj" ...), nur 2 aus echten
Läufen. Die datenbasierte Selbstoptimierung (core/optimization_advisor.py, liest exakt diese
Datei über memory/run_history.py.get_agent_model_performance()/get_agent_success_rates())
lief dadurch faktisch gegen Test-Rauschen statt gegen echte Historie - ein analyze()-Aufruf
lieferte deshalb praktisch immer ein leeres Ergebnis.

Diese Umleitung greift hier STRUKTURELL für JEDEN Test (auch künftige, noch ungeschriebene) -
robuster als 29+ einzelne, leicht vergessbare patch.object()-Aufrufe pro Testdatei. Tests, die
RUN_HISTORY_FILE selbst gezielt patchen (z.B. tests/test_run_history_integration.py,
tests/test_run_history.py, tests/test_optimization_advisor.py,
tests/test_observability_endpoint.py), sind davon unberührt: unittest.mock.patch.object()
sichert/restauriert immer den JEWEILS AKTUELLEN Wert - hier eben diesen Test-Pfad statt der
echten Datei, nie mit Verlustrisiko für Produktivdaten.

memory/cost_history.py.COST_HISTORY_FILE braucht dieselbe Behandlung NICHT: record_run_usage()
ist bereits ein No-Op, solange kein echter Tokenverbrauch über core/token_guard.py erfasst
wurde (siehe dort) - die in Tests genutzten Fake-LLMs rufen token_guard.record_usage() nie
auf, der Delta-Tokenverbrauch bleibt also immer 0. core/project_status.py schreibt ebenfalls
unkritisch: seine Historie liegt PRO PROJEKT im jeweiligen project_dir, das diese Tests bereits
selbst auf ein temporäres WorkspaceManager-Verzeichnis umbiegen.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

import memory.run_history as _run_history_module

_test_run_history_dir = Path(tempfile.mkdtemp(prefix="ai_team_test_run_history_"))
_run_history_module.RUN_HISTORY_FILE = _test_run_history_dir / "run_history.json"
atexit.register(lambda: shutil.rmtree(_test_run_history_dir, ignore_errors=True))
