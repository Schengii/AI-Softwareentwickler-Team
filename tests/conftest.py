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
