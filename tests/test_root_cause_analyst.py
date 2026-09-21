"""
tests/test_root_cause_analyst.py – Testet core/root_cause_analyst.py (automatisierter
Root-Cause-Analyst mit echtem, read-only Tool-Zugriff nach gescheiterten Läufen).

Gesamtsystem-Analyse 2026-09-14, Punkt 3.1: der bisherige, immer laufende Retrospektive-/
Trainer-Schritt (agents/orchestrator/retrospective.py) bekommt nur stark gekürzte Prosa-Auszüge
OHNE Tool-Zugriff - dieses Modul soll bei echten Warnsignalen (Verifikation gescheitert, Absturz,
wiederkehrendes Muster) stattdessen eine echte Tiefenanalyse mit Zugriff auf die rohen Logs und
den tatsächlichen Code auslösen.
"""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store_module
import core.root_cause_analyst as root_cause_analyst_module
import core.team_memory as team_memory_module
from core.backlog_store import get_ticket, list_tickets
from core.backlog_worker import _AUTONOMOUS_SOURCES
from core.message_bus import AgentResult
from core.root_cause_analyst import (
    TICKET_SOURCE,
    build_analysis_task,
    extract_findings,
    gather_evidence,
    record_findings_as_tickets,
    run_analysis,
    should_trigger,
)

_WELL_FORMED_RESPONSE = """Der Lauf scheiterte an einer echten Framework-Ursache.

### Befund 1
**Kategorie:** framework
**Titel:** Budget-Reserve blockiert die Verifikation
**Root Cause:** department.py setzt budget_aborted=True bereits beim Erreichen der reinen
Generierungs-Reserve, wodurch __init__.py die Verifikation komplett überspringt.
**Empfehlung:** generation_budget_reached von budget_aborted trennen, siehe budget.py.

### Befund 2
**Kategorie:** projekt
**Titel:** Fehlende JavaScript-Datei im Frontend
**Root Cause:** static/index.html bindet kein Skript ein, obwohl ein interaktives Dashboard
verlangt war.
**Empfehlung:** completeness.py soll fehlende .js-Dateien bei Formularen/Buttons erkennen.
"""


class TestShouldTrigger(unittest.TestCase):
    def test_no_trigger_on_clean_success(self):
        result = should_trigger(verification_ok=True, files_written=5)
        self.assertFalse(result.should_run)

    def test_triggers_on_crash_regardless_of_files_written(self):
        result = should_trigger(verification_ok=False, files_written=0, aborted=True)
        self.assertTrue(result.should_run)
        self.assertIn("Exception", result.reason)

    def test_triggers_on_failed_verification_with_real_work(self):
        result = should_trigger(verification_ok=False, files_written=3)
        self.assertTrue(result.should_run)

    def test_does_not_trigger_on_failed_verification_without_any_files(self):
        """files_written == 0 ist ein ANDERES, bereits bestehendes Signal
        (false_success_no_source_files) - keine Verifikationsursache, die sich im Code
        nachvollziehen ließe, siehe should_trigger()-Docstring."""
        result = should_trigger(verification_ok=False, files_written=0)
        self.assertFalse(result.should_run)

    def test_triggers_on_recurring_signature_even_if_verification_ok(self):
        result = should_trigger(verification_ok=True, files_written=5, recurring_signature_seen_before=True)
        self.assertTrue(result.should_run)

    def test_does_not_trigger_on_purely_informational_failure(self):
        """P3-3 (ROADMAP_TEMP.md): ein rein informativer Befund (z.B. lint/F841, in
        Millisekunden per ruff --fix --unsafe-fixes behebbar) darf allein keine kostenpflichtige
        Tiefenanalyse mehr auslösen, selbst wenn verification_ok=False und Dateien geschrieben
        wurden - echter Fund: root-cause-cachegrid_proxy-unbenutzte-variablenzuweisung."""
        result = should_trigger(verification_ok=False, files_written=3, has_blocking_failure=False)
        self.assertFalse(result.should_run)
        self.assertIn("informativ", result.reason)

    def test_still_triggers_when_a_real_blocking_failure_is_present(self):
        result = should_trigger(verification_ok=False, files_written=3, has_blocking_failure=True)
        self.assertTrue(result.should_run)

    def test_default_has_blocking_failure_preserves_prior_behavior(self):
        """Aufrufer ohne das neue Argument (z.B. bestehende Tests) verhalten sich unverändert -
        has_blocking_failure ist bewusst standardmäßig True."""
        result = should_trigger(verification_ok=False, files_written=3)
        self.assertTrue(result.should_run)


