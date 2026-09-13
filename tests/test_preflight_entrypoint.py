"""
tests/test_preflight_entrypoint.py – Testet check_entrypoint_exists() (Team-Goal 20260913,
Aufgabe 1): eine leichtgewichtige, rein lokale Prüffunktion, die direkt nach Phase 3
(Software-Entwicklung) im Orchestrator läuft, BEVOR die teuren QA-/Security-/Accessibility-/
Review-Phasen Tokens auf einem Projekt ohne physischen Haupteinstiegspunkt verbrennen.
"""

from core.definition_of_done import check_entrypoint_exists


class TestCheckEntrypointExists:
    def test_projekt_ohne_quelldateien_ist_kein_befund(self, tmp_path):
        (tmp_path / "README.md").write_text("# Doku\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""

    def test_leeres_verzeichnis_ist_kein_befund(self, tmp_path):
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""

    def test_python_main_py_wird_erkannt(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""

    def test_python_app_main_py_wird_erkannt(self, tmp_path):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (tmp_path / "app" / "models.py").write_text("class X: pass\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""

    def test_typescript_src_main_ts_wird_erkannt(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text("console.log('hi');\n", encoding="utf-8")
        (tmp_path / "src" / "App.tsx").write_text("export const App = () => null;\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""

    def test_index_html_wird_als_entrypoint_akzeptiert(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "App.tsx").write_text("export const App = () => null;\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""

    def test_fehlender_entrypoint_bei_vorhandenen_quelldateien_wird_gemeldet(self, tmp_path):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "models.py").write_text("class X: pass\n", encoding="utf-8")
        (tmp_path / "app" / "schemas.py").write_text("class Y: pass\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is False
        assert "Kein Haupteinstiegspunkt" in reason

    def test_leerer_entrypoint_zaehlt_nicht_als_vorhanden(self, tmp_path):
        (tmp_path / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is False
        assert "Kein Haupteinstiegspunkt" in reason

    def test_frontend_ohne_index_html_und_ohne_src_entry_wird_gemeldet(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.js").write_text("export const helper = () => 1;\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is False
        assert "Kein Haupteinstiegspunkt" in reason

    def test_node_modules_und_venv_werden_bei_der_quelldatei_suche_ignoriert(self, tmp_path):
        nested = tmp_path / "node_modules" / "some-dep"
        nested.mkdir(parents=True)
        (nested / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
        ok, reason = check_entrypoint_exists(tmp_path)
        assert ok is True
        assert reason == ""
