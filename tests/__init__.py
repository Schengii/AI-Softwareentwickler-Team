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

Team-Optimierung (Retrospektive, 2026-09-04): derselbe Fund traf zusätzlich auf
core/backlog_store.py.BACKLOG_FILE zu - der obige Absatz (vor dieser Ergänzung) ging noch davon
aus, das sei unkritisch, weil "in tests/test_pr_workflow.py sauber gepatcht". Tatsächlich riefen
mindestens 6 weitere Testdateien (test_governance_fix_loop.py, test_governance_final_
reverification.py, test_governance_no_progress_breaker.py, test_permission_blocked_
clarification_fix.py, test_verification_no_progress_breaker.py, test_goal_loop.py) upsert_
ticket() über den vollen Governance-/Goal-Loop OHNE Isolation auf. Ergebnis: die echte
memory/backlog.json enthielt zuletzt 200 von 200 möglichen Einträgen (MAX_TICKETS_KEPT, siehe
core/backlog_store.py) zu einem großen Teil aus Test-Rauschen (project_slug "test_proj"/
"notizen_api", Ticket-IDs wie "unresolved-governance-critical-gov_fix_test_proj") - wegen des
FIFO-Deckels wurden dabei sogar bereits echte, seltene Tickets verdrängt. Dieselbe strukturelle
Umleitung wie bei RUN_HISTORY_FILE oben schließt die Lücke für ALLE (auch künftige,
ungeschriebene) Tests, statt erneut auf einzelne, leicht vergessbare patch.object()-Aufrufe zu
vertrauen. Tests, die BACKLOG_FILE selbst gezielt patchen (z.B. tests/test_pr_workflow.py,
tests/test_project_status.py), sind davon unberührt - patch.object() sichert/restauriert immer
den JEWEILS AKTUELLEN Wert, hier eben schon diesen Test-Pfad statt der echten Datei.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

import core.backlog_store as _backlog_store_module
import memory.run_history as _run_history_module

_test_run_history_dir = Path(tempfile.mkdtemp(prefix="ai_team_test_run_history_"))
_run_history_module.RUN_HISTORY_FILE = _test_run_history_dir / "run_history.json"
atexit.register(lambda: shutil.rmtree(_test_run_history_dir, ignore_errors=True))

_test_backlog_dir = Path(tempfile.mkdtemp(prefix="ai_team_test_backlog_"))
_backlog_store_module.BACKLOG_FILE = _test_backlog_dir / "backlog.json"
atexit.register(lambda: shutil.rmtree(_test_backlog_dir, ignore_errors=True))
