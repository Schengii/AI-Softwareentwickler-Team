"""
tests/conftest.py – Test-weite Fixtures für die Framework-Testsuite.

Realer Fund (Team-Retrospektive 2026-09-06): core/optimization_advisor.py.
record_suggestions_as_lessons() wird bei JEDEM agents.orchestrator.Orchestrator.process()-Lauf
unbedingt aufgerufen (siehe dessen Modul-Docstring - bewusst NICHT hinter
config.ENABLE_AUTO_MODEL_TUNING versteckt, damit Funde auch ohne den globalen Schalter sichtbar
bleiben). Dutzende bestehender Tests lassen process() vollständig durchlaufen, ohne
core/optimization_advisor.py zu mocken - dabei liest analyze() die ECHTE, projektweite
memory/run_history.json. Findet sie dort einen echten Befund (z.B. einen Agenten mit
auffällig niedriger Erfolgsquote aus vergangenen, echten Läufen), schreibt
record_suggestions_as_lessons() ihn in die VERSIONIERTE memory/team_lessons.jsonl - ein
reiner Testlauf mutierte dadurch tatsächlich eine committete Projektdatei (genau das ist
während der Verifikation dieser Funktion einmal real passiert und musste per
`git checkout -- memory/team_lessons.jsonl` rückgängig gemacht werden).

Diese autouse-Fixture patcht record_suggestions_as_lessons für JEDEN Test zentral als No-Op,
statt jeden der zahlreichen betroffenen Testdateien einzeln anzupassen - reine Testisolation,
ändert kein Produktionsverhalten. Wirkt auch für unittest.TestCase-basierte Tests (der in
diesem Projekt übliche Stil), da pytest autouse-Fixtures unabhängig vom Testfall-Stil anwendet.

Dieselbe Gefahr gilt seit der Fortsetzung der Analyse 2026-09-06 für
core.optimization_advisor.record_unused_agent_tickets(): findet analyze() bei einem process()-
Lauf ohne gemockte Historie einen echten unused_agent-Befund, würde das ohne Patch ein echtes
Ticket in die VERSIONIERTE memory/backlog.json schreiben - dieselbe Klasse von Fehler wie oben
bei team_lessons.jsonl, nur eine Datei weiter.

Realer Fund (Analyse 2026-09-06, voller Suite-Lauf statt Einzeltest): core/llm_factory.py hält
mit `_gemini_rate_limiter` einen EINZIGEN, prozessweiten `RateLimiter` (Sliding-Window,
standardmäßig 12 Aufrufe/Minute) - dessen `acquire()` läuft auch dann echt (kein Mock), wenn nur
die eigentliche Gemini-API in einem Test gepatcht wird. tests/test_llm_routing.py::
test_waits_briefly_when_entire_fallback_chain_is_exhausted schlug NUR im vollen Suite-Lauf fehl
(`1 failed, 1319 passed`), isoliert lief er sauber durch: andere, zuvor gelaufene Gemini-Tests
im selben Prozess hatten das 60-Sekunden-Fenster bereits mit eigenen `acquire()`-Aufrufen gefüllt,
sodass dieser Test unerwartet oft auf das (gemockte) `asyncio.sleep(0.01)` der Rate-Limiter-
Warteschleife traf, statt wie erwartet nur den EINEN Exhaustion-Wait auszulösen. Dieselbe
Lösung wie oben: die interne Aufruf-Historie wird vor jedem Test zentral geleert.

Dieselbe Fehlerklasse, echt beobachtet bei einem weiteren vollen Suite-Lauf (Fortsetzung der
Analyse 2026-09-06): `core/token_guard.py` hält mit dem Modul-Singleton `token_guard` ebenfalls
EINEN prozessweiten Zustand (`_exhausted_models`) - mehrere Tests in tests/test_llm_routing.py
markieren darüber gezielt Modelle als "erschöpft", teils mit `cooldown_seconds=999.0` (fast 17
Minuten). Einzelne Testklassen räumen das bereits selbst in ihrer eigenen tearDown() auf (siehe
tests/test_llm_routing.py.TestLLMRouting/TestClaudeFreeHeavyFallback), aber jeweils nur für eine
fest verdrahtete, eigene Liste bekannter Modellnamen - ein Test, der ein ANDERES Modell markiert
(oder in einer Klasse OHNE eigene Aufräum-Logik läuft), kann den Zustand trotzdem in spätere,
komplett unabhängige Tests durchsickern lassen. `tests/test_llm_routing.py::
test_claude_candidate_is_skipped_entirely_without_anthropic_api_key` schlug dadurch NUR im
vollen Suite-Lauf fehl (`1 failed, 1343 passed`), isoliert lief er sauber durch - dieselbe
strukturelle Lösung wie beim Rate-Limiter oben (zentral statt einzeln, deckt auch künftige,
noch ungeschriebene Tests ab) schließt die Lücke unabhängig davon, welcher konkrete Test den
Zustand hinterlässt.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_team_lesson_writes(monkeypatch):
    monkeypatch.setattr(
        "agents.orchestrator.record_suggestions_as_lessons", lambda *a, **k: None, raising=False,
    )
    monkeypatch.setattr(
        "agents.orchestrator.record_unused_agent_tickets", lambda *a, **k: [], raising=False,
    )


@pytest.fixture(autouse=True)
def _reset_gemini_rate_limiter():
    from core.llm_factory import _gemini_rate_limiter
    _gemini_rate_limiter._call_times.clear()
    yield
    _gemini_rate_limiter._call_times.clear()


@pytest.fixture(scope="session")
def _run_log_sandbox(tmp_path_factory):
    return tmp_path_factory.mktemp("run_logs")


@pytest.fixture(autouse=True)
def _isolate_run_logs(_run_log_sandbox, monkeypatch):
    """Realer Fund (Framework-Analyse 2026-09-10): 189 von 200 Dateien in logs/runs stammten aus
    Testläufen - core/run_logger.prune_old_logs() behält nur die jüngsten MAX_RUN_LOGS_KEPT,
    jeder Suite-Lauf löschte dadurch echte Lauf-Logs. Leitet beide Log-Verzeichnisse für JEDEN
    Test in ein temporäres Verzeichnis um."""
    monkeypatch.setattr("core.run_logger.RUN_LOGS_DIR", _run_log_sandbox / "runs")
    monkeypatch.setattr("core.run_logger.VERIFICATION_LOGS_DIR", _run_log_sandbox / "verification")


@pytest.fixture(autouse=True)
def _reset_token_guard_exhaustion():
    from core.token_guard import token_guard
    token_guard._exhausted_models.clear()
    yield
    token_guard._exhausted_models.clear()


@pytest.fixture(autouse=True)
def _reset_gemini_key_pool():
    import core.llm_factory as lf
    lf._gemini_clients_by_key.clear()
    lf._gemini_exhausted_keys.clear()
    lf._gemini_active_key_index = 0
    yield
    lf._gemini_clients_by_key.clear()
    lf._gemini_exhausted_keys.clear()
    lf._gemini_active_key_index = 0