class TestGatherEvidence(unittest.TestCase):
    def test_includes_request_and_capped_log_tails(self):
        with tempfile.TemporaryDirectory() as d:
            run_log = Path(d) / "run.jsonl"
            run_log.write_text("A" * 50_000 + "ENDE_LAUF_LOG", encoding="utf-8")
            verif_log = Path(d) / "verif.log"
            verif_log.write_text("B" * 50_000 + "ENDE_VERIF_LOG", encoding="utf-8")

            evidence = gather_evidence(
                project_slug="testproj", user_request="baue etwas",
                verification_summary="Tests fehlgeschlagen",
                run_log_path=run_log, verification_log_path=verif_log,
            )
        self.assertIn("testproj", evidence)
        self.assertIn("baue etwas", evidence)
        self.assertIn("Tests fehlgeschlagen", evidence)
        self.assertIn("ENDE_LAUF_LOG", evidence)
        self.assertIn("ENDE_VERIF_LOG", evidence)
        # Deutlich kleiner als die volle 50.000+-Zeichen-Eingabe je Datei - Deckelung wirkt.
        self.assertLess(len(evidence), 40_000)

    def test_missing_log_files_do_not_raise(self):
        evidence = gather_evidence(
            project_slug="testproj", user_request="baue etwas",
            run_log_path=Path("/pfad/existiert/nicht.jsonl"),
            verification_log_path=None,
        )
        self.assertIn("testproj", evidence)


class TestBuildAnalysisTask(unittest.TestCase):
    def test_task_grants_read_only_tool_access_to_base_dir(self):
        task = build_analysis_task("meinprojekt", "EVIDENZ-TEXT")
        self.assertEqual(task.agent_id, "agent_trainer")
        self.assertTrue(task.allow_tools)
        self.assertTrue(task.tools_read_only)
        self.assertIsNotNone(task.project_dir)
        self.assertIn("EVIDENZ-TEXT", task.context)


_RESPONSE_WITH_BLANK_LINES_BETWEEN_FIELDS = """Kurze Einleitung.

### Befund 1

**Kategorie:** framework

**Titel:** Budget-Reserve blockiert die Verifikation

**Root Cause:** department.py setzt budget_aborted=True bereits beim Erreichen der reinen
Generierungs-Reserve, wodurch __init__.py die Verifikation komplett überspringt.

**Empfehlung:** generation_budget_reached von budget_aborted trennen, siehe budget.py.

### Befund 2

**Kategorie:** projekt

**Titel:** Fehlende JavaScript-Datei im Frontend

**Root Cause:** static/index.html bindet kein Skript ein, obwohl ein interaktives Dashboard
verlangt war.

**Empfehlung:** completeness.py soll fehlende .js-Dateien bei Formularen/Buttons erkennen.
"""


