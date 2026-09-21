"""
tests/test_learning_effectiveness.py – Testet die Wirksamkeitsmessung für Learnings (P2-1)

Regressionsschutz für den Befund aus ROADMAP_TEMP.md P2-1: memory/agent_learnings.json speicherte
Regeln als schlichte `list[str]` ohne jede Metadaten. Als Ersatz für eine echte Wirksamkeitsmessung
diente ausschließlich `_specificity_score()` (eine Text-Heuristik) - ob eine Regel den Fehler, den
sie beheben sollte, tatsächlich verhinderte, war nicht messbar. 7 der 22 Agenten standen am
`MAX_RULES_PER_AGENT`-Limit, wo jede neue Regel die generischste bestehende verdrängte, unabhängig
davon, ob diese nachweislich wirkte.

Diese Tests decken das neue Metadaten-Schema ab: `trigger_signature`-basierte Zählung von
Injektionen/Verletzungen, die abwärtskompatible Migration alter String-Einträge, die
wirksamkeitsbasierte Verdrängung (_evict_least_valuable_entry) und die automatische Meldung einer
nachweislich wirkungslosen Regel.
"""

import json
import tempfile
import unittest
from pathlib import Path

from memory.agent_knowledge_base import (
    INEFFECTIVE_INJECTION_THRESHOLD,
    MIN_INJECTIONS_FOR_EFFECTIVENESS,
    AgentKnowledgeBase,
    _effectiveness_rate,
    _evict_least_valuable_entry,
)


