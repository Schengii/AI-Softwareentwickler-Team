"""
tests/test_team_health_rollup.py – Testet core/team_health.py (projektübergreifender
Health-Rollup über workspace/)

Realer Fund: jedes Projekt in workspace/<projekt>/ trägt seine eigene Lauf-Historie
(.ai_team_status.json), aber es gab bisher keinen Befehl, der über ALLE Projekte hinweg einen
Überblick gibt - insbesondere um zu erkennen, wenn mehrere Projekte gleichzeitig an derselben
Fehlerursache scheitern.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from core.project_status import record_run
from core.team_health import build_team_health_rollup, categorize_failure


class TestCategorizeFailure(unittest.TestCase):
    def test_frontend_marker_recognized(self):
        self.assertEqual(
            categorize_failure("- 🌐 ❌ Frontend/UI-Check fehlgeschlagen: 404 auf /app.js."),
            "Frontend/UI-Check",
        )

    def test_lint_marker_recognized(self):
        self.assertEqual(categorize_failure("- 🎨 ruff: 3 Lint-Fund(e): ..."), "Lint")

    def test_empty_detail_falls_back(self):
        self.assertEqual(categorize_failure(""), "Sonstiger Fehler")

    def test_unknown_text_falls_back(self):
        self.assertEqual(categorize_failure("irgendein unbekannter Text"), "Sonstiger Fehler")

    def test_blocking_veto_categories_are_recognized(self):
        """Roadmap P0-5 (2026-09-20): die drei Fehlerarten, die die Verifikation am häufigsten
        erzeugt, hatten gar keinen Marker - 8 von 12 roten Projekten landeten deshalb unter
        'Sonstiger Fehler', obwohl aegisflow und ecotrack_ai nachweislich dasselbe Muster
        teilten. Genau dieses Muster sichtbar zu machen ist der Zweck von shared_patterns."""
        cases = {
            "- 🛡️ ❌ **Verifikations-Veto durch offene Sicherheits-Übergabe:** 1 vom security-Agenten …":
                "Sicherheits-Übergabe offen",
            "- ❌ **Verifikations-Veto durch Completeness-Check:** 2 Vollständigkeits-Fund(e) …":
                "Vollständigkeit (Stub/Platzhalter)",
            "- ❌ **Verifikations-Veto durch Test-Schrumpfung:** 1 Testfunktion verschwunden":
                "Test-Schrumpfung (Tests statt Fehler entfernt)",
            "- 🔍 🛑 Pre-Flight-Check, Versuch 2: dieselben 2 Fund(e) wie nach dem vorherigen Fixversuch":
                "Pre-Flight-Check (Schleife ohne Fortschritt)",
            "- 🚫 Lauf-Budget (`MAX_RUN_TOKENS=1,000,000`) erreicht – Vollständigkeits-Check abgebrochen.":
                "Token-Budget erreicht",
        }
        for detail, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(categorize_failure(detail), expected)

    def test_informational_lint_never_outranks_a_blocking_category(self):
        """`lint` ist ein informativer Check (INFORMATIONAL_CHECK_KEYS) und beeinflusst
        `verification_ok` nie. Stand der Lint-Marker vor `Testfehler`, verdrängte eine harmlose
        ruff-Warnung den echten, blockierenden Grund als Kategorie - real in 5 von 6 der letzten
        Läufe, die alle eine ruff-Zeile im Protokoll trugen."""
        detail = (
            "- 🎨 ⚠️ ruff: 2 Lint-Fund(e): app/worker/loop.py:53 [BLE001]\n"
            "- ❌ **Verifikations-Veto durch Completeness-Check:** 1 Fund"
        )
        self.assertEqual(categorize_failure(detail), "Vollständigkeit (Stub/Platzhalter)")

        detail_tests = "- 🎨 ⚠️ ruff: 1 Lint-Fund(e)\n- 🛠️ Versuch 1: 3 echte Testfehler"
        self.assertEqual(categorize_failure(detail_tests), "Testsuite")

    def test_pure_lint_finding_is_still_categorized_as_lint(self):
        """Gegenprobe: ohne blockierenden Grund bleibt Lint die richtige Kategorie."""
        self.assertEqual(categorize_failure("- 🎨 ⚠️ ruff: 1 Lint-Fund(e): app/main.py:16 [F841]"), "Lint")


class TestBuildTeamHealthRollup(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    def _project_dir(self, name: str) -> str:
        d = Path(self.workspace) / name
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def test_empty_workspace_returns_no_projects(self):
        rollup = build_team_health_rollup(self.workspace)
        self.assertEqual(rollup.projects, [])
        self.assertEqual(rollup.shared_patterns, {})

    def test_directory_without_status_file_is_ignored(self):
        Path(self.workspace, "not_a_project").mkdir()
        rollup = build_team_health_rollup(self.workspace)
        self.assertEqual(rollup.projects, [])

    def test_healthy_project_has_ok_status_and_zero_streak(self):
        record_run(self._project_dir("healthy_app"), "Feature X", verification_ok=True,
                   budget_aborted=False, files_written_count=3)
        rollup = build_team_health_rollup(self.workspace)
        self.assertEqual(len(rollup.projects), 1)
        p = rollup.projects[0]
        self.assertEqual(p.status, "ok")
        self.assertEqual(p.red_streak, 0)

    def test_red_streak_counts_consecutive_failures_at_history_head(self):
        proj = self._project_dir("flaky_app")
        record_run(proj, "Lauf 1", verification_ok=True, budget_aborted=False, files_written_count=1)
        record_run(proj, "Lauf 2", verification_ok=False, budget_aborted=False, files_written_count=1,
                   verification_summary="- 🎨 ruff: 2 Lint-Fund(e)")
        record_run(proj, "Lauf 3", verification_ok=False, budget_aborted=False, files_written_count=1,
                   verification_summary="- 🎨 ruff: 1 Lint-Fund")
        rollup = build_team_health_rollup(self.workspace)
        p = rollup.projects[0]
        self.assertEqual(p.status, "failed")
        self.assertEqual(p.red_streak, 2)
        self.assertEqual(p.failure_category, "Lint")

    def test_category_comes_from_the_full_protocol_not_the_truncated_excerpt(self):
        """Roadmap P0-5 (2026-09-20): `.ai_team_status.json` kappt `failure_detail` auf
        MAX_FAILURE_DETAIL_CHARS (500). Das Verifikationsprotokoll beginnt mit den frühen,
        informativen Schritten und trägt die blockierende Veto-Zeile am ENDE - sie fiel damit
        aus dem gespeicherten Ausschnitt heraus. Real beobachtet bei devpulse, eventstream_zero,
        nexus_resilience_gateway und nexusforge: alle vier trugen exakt 500 Zeichen Detail und
        landeten unter 'Sonstiger Fehler', obwohl der echte Grund im vollständigen Protokoll
        (.ai_team_runs/<ts>_verification.md) steht."""
        proj = self._project_dir("truncated_app")
        padding = "\n".join(
            f"- 📦 Versuch {i}: fehlendes Paket deterministisch in requirements.txt ergänzt."
            for i in range(1, 15)
        )
        summary = f"{padding}\n- ❌ **Verifikations-Veto durch Completeness-Check:** 1 Fund"
        self.assertGreater(len(summary), 500)
        record_run(proj, "Lauf", verification_ok=False, budget_aborted=False,
                   files_written_count=1, verification_summary=summary)

        p = build_team_health_rollup(self.workspace).projects[0]
        self.assertEqual(p.failure_category, "Vollständigkeit (Stub/Platzhalter)")
        # Angezeigt wird weiterhin der gekürzte Auszug - die volle Fassung gehört nicht in
        # eine Übersicht.
        self.assertLessEqual(len(p.failure_detail), 500)

    def test_cancelled_run_breaks_the_red_streak(self):
        proj = self._project_dir("cancelled_app")
        record_run(proj, "Lauf 1", verification_ok=False, budget_aborted=False, files_written_count=1)
        record_run(proj, "Lauf 2", verification_ok=False, cancelled=True, budget_aborted=False, files_written_count=1)
        rollup = build_team_health_rollup(self.workspace)
        p = rollup.projects[0]
        self.assertEqual(p.status, "cancelled")
        self.assertEqual(p.red_streak, 0)

    def test_shared_pattern_detected_across_multiple_projects(self):
        for name in ("proj_a", "proj_b", "proj_c"):
            record_run(self._project_dir(name), "Lauf", verification_ok=False, budget_aborted=False,
                       files_written_count=1,
                       verification_summary="- 🌐 ❌ Frontend/UI-Check fehlgeschlagen: 404 auf /main.js.")
        record_run(self._project_dir("proj_d"), "Lauf", verification_ok=False, budget_aborted=False,
                   files_written_count=1, verification_summary="- 🎨 ruff: 1 Lint-Fund")

        rollup = build_team_health_rollup(self.workspace)
        self.assertIn("Frontend/UI-Check", rollup.shared_patterns)
        self.assertEqual(set(rollup.shared_patterns["Frontend/UI-Check"]), {"proj_a", "proj_b", "proj_c"})
        # Nur EIN Projekt mit Lint-Fehler -> kein "Muster", da < 2 betroffene Projekte.
        self.assertNotIn("Lint", rollup.shared_patterns)

    def test_projects_sorted_by_longest_red_streak_first(self):
        short_red = self._project_dir("short_red")
        record_run(short_red, "Lauf", verification_ok=False, budget_aborted=False, files_written_count=1)

        long_red = self._project_dir("long_red")
        record_run(long_red, "Lauf 1", verification_ok=False, budget_aborted=False, files_written_count=1)
        record_run(long_red, "Lauf 2", verification_ok=False, budget_aborted=False, files_written_count=1)
        record_run(long_red, "Lauf 3", verification_ok=False, budget_aborted=False, files_written_count=1)

        rollup = build_team_health_rollup(self.workspace)
        names_in_order = [p.name for p in rollup.projects]
        self.assertEqual(names_in_order[0], "long_red")
        self.assertEqual(names_in_order[1], "short_red")


if __name__ == "__main__":
    unittest.main()
