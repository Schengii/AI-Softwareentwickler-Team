"""
tests/test_goal_loop.py – Unit-Tests für den autonomen Ziel- und Iterations-Loop.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.goal_loop import (
    GoalIterationReport,
    GoalLoopResult,
    GoalLoopRunner,
)
from core.token_guard import token_guard


def test_goal_iteration_report_and_summary():
    """Testet die Struktur und Formatierung des GoalLoop-Abschlussberichts."""
    it1 = GoalIterationReport(
        iteration=1,
        prompt_used="Baue Notiz-API",
        summary="Backend erstellt",
        verification_ok=False,
        failure_detail="1 Testfehler",
        goal_reached=False,
        evaluation_reason="Tests noch rot",
    )
    it2 = GoalIterationReport(
        iteration=2,
        prompt_used="Behebe Testfehler in test_api.py",
        summary="Tests repariert",
        verification_ok=True,
        failure_detail="",
        goal_reached=True,
        evaluation_reason="Alle Tests grün",
    )

    res = GoalLoopResult(
        goal="Baue Notiz-API",
        project_slug="notiz_api",
        success=True,
        total_iterations=2,
        iterations=[it1, it2],
        final_message="Ziel erfolgreich erreicht.",
    )

    summary = res.format_summary()
    assert "✅" in summary
    assert "notiz_api" in summary
    assert "Iteration 1" in summary
    assert "Iteration 2" in summary
    assert "Ziel erfolgreich" in summary


@pytest.mark.anyio
async def test_goal_loop_single_iteration_success(tmp_path):
    """Testet, dass der Loop sofort stoppt, wenn in Iteration 1 das Ziel erreicht und verifiziert ist."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Backend und Tests erfolgreich erstellt.")
    mock_orchestrator.last_task_summary = "Notiz-API implementiert und verifiziert"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    with patch("core.goal_loop.read_status") as mock_history, \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval:

        mock_history.return_value = [{"verification_ok": True, "failure_detail": ""}]
        mock_eval.return_value = {"goal_reached": True, "reason": "Alles grün", "next_prompt": ""}

        res = await runner.run(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=3,
        )

        assert res.success is True
        assert res.total_iterations == 1
        assert len(res.iterations) == 1
        assert mock_orchestrator.process.call_count == 1


@pytest.mark.anyio
async def test_goal_loop_multi_iteration_recovery(tmp_path):
    """Testet, dass der Loop bei anfänglichem Fehlschlag einen Folge-Prompt generiert und weiterarbeitet."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(side_effect=[
        "Iteration 1: Backend gebaut, aber Test schlug fehl.",
        "Iteration 2: Testfehler behoben, alles grün.",
    ])
    mock_orchestrator.last_task_summary = "Tests repariert"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    eval_calls = [
        {"goal_reached": False, "reason": "1 Testfehler", "next_prompt": "Repariere den Testfehler in tests/test_api.py"},
        {"goal_reached": True, "reason": "Alle Tests bestanden", "next_prompt": ""},
    ]

    histories = [
        [{"verification_ok": False, "failure_detail": "Assert 200 == 404"}],
        [{"verification_ok": True, "failure_detail": ""}],
    ]

    with patch("core.goal_loop.read_status", side_effect=histories), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", side_effect=eval_calls):

        res = await runner.run(
            goal="Erstelle eine Notizen-API mit Tests",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=4,
        )

        assert res.success is True
        assert res.total_iterations == 2
        assert mock_orchestrator.process.call_count == 2
        # Der zweite Aufruf nutzt den automatisch generierten Folge-Prompt
        assert "Repariere den Testfehler" in mock_orchestrator.process.call_args_list[1].kwargs["user_request"]


@pytest.mark.anyio
async def test_goal_loop_cancellation(tmp_path):
    """Testet den kooperativen Abbruch per Cancel-Event."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Abbruch")
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    res = await runner.run(
        goal="Testziel",
        project_dir=str(tmp_path / "test_proj"),
        max_iterations=5,
        cancel_requested=lambda: True,  # Sofort abgebrochen
    )

    assert res.cancelled is True
    assert res.total_iterations == 0
    assert mock_orchestrator.process.call_count == 0