class TestExtractFindings(unittest.TestCase):
    def test_parses_both_categories(self):
        findings = extract_findings(_WELL_FORMED_RESPONSE)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["category"], "framework")
        self.assertIn("Budget-Reserve", findings[0]["title"])
        self.assertEqual(findings[1]["category"], "projekt")

    def test_malformed_response_yields_no_findings_without_raising(self):
        findings = extract_findings("Ich habe leider keine klare Ursache gefunden, sorry.")
        self.assertEqual(findings, [])

    def test_parses_findings_with_blank_lines_between_fields(self):
        """Folgeanalyse 2026-09-14, Befund 1 (kritisch): reale LLM-Antworten setzen praktisch
        immer Leerzeilen zwischen fett hervorgehobenen Feldern - die ursprüngliche Version
        lieferte hier 0 statt 2 Befunde, obwohl der teure Werkzeug-Loop bereits gelaufen war."""
        findings = extract_findings(_RESPONSE_WITH_BLANK_LINES_BETWEEN_FIELDS)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["category"], "framework")
        self.assertIn("Budget-Reserve", findings[0]["title"])
        self.assertIn("Generierungs-Reserve", findings[0]["root_cause"])
        self.assertIn("budget.py", findings[0]["recommendation"])
        self.assertEqual(findings[1]["category"], "projekt")

    def test_fields_in_different_order_still_parse(self):
        """_parse_fields() lokalisiert Label-Positionen unabhängig von ihrer Reihenfolge -
        robuster als ein starres, sequenzielles Block-Pattern."""
        response = """### Befund 1
**Titel:** Vertauschte Feldreihenfolge
**Empfehlung:** Reihenfolge ignorieren.
**Kategorie:** framework
**Root Cause:** Das Modell hat die Felder nicht in der Prompt-Reihenfolge geschrieben.
"""
        findings = extract_findings(response)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["title"], "Vertauschte Feldreihenfolge")
        self.assertEqual(findings[0]["category"], "framework")

    def test_missing_category_label_defaults_to_projekt(self):
        response = """### Befund 1
**Titel:** Kategorie-Label vergessen
**Root Cause:** Das Modell hat das Kategorie-Feld komplett ausgelassen.
**Empfehlung:** Trotzdem als Befund werten, nur sicherheitshalber niedriger priorisiert.
"""
        findings = extract_findings(response)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "projekt")

    def test_word_empfehlung_inside_prose_does_not_split_a_field(self):
        """_FIELD_LABEL_RE ist am Zeilenanfang verankert (^[ \\t]*) - ein Vorkommen des Wortes
        mitten in einem Satz darf ein Feld nicht vorzeitig abschneiden."""
        response = """### Befund 1
**Titel:** Testfall für Wortkollision
**Root Cause:** Der Tester braucht hier eine klare Empfehlung, bevor er weiterarbeitet.
**Empfehlung:** Die komplette Root-Cause-Regel wie oben beschrieben umsetzen.
"""
        findings = extract_findings(response)
        self.assertEqual(len(findings), 1)
        self.assertIn("bevor er weiterarbeitet", findings[0]["root_cause"])
        self.assertIn("wie oben beschrieben umsetzen", findings[0]["recommendation"])


