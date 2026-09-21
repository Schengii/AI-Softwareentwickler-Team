"""
tests/test_definition_of_done.py – Maschinenlesbare Fertigstellungs-Kriterien

Regressionsschutz für einen Fund der KI-Team-Masterplan-Analyse: PROJECT_STATE.md meldete für
workspace/event_ticket_api "⚠️ In Entwicklung / Verifikation ausstehend" – bei
`files_written_count: 0`, also nachdem kein einziger Agent etwas produziert hatte. Ein
Prosa-Status kann "fast fertig", "gar nicht angefangen" und "an der Infrastruktur gescheitert"
nicht unterscheiden.
"""

import json

import pytest

from core.definition_of_done import (
    DOD_FILENAME,
    build_definition_of_done,
    read_definition_of_done,
    write_definition_of_done,
)


def _blocking(dod):
    return [c.key for c in dod.blocking_criteria]


def _dod(tmp_path, **kwargs):
    basis = {"files_written": 3, "tests_ran": True, "tests_passed": True}
    basis.update(kwargs)
    return build_definition_of_done(project_slug="demo", project_dir=tmp_path, **basis)


class TestKriterien:
    def test_vollstaendiger_lauf_gilt_als_fertig(self, tmp_path):
        assert _dod(tmp_path).is_done is True

    def test_lauf_ohne_geschriebene_dateien_ist_nie_fertig(self, tmp_path):
        """Der eigentliche Kernbefund: 0 Dateien, aber Status 'In Entwicklung'."""
        dod = _dod(tmp_path, files_written=0, tests_ran=False, tests_passed=False)
        assert dod.is_done is False
        assert "files_written" in [c.key for c in dod.blocking_criteria]

    def test_fehlende_tests_blockieren(self, tmp_path):
        dod = _dod(tmp_path, tests_ran=False, tests_passed=False)
        blockierend = [c.key for c in dod.blocking_criteria]
        assert "tests_exist" in blockierend
        assert "tests_pass" in blockierend

    def test_frontend_unter_public_index_html_gilt_als_geliefert(self, tmp_path):
        """
        Realer Fund (dev_snippet_vault, 2026-09-15): der frontend-Agent lieferte ein
        vollstaendiges Frontend unter `public/index.html` (uebliche Konvention fuer ein von
        einem Backend statisch ausgeliefertes Static-Asset) - `missing_frontend_ui` meldete
        trotzdem faelschlich, kein Frontend sei geliefert worden, weil nur root-level
        `index.html` als Kandidat bekannt war.
        """
        (tmp_path / "public").mkdir()
        (tmp_path / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
        dod = _dod(tmp_path, frontend_planned=True)
        kriterium = next(c for c in dod.criteria if c.key == "missing_frontend_ui")
        assert kriterium.passed is True
        assert "missing_frontend_ui" not in [c.key for c in dod.blocking_criteria]

    def test_rote_tests_blockieren(self, tmp_path):
        dod = _dod(tmp_path, tests_ran=True, tests_passed=False)
        assert [c.key for c in dod.blocking_criteria] == ["tests_pass"]

    def test_tests_koennen_nicht_gruen_sein_ohne_zu_laufen(self, tmp_path):
        """Absicherung gegen widerspruechliche Eingaben."""
        dod = _dod(tmp_path, tests_ran=False, tests_passed=True)
        assert dod.is_done is False


class TestNichtAnwendbareKriterien:
    def test_none_bedeutet_nicht_geprueft_und_blockiert_nicht(self, tmp_path):
        """Unterschied zwischen 'nicht geprüft' und 'geprüft und durchgefallen'."""
        dod = _dod(tmp_path, app_starts=None, deps_installable=None, secrets_clean=None)
        assert dod.is_done is True
        app = next(c for c in dod.criteria if c.key == "app_starts")
        assert app.applicable is False
        assert app.blocking is False

    def test_false_bedeutet_geprueft_und_durchgefallen(self, tmp_path):
        dod = _dod(tmp_path, app_starts=False)
        assert dod.is_done is False
        assert "app_starts" in [c.key for c in dod.blocking_criteria]

    def test_lint_ist_nicht_verpflichtend(self, tmp_path):
        """Ein Stilverstoß macht ein Projekt nicht unfertig."""
        dod = _dod(tmp_path, lint_clean=False)
        assert dod.is_done is True

    def test_readme_ist_nicht_verpflichtend(self, tmp_path):
        dod = _dod(tmp_path)
        readme = next(c for c in dod.criteria if c.key == "readme")
        assert readme.passed is False
        assert readme.blocking is False

    def test_readme_wird_erkannt(self, tmp_path):
        (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
        dod = _dod(tmp_path)
        assert next(c for c in dod.criteria if c.key == "readme").passed is True


class TestCoverage:
    def test_ohne_mindestwert_kein_coverage_kriterium(self, tmp_path):
        dod = _dod(tmp_path, coverage_percent=12.0, min_coverage=0.0)
        assert "coverage" not in [c.key for c in dod.criteria]

    def test_unterschrittene_abdeckung_blockiert_nicht(self, tmp_path):
        dod = _dod(tmp_path, coverage_percent=40.0, min_coverage=80.0)
        cov = next(c for c in dod.criteria if c.key == "coverage")
        assert cov.passed is False
        assert dod.is_done is True

    def test_erreichte_abdeckung_wird_erkannt(self, tmp_path):
        dod = _dod(tmp_path, coverage_percent=95.0, min_coverage=80.0)
        assert next(c for c in dod.criteria if c.key == "coverage").passed is True


class TestAbnahmeGegenAnforderung:
    """P4-2 (ROADMAP_TEMP.md): requirements_met, gespeist von core/acceptance_check.py."""

    def test_ohne_abnahmepruefung_kein_kriterium(self, tmp_path):
        dod = _dod(tmp_path)
        assert "requirements_met" not in [c.key for c in dod.criteria]

    def test_fehlende_anforderungen_blockieren_und_werden_benannt(self, tmp_path):
        dod = _dod(tmp_path, requirements_met=False, missing_requirements=["Write-Behind-Strategie", "Key-Tagging"])
        assert dod.is_done is False
        assert "requirements_met" in _blocking(dod)
        kriterium = next(c for c in dod.criteria if c.key == "requirements_met")
        assert "Write-Behind-Strategie" in kriterium.detail
        assert "Key-Tagging" in kriterium.detail

    def test_erfuellte_anforderungen_blockieren_nicht(self, tmp_path):
        dod = _dod(tmp_path, requirements_met=True, missing_requirements=[])
        assert dod.is_done is True
        assert "requirements_met" not in _blocking(dod)


class TestPersistenz:
    def test_schreiben_und_lesen(self, tmp_path):
        dod = _dod(tmp_path)
        pfad = write_definition_of_done(tmp_path, dod)
        assert pfad is not None
        assert pfad.name == DOD_FILENAME
        gelesen = read_definition_of_done(tmp_path)
        assert gelesen["is_done"] is True
        assert gelesen["project_slug"] == "demo"
        assert gelesen["blocking"] == []

    def test_blockierende_kriterien_landen_in_der_datei(self, tmp_path):
        dod = _dod(tmp_path, files_written=0, tests_ran=False, tests_passed=False)
        write_definition_of_done(tmp_path, dod)
        daten = json.loads((tmp_path / DOD_FILENAME).read_text(encoding="utf-8"))
        assert daten["is_done"] is False
        assert "files_written" in daten["blocking"]

    def test_fehlende_datei_ergibt_none(self, tmp_path):
        assert read_definition_of_done(tmp_path) is None

    def test_beschaedigte_datei_ergibt_none_statt_absturz(self, tmp_path):
        (tmp_path / DOD_FILENAME).write_text("{kaputt", encoding="utf-8")
        assert read_definition_of_done(tmp_path) is None

    def test_schreibfehler_kippt_den_lauf_nicht(self, tmp_path):
        from unittest.mock import patch
        dod = _dod(tmp_path)
        with patch("pathlib.Path.write_text", side_effect=OSError("voll")):
            assert write_definition_of_done(tmp_path, dod) is None


class TestZusammenfassung:
    def test_fertiger_lauf(self, tmp_path):
        assert "**Ergebnis: FERTIG**" in _dod(tmp_path).format_summary()

    def test_unfertiger_lauf_nennt_die_offenen_punkte(self, tmp_path):
        text = _dod(tmp_path, files_written=0, tests_ran=False, tests_passed=False).format_summary()
        assert "**Ergebnis: NICHT FERTIG**" in text
        assert "Es wurde tatsächlich Code erzeugt" in text

    @pytest.mark.parametrize("symbol,kwargs", [
        ("➖", {"app_starts": None}),
        ("❌", {"app_starts": False}),
    ])
    def test_symbole_unterscheiden_nicht_geprueft_von_durchgefallen(self, tmp_path, symbol, kwargs):
        text = _dod(tmp_path, **kwargs).format_summary()
        assert f"- {symbol} Die Anwendung startet" in text


class TestFrontendErwartungAusAuftrag:
    """
    Regressionsschutz für den syncwave-Fund (2026-09-16): `frontend_planned` wurde daraus
    abgeleitet, WELCHE AGENTEN LIEFEN, steuerte aber `ui_ok.required` und
    `missing_frontend_ui.applicable` – der Wächter für ein fehlendes oder kaputtes Frontend
    schaltete sich also genau dann ab, wenn der Planer keinen frontend-Agenten einplante.
    syncwave stand dadurch mit `is_done: true, blocking: []` auf der Platte, obwohl der
    Browser-UI-Check hart gescheitert war.
    """

    def test_gescheiterter_ui_check_blockiert_auch_ohne_frontend_agent(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        dod = _dod(
            tmp_path,
            user_request="FastAPI-Log-Monitoring-Plattform mit WebSocket-Dashboard",
            frontend_planned=False,
            ui_ok=False,
        )
        assert "ui_ok" in _blocking(dod)

    def test_fehlende_ui_dateien_blockieren_bei_beauftragter_oberflaeche(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        dod = _dod(
            tmp_path,
            user_request="Baue ein Dashboard mit Diagrammen im Browser",
            frontend_planned=False,
        )
        assert "missing_frontend_ui" in _blocking(dod)

    def test_reines_backend_projekt_bleibt_unberuehrt(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        dod = _dod(
            tmp_path,
            user_request="Baue eine Notizen-REST-API mit FastAPI und SQLite, CRUD-Endpunkte",
            frontend_planned=False,
            ui_ok=None,
        )
        assert "ui_ok" not in _blocking(dod)
        assert "missing_frontend_ui" not in _blocking(dod)


class TestFehlendeMessungBlockiert:
    """
    Regressionsschutz: `applicable=<wert> is not None` behandelte "nicht gemessen" wie "nicht
    relevant". `VerificationOutcome.status()` liefert `None` aber sowohl für bewusst
    übersprungene als auch für nie aufgezeichnete Prüfungen – eine abgebrochene Start- oder
    Installationsprüfung wurde dadurch stillschweigend zu "fertig".
    """

    def test_fehlender_startmesswert_blockiert_wenn_die_pipeline_lief(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        dod = _dod(tmp_path, verification_ran=True, app_starts=None)
        assert "app_starts" in _blocking(dod)

    def test_ohne_einstiegspunkt_bleibt_der_startcheck_nicht_anwendbar(self, tmp_path):
        dod = _dod(tmp_path, verification_ran=True, app_starts=None)
        assert "app_starts" not in _blocking(dod)

    def test_fehlende_installationsmessung_blockiert_nur_mit_manifest(self, tmp_path):
        ohne = _dod(tmp_path, verification_ran=True, deps_installable=None)
        assert "deps_installable" not in _blocking(ohne)
        (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        mit = _dod(tmp_path, verification_ran=True, deps_installable=None)
        assert "deps_installable" in _blocking(mit)

    def test_fehlendes_gesamturteil_blockiert(self, tmp_path):
        dod = _dod(tmp_path, verification_ran=True, verification_ok=None)
        assert "verification_ok" in _blocking(dod)

    def test_uebersprungene_verifikation_blockiert_nicht(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        dod = _dod(tmp_path, verification_ran=True, verification_skipped=True,
                   app_starts=None, verification_ok=None)
        assert _blocking(dod) == []

    def test_ohne_flag_bleibt_das_alte_verhalten(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        dod = _dod(tmp_path, app_starts=None, deps_installable=None, verification_ok=None)
        assert _blocking(dod) == []


class TestDarkModeKriterium:
    """Regressionsschutz für den EventForge-Fund (KI-Team-Analyse 20260916_154524): der
    Auftrag nannte "Dark-Mode-Dashboard" explizit, das ausgelieferte Dashboard hatte keine
    einzige Dark-Mode-Referenz - kein bisheriges Kriterium prüfte das."""

    def test_explizit_beauftragtes_dark_mode_ohne_umsetzung_blockiert(self, tmp_path):
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "index.html").write_text(
            "<html><body>Hallo</body></html>", encoding="utf-8",
        )
        dod = _dod(
            tmp_path, user_request="Baue ein Dark-Mode-Dashboard für Webhooks",
            frontend_planned=True,
        )
        assert "dark_mode_delivered" in _blocking(dod)

    def test_umgesetztes_dark_mode_blockiert_nicht(self, tmp_path):
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "style.css").write_text(
            "@media (prefers-color-scheme: dark) { body { background: #111; } }",
            encoding="utf-8",
        )
        (tmp_path / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
        dod = _dod(
            tmp_path, user_request="Baue ein Dark-Mode-Dashboard für Webhooks",
            frontend_planned=True,
        )
        assert "dark_mode_delivered" not in _blocking(dod)

    def test_ohne_erwaehnung_im_auftrag_ist_das_kriterium_nicht_anwendbar(self, tmp_path):
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
        dod = _dod(tmp_path, user_request="Baue ein Webhook-Dashboard", frontend_planned=True)
        kriterium = next(c for c in dod.criteria if c.key == "dark_mode_delivered")
        assert kriterium.applicable is False
        assert "dark_mode_delivered" not in _blocking(dod)

    def test_reines_backend_projekt_bleibt_unberuehrt_auch_bei_dark_mode_im_text(self, tmp_path):
        (tmp_path / "main.py").write_text("app = 1\n", encoding="utf-8")
        dod = _dod(tmp_path, user_request="Ein Dark-Mode-Client soll sich hierher verbinden")
        kriterium = next(c for c in dod.criteria if c.key == "dark_mode_delivered")
        assert kriterium.applicable is False
