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
