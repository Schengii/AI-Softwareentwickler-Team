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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
