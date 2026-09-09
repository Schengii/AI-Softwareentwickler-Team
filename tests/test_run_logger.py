"""
tests/test_run_logger.py – Strukturiertes Lauf-Protokoll (core/run_logger.py)

Regressionsschutz für den Befund der KI-Team-Masterplan-Analyse: `logs/` war vollständig leer
und es existierte kein Datei-Logging – ein im Hintergrund (`--work-backlog`, issue_watcher,
production_monitor) gescheiterter Lauf konnte hinterher nicht mehr untersucht werden.
"""

import json
from unittest.mock import patch

import pytest

from core import run_logger as rl
from core.message_bus import AgentResult
from core.provider_exhaustion import FAILURE_CLASS_PROVIDER_EXHAUSTED


@pytest.fixture
def logdirs(tmp_path):
    """Leitet beide Log-Verzeichnisse in ein temporäres Verzeichnis um."""
    runs, verif = tmp_path / "runs", tmp_path / "verification"
    with patch.object(rl, "RUN_LOGS_DIR", runs), patch.object(rl, "VERIFICATION_LOGS_DIR", verif):
        yield runs, verif


def _read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestRunLogger:
    def test_schreibt_jsonl_mit_pflichtfeldern(self, logdirs):
        logger = rl.RunLogger(project_slug="notes_api")
        logger.log_event("run_started", task_summary="Demo")
        events = _read_events(logger.run_log_path)
        assert len(events) == 1
        assert events[0]["event"] == "run_started"
        assert events[0]["project_slug"] == "notes_api"
        assert events[0]["seq"] == 1
        assert "ts" in events[0]

    def test_agent_call_haelt_angefordertes_und_effektives_modell_fest(self, logdirs):
        """Der wichtigste Diagnosewert: Ein stiller Fallback-Hop war zuvor nirgends sichtbar."""
        logger = rl.RunLogger(project_slug="demo")
        result = AgentResult(
            task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok",
            model_used="groq:openai/gpt-oss-120b", total_tokens=1234, duration_seconds=2.5,
        )
        logger.log_agent_result(result, requested_model="claude-sonnet-5")
        entry = _read_events(logger.run_log_path)[0]
        assert entry["requested_model"] == "claude-sonnet-5"
        assert entry["effective_model"] == "groq:openai/gpt-oss-120b"
        assert entry["model_downgraded"] is True
        assert entry["total_tokens"] == 1234

    def test_kein_downgrade_wenn_modelle_uebereinstimmen(self, logdirs):
        logger = rl.RunLogger(project_slug="demo")
        result = AgentResult(
            task_id="t1", agent_id="readme", agent_name="Readme", success=True, content="ok",
            model_used="gemini-3.1-flash-lite",
        )
        logger.log_agent_result(result, requested_model="gemini-3.1-flash-lite")
        assert _read_events(logger.run_log_path)[0]["model_downgraded"] is False

    def test_fehlschlag_protokolliert_klasse_und_meldung(self, logdirs):
        logger = rl.RunLogger(project_slug="demo")
        result = AgentResult(
            task_id="t1", agent_id="architect", agent_name="Architekt", success=False, content="",
            error="429 RESOURCE_EXHAUSTED", failure_class=FAILURE_CLASS_PROVIDER_EXHAUSTED,
        )
        logger.log_agent_result(result)
        entry = _read_events(logger.run_log_path)[0]
        assert entry["success"] is False
        assert entry["failure_class"] == FAILURE_CLASS_PROVIDER_EXHAUSTED
        assert "429" in entry["error"]

    def test_verifikations_rohausgabe_landet_in_eigener_datei(self, logdirs):
        logger = rl.RunLogger(project_slug="demo")
        logger.log_verification_output("pytest (erstlauf)", output="E   assert 1 == 2", exit_code=1)
        assert logger.verification_log_path.exists()
        raw = logger.verification_log_path.read_text(encoding="utf-8")
        assert "assert 1 == 2" in raw
        assert "pytest (erstlauf)" in raw
        entry = _read_events(logger.run_log_path)[0]
        assert entry["event"] == "verification_step"
        assert entry["exit_code"] == 1
        assert entry["output_truncated"] is False

    def test_sehr_grosse_ausgabe_wird_gekuerzt(self, logdirs):
        logger = rl.RunLogger(project_slug="demo")
        with patch.object(rl, "MAX_VERIFICATION_CHARS_PER_ENTRY", 100):
            logger.log_verification_output("pip install", output="x" * 5000, exit_code=1)
        entry = _read_events(logger.run_log_path)[0]
        assert entry["output_truncated"] is True
        assert entry["output_chars"] == 5000
        assert "gekürzt" in logger.verification_log_path.read_text(encoding="utf-8")

    def test_slug_wird_dateisystemsicher_gemacht(self, logdirs):
        logger = rl.RunLogger(project_slug="my/project:name*?")
        logger.log_event("run_started")
        assert logger.run_log_path.exists()
        for zeichen in '/:*?"<>|':
            assert zeichen not in logger.run_log_path.name

    def test_leerer_slug_faellt_auf_platzhalter_zurueck(self, logdirs):
        logger = rl.RunLogger(project_slug="")
        logger.log_event("run_started")
        assert "unbenannt" in logger.run_log_path.name

    def test_protokollierung_bricht_lauf_nie_ab(self, logdirs):
        """Grundsatz: Ein I/O-Fehler beim Loggen darf einen sonst erfolgreichen Lauf nie kippen."""
        logger = rl.RunLogger(project_slug="demo")
        with patch("pathlib.Path.open", side_effect=OSError("Datenträger voll")):
            logger.log_event("run_started")            # darf nicht werfen
            logger.log_verification_output("pytest", "x", 0)
            logger.close(verification_ok=False)

    def test_nicht_serialisierbares_feld_verliert_die_zeile_nicht(self, logdirs):
        logger = rl.RunLogger(project_slug="demo")
        logger.log_event("run_started", pfad=object())
        assert len(_read_events(logger.run_log_path)) == 1

    def test_close_schreibt_abschlusszeile(self, logdirs):
        logger = rl.RunLogger(project_slug="demo")
        logger.log_event("run_started")
        logger.close(verification_ok=True, total_tokens=999)
        letzte = _read_events(logger.run_log_path)[-1]
        assert letzte["event"] == "run_closed"
        assert letzte["verification_ok"] is True
        assert letzte["total_tokens"] == 999
        assert "duration_seconds" in letzte


class TestLogRotation:
    def test_ueberzaehlige_dateien_werden_entfernt(self, logdirs):
        runs, _ = logdirs
        runs.mkdir(parents=True, exist_ok=True)
        for i in range(10):
            (runs / f"lauf_{i:02d}.jsonl").write_text("{}\n", encoding="utf-8")
        entfernt = rl.prune_old_logs(max_files=4, max_age_days=365)
        assert entfernt == 6
        assert len(list(runs.glob("*.jsonl"))) == 4

    def test_zu_alte_dateien_werden_entfernt(self, logdirs):
        import os
        import time
        runs, _ = logdirs
        runs.mkdir(parents=True, exist_ok=True)
        alt = runs / "alt.jsonl"
        alt.write_text("{}\n", encoding="utf-8")
        veraltet = time.time() - 60 * 86400
        os.utime(alt, (veraltet, veraltet))
        neu = runs / "neu.jsonl"
        neu.write_text("{}\n", encoding="utf-8")
        rl.prune_old_logs(max_files=100, max_age_days=30)
        assert not alt.exists()
        assert neu.exists()

    def test_fehlendes_verzeichnis_ist_kein_fehler(self, logdirs):
        assert rl.prune_old_logs() == 0