@pytest.mark.anyio
async def test_goal_loop_stagnation_aborts_early(tmp_path):
    """
    Liefert die Verifikation zwei Iterationen in Folge exakt denselben Fehler, dreht sich der
    Loop im Kreis (ein Bug, den das Team offenbar nicht selbst löst) - der Loop muss dann
    VOR max_iterations abbrechen statt weitere Iterationen zu verschwenden.
    """
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Testfehler weiterhin vorhanden.")
    mock_orchestrator.last_task_summary = "Fix-Versuch"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    same_failure = [{"verification_ok": False, "failure_detail": "Assert 200 == 404 in test_api.py"}]
    eval_result = {"goal_reached": False, "reason": "Testfehler weiterhin vorhanden", "next_prompt": "Repariere erneut"}

    with patch("core.goal_loop.read_status", return_value=same_failure), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = eval_result

        res = await runner.run(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=5,
        )

        assert res.success is False
        # Iteration 1 liefert den Fehler zum ersten Mal, Iteration 2 wiederholt ihn identisch
        # -> Abbruch nach Iteration 2, NICHT erst nach den vollen 5 Iterationen.
        assert res.total_iterations == 2
        assert mock_orchestrator.process.call_count == 2
        assert "stagnier" in res.final_message.lower()


@pytest.mark.anyio
async def test_goal_loop_stagnation_detects_near_duplicate_failure(tmp_path):
    """
    Realer Fund (Team-Retrospektive 2026-09-06): der bisherige Stagnations-Vergleich verlangte
    exakte String-Gleichheit von failure_detail - ein Traceback mit leicht verschobener
    Zeilennummer (beim iterativen Fixen derselben Ursache real häufig) umging die Erkennung
    komplett. Muss auch dann abbrechen, wenn sich nur die Zeilennummer im sonst identischen
    Fehler unterscheidet.
    """
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Testfehler weiterhin vorhanden.")
    mock_orchestrator.last_task_summary = "Fix-Versuch"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    failures = [
        {"verification_ok": False, "failure_detail": "Assert 200 == 404 in test_api.py:42"},
        {"verification_ok": False, "failure_detail": "Assert 200 == 404 in test_api.py:57"},
    ]
    eval_result = {"goal_reached": False, "reason": "Testfehler weiterhin vorhanden", "next_prompt": "Repariere erneut"}

    def _status(project_dir):
        return [failures.pop(0)] if failures else [{"verification_ok": False, "failure_detail": "x"}]

    with patch("core.goal_loop.read_status", side_effect=_status), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = eval_result

        res = await runner.run(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=5,
        )

        assert res.total_iterations == 2
        assert "stagnier" in res.final_message.lower()


