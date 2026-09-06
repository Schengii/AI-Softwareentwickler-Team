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
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_team_lesson_writes(monkeypatch):
    monkeypatch.setattr(
        "agents.orchestrator.record_suggestions_as_lessons", lambda *a, **k: None, raising=False,
    )
