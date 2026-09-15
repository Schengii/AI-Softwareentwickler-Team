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

Dieselbe Fehlerklasse noch einmal, echt beobachtet im PRODUKTIVEN Obsidian-Vault (Fund
2026-09-13): core/adr.write_adr() ruft intern IMMER auch export_adr_to_obsidian(project_dir, ...)
auf, OHNE dabei vault_path durchzureichen - export_adr_to_obsidian() fällt dann mangels
explizitem Pfad auf config.OBSIDIAN_VAULT_PATH zurück, das standardmäßig auf den echten,
produktiven Vault zeigt. tests/test_adr.py testet write_adr() direkt (nicht nur den bereits
isoliert getesteten export_adr_to_obsidian()-Pfad in tests/test_adr_obsidian_export.py) und
verwendet dafür u.a. per tempfile.mkdtemp() erzeugte Projektordner sowie fest benannte
Test-Projektordner ("adr_test_proj", "demo_project", "my_project", "gov_fix_test_proj") -
jeder einzelne Testlauf schrieb dadurch echte "ADR - <Projektordnername> - <Titel>.md"-Dateien
mit reinem Platzhalterinhalt ("K"/"E"/"K" bzw. "Kontext"/"Entscheidung"/"Konsequenzen") in
03 Resources/Permanent Notes/ des echten Vaults - über 40 solcher Dateien mussten von dort
manuell entfernt werden. Dieselbe strukturelle Lösung wie oben: config.OBSIDIAN_VAULT_PATH
wird für JEDEN Test zentral auf ein Wegwerfverzeichnis umgeleitet, statt jeden betroffenen und
künftigen ADR-Test einzeln um einen expliziten vault_path zu ergänzen.
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
    monkeypatch.setattr("agents.orchestrator.start_trials_from_report", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(
        "agents.orchestrator.evaluate_trials",
        lambda *a, **k: {"promoted": [], "rejected": [], "rolled_back": []}, raising=False,
    )
    # Hängt Status-Ereignisse an die versionierte memory/team_lessons.jsonl an.
    monkeypatch.setattr(
        "agents.orchestrator.auto_link_lessons_to_rules", lambda *a, **k: [], raising=False,
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
def _isolate_team_lessons(tmp_path_factory, monkeypatch):
    """core/team_memory.record_lesson() hängt bei Wiederholungen ein Ereignis an - viele Tests
    lösen über process() Lektionen aus. Jeder Test arbeitet deshalb auf einer Kopie der echten,
    versionierten memory/team_lessons.jsonl (Lesen bleibt realistisch, Schreiben ist folgenlos).
    Tests, die TEAM_MEMORY_FILE selbst patchen, überschreiben diese Umleitung wie bisher."""
    import shutil

    import core.team_memory as team_memory

    # Eigenes Verzeichnis statt tmp_path des Tests - manche Tests erwarten ihr tmp_path leer.
    copy = tmp_path_factory.mktemp("team_lessons") / "team_lessons_copy.jsonl"
    if team_memory.TEAM_MEMORY_FILE.exists():
        shutil.copy(team_memory.TEAM_MEMORY_FILE, copy)
    monkeypatch.setattr(team_memory, "TEAM_MEMORY_FILE", copy)


@pytest.fixture(autouse=True)
def _isolate_model_ab_trials(_run_log_sandbox, monkeypatch):
    """Ein echter memory/model_ab_trials.json auf dem Entwicklerrechner würde über
    config.get_model_for_agent() zufällig Kandidatenmodelle in Modell-Routing-Tests einstreuen."""
    monkeypatch.setattr("config.MODEL_AB_TRIALS_FILE", str(_run_log_sandbox / "model_ab_trials_absent.json"))


@pytest.fixture(autouse=True)
def _isolate_conversation_history(_run_log_sandbox, monkeypatch):
    """Realer Fund (Analyse auditlog_sentinel 2026-09-10): memory/history_default.json enthielt
    `<MagicMock name='ProjectVerifier().check_runtime_smoke().entrypoint'>`-Texte - jeder Test,
    der einen echten Orchestrator() baut, schrieb über ConversationHistory in die ECHTE
    Konsolen-Historie, die der Planer später als Gesprächskontext liest."""
    history_dir = _run_log_sandbox / "history"
    history_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("memory.conversation_history.MEMORY_DIR", str(history_dir))


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


@pytest.fixture(scope="session")
def _obsidian_vault_sandbox(tmp_path_factory):
    return tmp_path_factory.mktemp("obsidian_vault")


@pytest.fixture(autouse=True)
def _isolate_obsidian_adr_export(_obsidian_vault_sandbox, monkeypatch):
    """Leitet den Obsidian-Vault-Pfad für JEDEN Test in ein Wegwerfverzeichnis um. write_adr()
    (core/adr.py) exportiert intern immer auch nach Obsidian und fällt dabei ohne explizit
    übergebenen vault_path auf config.OBSIDIAN_VAULT_PATH zurück - ohne diese Umleitung landen
    ADR-Tests mit echten (oder tempfile.mkdtemp()-generierten) Projektordnern als Seiteneffekt
    im echten, produktiven Vault (siehe Modul-Docstring oben)."""
    monkeypatch.setattr("config.OBSIDIAN_VAULT_PATH", str(_obsidian_vault_sandbox))


@pytest.fixture(autouse=True, scope="session")
def _ensure_ci_test_gemini_key():
    """Stellt sicher, dass in CI/Umgebungen ohne echte .env immer ein Dummy-Key für gemockte
    Gemini-Tests vorhanden ist, sodass _DynamicGeminiClientProxy und GeminiClient initialisierbar sind."""
    import os

    import config
    import core.llm_factory as lf

    if not config.GEMINI_API_KEYS and not os.getenv("GEMINI_API_KEY"):
        dummy_key = "test-ci-dummy-gemini-key"
        os.environ["GEMINI_API_KEY"] = dummy_key
        config.GEMINI_API_KEY = dummy_key
        config.GEMINI_API_KEYS = [dummy_key]
        lf.GEMINI_API_KEYS = [dummy_key]