@pytest.mark.anyio
async def test_goal_loop_no_stagnation_when_failures_are_structurally_different(tmp_path):
    """Gegenprobe: zwei tatsächlich unterschiedliche Fehler (nicht nur andere Zeilennummer)
    dürfen NICHT als Stagnation gewertet werden - der Loop soll normal weiterlaufen."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Weiterer Versuch.")
    mock_orchestrator.last_task_summary = "Fix-Versuch"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    failures = [
        {"verification_ok": False, "failure_detail": "Assert 200 == 404 in test_api.py:42"},
        {"verification_ok": False, "failure_detail": "ImportError: keine Modul namens flask"},
        {"verification_ok": True, "failure_detail": ""},
    ]
    eval_results = [
        {"goal_reached": False, "reason": "r1", "next_prompt": "weiter"},
        {"goal_reached": False, "reason": "r2", "next_prompt": "weiter"},
        {"goal_reached": True, "reason": "fertig", "next_prompt": ""},
    ]

    with patch("core.goal_loop.read_status", side_effect=lambda project_dir: [failures.pop(0)]), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval:
        mock_eval.side_effect = eval_results

        res = await runner.run(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=5,
        )

        assert res.total_iterations == 3
        assert res.success is True


@pytest.mark.anyio
async def test_goal_loop_stagnation_detects_oscillating_non_consecutive_failure(tmp_path):
    """
    Folgeanalyse 2026-09-14 ("Oszillations-Fund"): der Fix für Fehler A bricht Fehler B, der
    Fix für B bricht wieder A - ein real zu erwartendes Muster, das die bisherige, rein
    konsekutive Stagnationserkennung NIE erkannte (aufeinanderfolgende Iterationen unterscheiden
    sich bei einer Oszillation immer). Tatsächlich ausgeführter Repro vor diesem Fix bestätigte:
    das Muster A-B-A-B-A lief alle 5 Iterationen durch, ohne dass die Erkennung je ansprach.
    Fehler A taucht hier in Iteration 3 zum ZWEITEN Mal auf (zuerst in Iteration 1, NICHT der
    unmittelbaren Vorrunde Iteration 2) - muss trotzdem als Stagnation erkannt werden.
    """
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Weiterer Versuch.")
    mock_orchestrator.last_task_summary = "Fix-Versuch"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    failures = [
        {"verification_ok": False, "failure_detail": "AssertionError in test_auth.py:10"},
        {"verification_ok": False, "failure_detail": "ImportError: fehlt Modul httpx"},
        {"verification_ok": False, "failure_detail": "AssertionError in test_auth.py:15"},  # = Iteration 1, nur Zeilennummer anders
        {"verification_ok": False, "failure_detail": "ImportError: fehlt Modul httpx"},
        {"verification_ok": False, "failure_detail": "AssertionError in test_auth.py:22"},
    ]
    eval_result = {"goal_reached": False, "reason": "weiter", "next_prompt": "nochmal versuchen"}

    with patch("core.goal_loop.read_status", side_effect=lambda project_dir: [failures.pop(0)]), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = eval_result

        res = await runner.run(
            goal="Baue eine Auth-API",
            project_dir=str(tmp_path / "auth_api"),
            max_iterations=5,
        )

        assert res.total_iterations == 3  # Abbruch bei der Wiederkehr von Fehler A, nicht erst nach 5
        assert res.success is False
        assert "stagnier" in res.final_message.lower()
        # Genau EIN next_prompt/Fix-Zyklus für Fehler B wurde probiert, kein zweiter -
        # bestätigt, dass der Loop wirklich früh abbrach statt sich weiterzudrehen.
        assert mock_orchestrator.process.call_count == 3


@pytest.mark.anyio
async def test_goal_loop_cumulative_token_budget_aborts(tmp_path, monkeypatch):
    """
    GOAL_LOOP_MAX_TOTAL_TOKENS begrenzt den Gesamtverbrauch ÜBER ALLE Iterationen hinweg -
    unabhängig vom (pro Einzellauf geltenden) MAX_RUN_TOKENS.
    """
    monkeypatch.setattr("core.goal_loop.GOAL_LOOP_MAX_TOTAL_TOKENS", 100)

    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Iteration abgeschlossen.")
    mock_orchestrator.last_task_summary = "Weiterentwicklung"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    # Unterschiedliche failure_detail pro Iteration, damit die separate Stagnations-Erkennung
    # (siehe test_goal_loop_stagnation_aborts_early) hier NICHT zuerst greift.
    histories = [
        [{"verification_ok": False, "failure_detail": "Fehler A"}],
        [{"verification_ok": False, "failure_detail": "Fehler B"}],
    ]

    with patch("core.goal_loop.read_status", side_effect=histories), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval, \
         patch.object(token_guard, "get_summary") as mock_summary:
        mock_eval.return_value = {"goal_reached": False, "reason": "noch offen", "next_prompt": "weiter"}
        # Simuliert echten Tokenverbrauch: jeder Aufruf zeigt 80 weitere Tokens seit Loop-Start an.
        mock_summary.side_effect = [
            {"grand_total_tokens": 0},    # loop_start_tokens
            {"grand_total_tokens": 80},   # nach Iteration 1 (unter dem Budget von 100)
            {"grand_total_tokens": 160},  # nach Iteration 2 (>= 100 -> Abbruch)
        ]

        res = await runner.run(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=5,
        )

        assert res.success is False
        assert res.total_iterations == 2
        assert "budget" in res.final_message.lower()


@pytest.mark.anyio
async def test_goal_loop_empty_goal_returns_immediately_without_orchestrator_call():
    """Ein leeres/nur-Whitespace-Ziel darf den Orchestrator nie starten (kein Tokenverbrauch)."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="sollte nie aufgerufen werden")
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    res = await runner.run(goal="   ", max_iterations=3)

    assert res.success is False
    assert res.total_iterations == 0
    assert mock_orchestrator.process.call_count == 0
    assert "leeres ziel" in res.final_message.lower()