class TestRecordFindingsAsTickets(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        # record_findings_as_tickets() spiegelt jeden Befund zusätzlich als Team-Lektion
        # (core/team_memory.py.record_lesson()) - ohne diesen Patch würde jeder Testlauf echte
        # Einträge in memory/team_lessons.jsonl hinterlassen (real passiert, per git diff
        # entdeckt und rückgängig gemacht, bevor dieser Patch ergänzt wurde).
        self._lessons_patcher = patch.object(team_memory_module, "TEAM_MEMORY_FILE", Path(self.temp_dir) / "team_lessons.jsonl")
        self._lessons_patcher.start()
        self.addCleanup(self._lessons_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_creates_one_ticket_per_finding_with_correct_source_and_priority(self):
        findings = extract_findings(_WELL_FORMED_RESPONSE)
        ticket_ids = record_findings_as_tickets("meinprojekt", findings)

        self.assertEqual(len(ticket_ids), 2)
        framework_ticket = get_ticket(ticket_ids[0])
        self.assertEqual(framework_ticket.source, TICKET_SOURCE)
        self.assertEqual(framework_ticket.priority, 1)  # framework-Befunde: hohe Priorität
        self.assertEqual(framework_ticket.status, "blocked")
        self.assertIn("Budget-Reserve", framework_ticket.title)
        self.assertIn("Generierungs-Reserve", framework_ticket.detail)

        project_ticket = get_ticket(ticket_ids[1])
        self.assertEqual(project_ticket.priority, 2)
        self.assertEqual(project_ticket.status, "todo")

    def test_ticket_source_is_never_autonomous(self):
        """Framework-Änderungen verdienen ein menschliches Review - core/backlog_worker.py darf
        einen Root-Cause-Befund NIE selbstständig als Programmierauftrag umsetzen."""
        self.assertNotIn(TICKET_SOURCE, _AUTONOMOUS_SOURCES)

    def test_repeated_identical_finding_updates_same_ticket_instead_of_duplicating(self):
        findings = extract_findings(_WELL_FORMED_RESPONSE)
        first_ids = record_findings_as_tickets("meinprojekt", findings)
        second_ids = record_findings_as_tickets("meinprojekt", findings)

        self.assertEqual(first_ids, second_ids)
        all_root_cause_tickets = [t for t in list_tickets() if t.source == TICKET_SOURCE]
        self.assertEqual(len(all_root_cause_tickets), 2)

    def test_regression_test_is_embedded_in_ticket_detail_when_present(self):
        """Folgeanalyse 2026-09-14, Empfehlung 1: ein Regressionstest-Vorschlag soll direkt im
        Ticket sichtbar sein, nicht nur in der rohen LLM-Antwort verschwinden."""
        response = """### Befund 1
**Kategorie:** framework
**Titel:** Fehlender Cooldown
**Root Cause:** Kein Kostenschutz vorhanden.
**Empfehlung:** Cooldown ergänzen.
**Regressionstest-Vorschlag:**
```python
def test_cooldown_blocks_second_call():
    assert True
```
"""
        findings = extract_findings(response)
        ticket_ids = record_findings_as_tickets("meinprojekt", findings)
        ticket = get_ticket(ticket_ids[0])
        self.assertIn("Regressionstest-Vorschlag", ticket.detail)
        self.assertIn("def test_cooldown_blocks_second_call", ticket.detail)

    def test_no_regression_test_section_when_model_omitted_it(self):
        findings = extract_findings(_WELL_FORMED_RESPONSE)
        ticket_ids = record_findings_as_tickets("meinprojekt", findings)
        ticket = get_ticket(ticket_ids[0])
        self.assertNotIn("Regressionstest-Vorschlag", ticket.detail)


class TestTeamwideEscalation(unittest.TestCase):
    """Folgeanalyse 2026-09-14, Empfehlung 3: dieselbe Framework-Schwachstelle an mehreren
    UNABHÄNGIGEN Projekten ist ein stärkeres Signal als ein einzelnes Projekt-Ticket."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._lessons_patcher = patch.object(team_memory_module, "TEAM_MEMORY_FILE", Path(self.temp_dir) / "team_lessons.jsonl")
        self._lessons_patcher.start()
        self.addCleanup(self._lessons_patcher.stop)
        self._notify_patcher = patch.object(root_cause_analyst_module, "notify_external")
        self.mock_notify = self._notify_patcher.start()
        self.addCleanup(self._notify_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _framework_finding(self, title="Fehlendes Async-Setup"):
        return [{
            "category": "framework", "title": title,
            "root_cause": "Immer derselbe strukturelle Grund.", "recommendation": "Immer dieselbe Empfehlung.",
            "regression_test": "",
        }]

    def test_no_escalation_below_threshold(self):
        record_findings_as_tickets("projekt_a", self._framework_finding())
        record_findings_as_tickets("projekt_b", self._framework_finding())

        self.assertIsNone(get_ticket("root-cause-teamwide-fehlendes-async-setup"))
        self.mock_notify.assert_not_called()

    def test_escalates_and_notifies_at_third_independent_project(self):
        record_findings_as_tickets("projekt_a", self._framework_finding())
        record_findings_as_tickets("projekt_b", self._framework_finding())
        record_findings_as_tickets("projekt_c", self._framework_finding())

        teamwide = get_ticket("root-cause-teamwide-fehlendes-async-setup")
        self.assertIsNotNone(teamwide)
        self.assertIn("projekt_a", teamwide.detail)
        self.assertIn("projekt_b", teamwide.detail)
        self.assertIn("projekt_c", teamwide.detail)
        self.assertIn("3", teamwide.title)
        self.mock_notify.assert_called_once()

    def test_repeated_run_of_same_project_does_not_renotify(self):
        """Ein wiederholter Lauf DESSELBEN bereits bekannten Projekts darf nicht bei jedem Mal
        erneut eskalieren/benachrichtigen - nur ein GENUIN NEUES Projekt löst das aus."""
        record_findings_as_tickets("projekt_a", self._framework_finding())
        record_findings_as_tickets("projekt_b", self._framework_finding())
        record_findings_as_tickets("projekt_c", self._framework_finding())
        self.mock_notify.assert_called_once()

        record_findings_as_tickets("projekt_a", self._framework_finding())  # erneuter Lauf, kein neues Projekt
        self.mock_notify.assert_called_once()  # weiterhin nur EIN Aufruf

    def test_fourth_independent_project_does_not_renotify_but_updates_ticket(self):
        for slug in ("projekt_a", "projekt_b", "projekt_c"):
            record_findings_as_tickets(slug, self._framework_finding())
        self.mock_notify.assert_called_once()

        record_findings_as_tickets("projekt_d", self._framework_finding())
        self.assertEqual(self.mock_notify.call_count, 2)
        teamwide = get_ticket("root-cause-teamwide-fehlendes-async-setup")
        self.assertIn("projekt_d", teamwide.detail)

    def test_project_scoped_ticket_is_never_autonomous(self):
        self.assertNotIn(TICKET_SOURCE, _AUTONOMOUS_SOURCES)


class TestActionRate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_backlog_returns_zero_rate(self):
        rate = root_cause_analyst_module.get_action_rate()
        self.assertEqual(rate.total, 0)
        self.assertEqual(rate.action_rate_pct, 0.0)

    def test_counts_done_vs_open_across_projects(self):
        from core.backlog_store import upsert_ticket

        upsert_ticket("root-cause-a-x", "X", TICKET_SOURCE, "done", project_slug="a")
        upsert_ticket("root-cause-b-y", "Y", TICKET_SOURCE, "blocked", project_slug="b")
        upsert_ticket("root-cause-c-z", "Z", TICKET_SOURCE, "todo", project_slug="c")
        upsert_ticket("unrelated-ticket", "Unrelated", "cli", "done")  # andere Quelle, muss ignoriert werden

        rate = root_cause_analyst_module.get_action_rate()
        self.assertEqual(rate.total, 3)
        self.assertEqual(rate.done, 1)
        self.assertEqual(rate.open, 2)
        self.assertAlmostEqual(rate.action_rate_pct, 33.3, places=1)


class TestMaybeRunRootCauseAnalysisWiring(unittest.TestCase):
    """P3-3 (ROADMAP_TEMP.md): Orchestrator._maybe_run_root_cause_analysis() muss
    self.last_verification_outcome auswerten und has_blocking_failure entsprechend an
    should_trigger() weiterreichen - nicht mehr nur das grobe verification_ok."""

    def setUp(self):
        from agents.orchestrator import Orchestrator
        from core.verification_outcome import VerificationOutcome

        self.VerificationOutcome = VerificationOutcome
        self.orchestrator = Orchestrator()
        self.orchestrator.last_project_slug = "proj"

    def _run(self, outcome):
        self.orchestrator.last_verification_outcome = outcome
        with patch("core.root_cause_analyst.run_analysis", new_callable=AsyncMock) as mock_run:
            asyncio.run(self.orchestrator._maybe_run_root_cause_analysis(
                user_request="baue etwas", verification_ok=False, verification_summary="rot",
                files_written=3, project_dir=str(Path(tempfile.gettempdir()) / "nie_existierend_xyz"),
                notify=lambda msg: None,
            ))
        return mock_run

    def test_purely_informational_failure_does_not_trigger_analysis(self):
        outcome = self.VerificationOutcome()
        outcome.record("lint", False, "F841")

        mock_run = self._run(outcome)

        mock_run.assert_not_awaited()

    def test_real_blocking_failure_triggers_analysis(self):
        outcome = self.VerificationOutcome()
        outcome.record("tests", False, "2 failed")

        mock_run = self._run(outcome)

        mock_run.assert_awaited_once()


class TestRunAnalysisEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._lessons_patcher = patch.object(team_memory_module, "TEAM_MEMORY_FILE", Path(self.temp_dir) / "team_lessons.jsonl")
        self._lessons_patcher.start()
        self.addCleanup(self._lessons_patcher.stop)
        # Isoliert den Cooldown-Zustand (Folgeanalyse 2026-09-14, Befund 2) - ohne diesen Patch
        # würde jeder Testfall dieser Klasse den ECHTEN memory/root_cause_analysis_state.json
        # beschreiben (dieselbe Art von Testfehler, die bereits einmal bei team_lessons.jsonl
        # real passiert ist, siehe Kommentar dort).
        self._state_patcher = patch.object(
            root_cause_analyst_module, "ROOT_CAUSE_ANALYSIS_STATE_FILE", Path(self.temp_dir) / "rca_state.json",
        )
        self._state_patcher.start()
        self.addCleanup(self._state_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _fake_orchestrator(self, content=_WELL_FORMED_RESPONSE, success=True, error=None):
        orch = MagicMock()
        orch._run_single_agent = AsyncMock(return_value=AgentResult(
            task_id="t", agent_id="agent_trainer", agent_name="agent_trainer",
            success=success, content=content, error=error,
        ))
        return orch

    def test_successful_analysis_creates_tickets(self):
        orch = self._fake_orchestrator()
        report = asyncio.run(run_analysis(
            orch, project_slug="meinprojekt", user_request="baue etwas",
            verification_summary="Tests fehlgeschlagen",
        ))
        self.assertTrue(report.ok)
        self.assertEqual(len(report.findings), 2)
        self.assertEqual(len(report.ticket_ids), 2)
        orch._run_single_agent.assert_awaited_once()

    def test_agent_failure_surfaces_as_error_without_raising(self):
        orch = self._fake_orchestrator(success=False, content="", error="Provider erschöpft")
        report = asyncio.run(run_analysis(orch, project_slug="meinprojekt", user_request="baue etwas"))
        self.assertFalse(report.ok)
        self.assertIn("Provider erschöpft", report.error)

    def test_exception_from_agent_call_is_caught(self):
        orch = MagicMock()
        orch._run_single_agent = AsyncMock(side_effect=RuntimeError("kaputt"))
        report = asyncio.run(run_analysis(orch, project_slug="meinprojekt", user_request="baue etwas"))
        self.assertFalse(report.ok)
        self.assertIn("kaputt", report.error)

    def test_second_call_within_cooldown_skips_the_expensive_agent_call(self):
        """Folgeanalyse 2026-09-14, Befund 2: ein chronisch scheiterndes Projekt (real
        beobachtet: drei ecochef-Läufe an einem Nachmittag) darf nicht bei jedem Lauf erneut
        den vollen, werkzeugbasierten LLM-Aufruf auslösen."""
        orch = self._fake_orchestrator()
        first = asyncio.run(run_analysis(orch, project_slug="chronisch_kaputt", user_request="baue etwas"))
        self.assertTrue(first.ok)
        orch._run_single_agent.assert_awaited_once()

        second = asyncio.run(run_analysis(orch, project_slug="chronisch_kaputt", user_request="baue etwas erneut"))
        self.assertFalse(second.ok)
        self.assertIn("Cooldown", second.error)
        orch._run_single_agent.assert_awaited_once()  # weiterhin nur EIN Aufruf, kein zweiter

    def test_cooldown_is_scoped_per_project_not_global(self):
        """Ein Cooldown für Projekt A darf ein GLEICHZEITIG scheiterndes Projekt B nicht
        mit-blockieren - jedes Projekt hat sein eigenes Fehlerbild."""
        orch = self._fake_orchestrator()
        asyncio.run(run_analysis(orch, project_slug="projekt_a", user_request="baue A"))
        report_b = asyncio.run(run_analysis(orch, project_slug="projekt_b", user_request="baue B"))
        self.assertTrue(report_b.ok)
        self.assertEqual(orch._run_single_agent.await_count, 2)

    def test_cooldown_expires_after_configured_duration(self):
        """Nach Ablauf von ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS muss ein weiterhin scheiterndes
        Projekt wieder analysiert werden - der Cooldown soll wiederholte Analysen bündeln,
        nicht ein Projekt auf unbestimmte Zeit von der Selbstoptimierung ausschließen."""
        orch = self._fake_orchestrator()
        asyncio.run(run_analysis(orch, project_slug="langfristig_kaputt", user_request="baue etwas"))
        orch._run_single_agent.assert_awaited_once()

        # Simuliert Zeitablauf, statt in einem Unit-Test tatsächlich Stunden zu warten.
        past = time.time() - root_cause_analyst_module.ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS - 1
        root_cause_analyst_module._save_analysis_state({"langfristig_kaputt": past})

        second = asyncio.run(run_analysis(orch, project_slug="langfristig_kaputt", user_request="baue etwas"))
        self.assertTrue(second.ok)
        self.assertEqual(orch._run_single_agent.await_count, 2)


if __name__ == "__main__":
    unittest.main()