class TestMigrationAlterStringEintraege(unittest.TestCase):
    """Abwärtskompatibler Loader: memory/agent_learnings.json enthielt bisher list[str]."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "learnings.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_alte_string_eintraege_werden_transparent_migriert(self):
        self.file_path.write_text(
            json.dumps({"backend": ["Verwende `StaticPool` bei In-Memory-SQLite."]}),
            encoding="utf-8",
        )
        kb = AgentKnowledgeBase(file_path=self.file_path)

        self.assertEqual(kb.get_learnings("backend"), ["Verwende `StaticPool` bei In-Memory-SQLite."])
        details = kb.get_learning_details("backend")
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["injections"], 0)
        self.assertIsNone(details[0]["effectiveness"])
        self.assertIn("created_at", details[0])

    def test_migrierte_regeln_bleiben_nach_speichern_im_neuen_schema(self):
        self.file_path.write_text(json.dumps({"backend": ["Alte Regel."]}), encoding="utf-8")
        kb = AgentKnowledgeBase(file_path=self.file_path)
        kb.add_learning("backend", "Neue, ganz andere Regel ueber `anker`.")

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        self.assertIsInstance(raw["backend"][0], dict)
        self.assertEqual(raw["backend"][0]["rule"], "Alte Regel.")


class TestTriggerSignatureZaehltVerletzungenStattDubletten(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.kb = AgentKnowledgeBase(file_path=Path(self.temp_dir.name) / "learnings.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_gleiche_signatur_erzeugt_keine_zweite_regel_sondern_eine_verletzung(self):
        self.kb.add_learning(
            "backend", "Pruefe Symbol X in Modul Y.", trigger_signature="import_name_error:app.core.security"
        )
        self.kb.add_learning(
            "backend", "Pruefe Symbol Z in Modul Y.", trigger_signature="import_name_error:app.core.security"
        )

        self.assertEqual(len(self.kb.get_learnings("backend")), 1)
        details = self.kb.get_learning_details("backend")
        self.assertEqual(details[0]["violations_after"], 1)

    def test_andere_signatur_erzeugt_eigene_regel(self):
        self.kb.add_learning("backend", "Regel A.", trigger_signature="sig_a")
        self.kb.add_learning("backend", "Regel B ueber etwas ganz anderes.", trigger_signature="sig_b")

        self.assertEqual(len(self.kb.get_learnings("backend")), 2)


class TestInjektionenUndWirksamkeit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.kb = AgentKnowledgeBase(file_path=Path(self.temp_dir.name) / "learnings.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_jeder_augmented_prompt_aufruf_zaehlt_eine_injektion(self):
        self.kb.add_learning("backend", "Regel mit `anker`.")
        for _ in range(3):
            self.kb.get_augmented_prompt("backend", "Basis-Prompt")

        self.assertEqual(self.kb.get_learning_details("backend")[0]["injections"], 3)

    def test_wirksamkeit_ist_none_unterhalb_der_mindest_injektionszahl(self):
        entry = {"injections": MIN_INJECTIONS_FOR_EFFECTIVENESS - 1, "violations_after": 1}
        self.assertIsNone(_effectiveness_rate(entry))

    def test_wirksamkeit_wird_ab_mindest_injektionszahl_berechnet(self):
        entry = {"injections": MIN_INJECTIONS_FOR_EFFECTIVENESS, "violations_after": 2}
        self.assertAlmostEqual(_effectiveness_rate(entry), 2 / MIN_INJECTIONS_FOR_EFFECTIVENESS)


class TestWirksamkeitsbasierteVerdraengung(unittest.TestCase):
    """_evict_least_valuable_entry nutzt die gemessene Rate, sobald genug Injektionen vorliegen,
    sonst faellt sie auf die bestehende Spezifitaets-Heuristik zurueck (Akzeptanzkriterium P2-1)."""

    def test_gemessene_wirkungslose_regel_fliegt_vor_unvermessener_generischer_regel(self):
        wirkungslos = {
            "rule": "Sehr spezifische, aber nachweislich wirkungslose Regel mit `anker_a` und ModuleNotFoundError.",
            "injections": 10,
            "violations_after": 9,
        }
        unvermessen_generisch = {"rule": "Achte auf guten Stil.", "injections": 1, "violations_after": 0}
        entries = [wirkungslos, unvermessen_generisch]

        _evict_least_valuable_entry(entries)

        self.assertNotIn(wirkungslos, entries)
        self.assertIn(unvermessen_generisch, entries)

    def test_ohne_gemessene_regeln_faellt_es_auf_spezifitaet_zurueck(self):
        konkret = {"rule": "Nutze `StaticPool` in conftest.py.", "injections": 1, "violations_after": 0}
        generisch = {"rule": "Achte auf guten Stil.", "injections": 1, "violations_after": 0}
        entries = [konkret, generisch]

        _evict_least_valuable_entry(entries)

        self.assertNotIn(generisch, entries)
        self.assertIn(konkret, entries)

    def test_einzelner_eintrag_wird_nie_entfernt(self):
        entries = [{"rule": "Einzige Regel.", "injections": 100, "violations_after": 100}]
        _evict_least_valuable_entry(entries)
        self.assertEqual(len(entries), 1)


class TestAutomatischeMeldungWirkungsloserRegeln(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.kb = AgentKnowledgeBase(file_path=Path(self.temp_dir.name) / "learnings.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_regel_ueber_schwellenwert_mit_verletzung_wird_einmalig_gemeldet(self):
        import unittest.mock as mock

        self.kb.add_learning("backend", "Regel mit `anker`.", trigger_signature="sig_x")
        # Genug Injektionen sammeln, um den Schwellenwert zu ueberschreiten.
        for _ in range(INEFFECTIVE_INJECTION_THRESHOLD):
            self.kb.get_augmented_prompt("backend", "Basis")
        # Die Signatur tritt trotz der Regel erneut auf (violations_after > 0).
        self.kb.add_learning("backend", "Andere Formulierung, gleiche Signatur.", trigger_signature="sig_x")

        with mock.patch("core.team_memory.record_lesson") as mocked:
            self.kb.get_augmented_prompt("backend", "Basis")  # ueberschreitet den Schwellenwert
            self.kb.get_augmented_prompt("backend", "Basis")  # darf NICHT erneut melden

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(mocked.call_args.kwargs["category"], "learning_ineffective")


if __name__ == "__main__":
    unittest.main()