@pytest.mark.anyio
async def test_goal_loop_max_iterations_below_one_is_clamped(tmp_path):
    """max_iterations=0 (oder negativ) darf den Loop nicht stillschweigend zu einem No-Op machen."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(return_value="Iteration 1 erledigt.")
    mock_orchestrator.last_task_summary = "Erledigt"
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    with patch("core.goal_loop.read_status", return_value=[{"verification_ok": True, "failure_detail": ""}]), \
         patch.object(runner, "_evaluate_and_synthesize_next_step", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"goal_reached": True, "reason": "grün", "next_prompt": ""}

        res = await runner.run(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path / "notizen_api"),
            max_iterations=0,
        )

        assert mock_orchestrator.process.call_count == 1
        assert res.total_iterations == 1
        assert res.success is True


@pytest.mark.anyio
async def test_goal_loop_exception_reports_crash_not_generic_max_iterations_message(tmp_path):
    """
    Eine Exception mitten im Orchestrator-Lauf muss als echter Fehler im Abschlussbericht
    sichtbar sein - nicht als die irreführende Standardmeldung "max. Iterationen erreicht".
    """
    mock_orchestrator = MagicMock()
    mock_orchestrator.process = AsyncMock(side_effect=RuntimeError("Provider-Kette komplett erschöpft"))
    mock_orchestrator.get_workspace_manager = MagicMock()

    runner = GoalLoopRunner(orchestrator=mock_orchestrator)

    res = await runner.run(
        goal="Erstelle eine Notizen-API",
        project_dir=str(tmp_path / "notizen_api"),
        max_iterations=5,
    )

    assert res.success is False
    assert res.total_iterations == 1
    assert "unerwarteter fehler" in res.final_message.lower()
    assert "Provider-Kette komplett erschöpft" in res.final_message


@pytest.mark.anyio
async def test_eval_prompt_includes_verification_trend_warning(tmp_path):
    """
    Punkt 3 der Team-Retrospektive (2026-09-06): core/optimization_advisor.py erkennt einen
    teamweiten Verifikations-Trend bereits - der Goal-Loop soll diesen proaktiv in seinen
    Eval-Prompt aufnehmen, statt ihn zu ignorieren und erst am eigenen Scheitern zu erkennen.
    """
    runner = GoalLoopRunner(orchestrator=MagicMock())
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value='{"goal_reached": false, "reason": "x", "next_prompt": "y"}')

    with patch("core.goal_loop.get_recent_verification_trend_warning", return_value="⚠️ Team-weiter Verifikations-Trend: nur 1/3 grün."), \
         patch("core.goal_loop.LLMFactory.create_for_model", return_value=mock_llm):
        await runner._evaluate_and_synthesize_next_step(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path),
            iteration=1,
            max_iterations=5,
            summary="x",
            verification_ok=False,
            failure_detail="x",
            result_text="x",
        )

    sent_prompt = mock_llm.generate.call_args[0][0]
    assert "Team-weiter Verifikations-Trend" in sent_prompt


@pytest.mark.anyio
async def test_eval_prompt_omits_trend_line_when_no_warning(tmp_path):
    """Gegenprobe: der Normalfall ohne Trend darf keine leere/kaputte Zeile in den Prompt
    einschleusen."""
    runner = GoalLoopRunner(orchestrator=MagicMock())
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value='{"goal_reached": false, "reason": "x", "next_prompt": "y"}')

    with patch("core.goal_loop.get_recent_verification_trend_warning", return_value=""), \
         patch("core.goal_loop.LLMFactory.create_for_model", return_value=mock_llm):
        await runner._evaluate_and_synthesize_next_step(
            goal="Erstelle eine Notizen-API",
            project_dir=str(tmp_path),
            iteration=1,
            max_iterations=5,
            summary="x",
            verification_ok=False,
            failure_detail="x",
            result_text="x",
        )

    sent_prompt = mock_llm.generate.call_args[0][0]
    assert "Team-weiter Verifikations-Trend" not in sent_prompt
