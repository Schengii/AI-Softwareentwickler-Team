"""
tests/test_agent_learnings.py – Testet die persistente Selbstoptimierung & Wissensbasis der Agenten
"""

import tempfile
import unittest
from pathlib import Path

from memory.agent_knowledge_base import MAX_RULE_LENGTH, AgentKnowledgeBase


class TestAgentKnowledgeBase(unittest.TestCase):
    """Testet das persistente Langzeitgedächtnis für Agenten-Optimierungen."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_learnings.json"
        self.kb = AgentKnowledgeBase(file_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_retrieve_learning(self):
        self.kb.add_learning("database", "Verwende stets db_index=True bei ForeignKey-Relationen.")
        learnings = self.kb.get_learnings("database")
        self.assertEqual(len(learnings), 1)
        self.assertIn("db_index=True", learnings[0])

    def test_overlong_rule_is_truncated_to_prevent_permanent_prompt_bloat(self):
        """
        Jede gespeicherte Regel landet bei JEDEM künftigen Aufruf des Agenten im
        System-Prompt (siehe get_augmented_prompt) - eine einzelne, unbegrenzt lange
        "Regel" (der Trainer-Agent liefert Freitext) würde diesen Tokenverbrauch bei
        jedem künftigen Lauf unbemerkt wiederholen.
        """
        overlong_rule = "Wichtige Regel: " + ("sehr ausführlicher Text " * 30)
        self.assertGreater(len(overlong_rule), MAX_RULE_LENGTH)

        self.kb.add_learning("backend", overlong_rule)
        stored = self.kb.get_learnings("backend")[0]

        self.assertLessEqual(len(stored), MAX_RULE_LENGTH + 1)  # +1 für das "…"-Suffix
        self.assertTrue(stored.endswith("…"))

    def test_prompt_augmentation(self):
        self.kb.add_learning("backend", "Verwende async def für alle I/O-gebundenen Endpunkte.")
        base_prompt = "Du bist ein Backend-Entwickler."
        augmented = self.kb.get_augmented_prompt("backend", base_prompt)
        self.assertIn("Du bist ein Backend-Entwickler.", augmented)
        self.assertIn("GELERNTE BEST PRACTICES", augmented)
        self.assertIn("async def", augmented)

    def test_semantically_near_duplicate_learning_is_not_added_again(self):
        """
        Realer Fund (ki_team_analyse_und_optimierungen.md, Punkt 5): memory/agent_learnings.json
        enthielt beim backend-Agenten drei Fast-Duplikate zum Thema "Import in requirements.txt
        nachtragen", jeweils in leicht anderem Wortlaut - der bisherige exakte String-Vergleich
        erkannte das nicht. Eine Jaccard-Ähnlichkeit der Wortmengen >= 60% gilt als Dublette und
        wird nicht erneut gespeichert.
        """
        self.kb.add_learning("backend", "Jeder neue Import muss sofort in requirements.txt nachgetragen werden.")
        self.kb.add_learning("backend", "Jeder neue Import muss sofort und zwingend in die requirements.txt nachgetragen werden.")

        self.assertEqual(len(self.kb.get_learnings("backend")), 1)

    def test_clearly_distinct_learning_is_still_added(self):
        self.kb.add_learning("backend", "Jeder neue Import muss sofort in requirements.txt nachgetragen werden.")
        self.kb.add_learning("backend", "Verwende niemals `assert` im Produktionscode (B101).")

        self.assertEqual(len(self.kb.get_learnings("backend")), 2)


class TestInfrastructureWorkaroundFilter(unittest.TestCase):
    """
    Realer Fund (Analyse 2026-09-10, auditlog_sentinel-Lauf): memory/agent_learnings.json enthielt
    11 reine Provider-/Kontingent-Workarounds statt Code-Lektionen, u.a. "Bei 429-Fehlern:
    Umschalten auf High-Level-Compliance-Check ohne detaillierte Code-Analyse." (security) und
    "... nutze gpt-3.5-turbo als Fallback." (database, ein in diesem Framework nirgends
    konfiguriertes Fremdmodell). Ein einzelner Agent sieht den rohen HTTP-Statuscode eines
    gescheiterten LLM-Aufrufs nie - core/llm_factory.py/core/token_guard.py behandeln das bereits
    zentral, VOR dem Agenten. add_learning() weist solche Regeln jetzt zurück.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_learnings.json"
        self.kb = AgentKnowledgeBase(file_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rejects_rate_limit_reaction_rule(self):
        self.kb.add_learning("security", "Bei 429-Fehlern: Umschalten auf High-Level-Compliance-Check ohne detaillierte Code-Analyse.")
        self.assertEqual(self.kb.get_learnings("security"), [])

    def test_rejects_model_fallback_rotation_rule(self):
        self.kb.add_learning("code_reviewer", "Signalisiere bei API-429-Fehlern sofort <fallback_request> zur Modell-Rotation.")
        self.assertEqual(self.kb.get_learnings("code_reviewer"), [])

    def test_rejects_foreign_model_recommendation_even_without_error_marker(self):
        self.kb.add_learning("database", "Begrenze jede Anfrage auf max. 7500 Tokens; bei Überschreitung splitte das Schema und nutze gpt-3.5-turbo als Fallback.")
        self.assertEqual(self.kb.get_learnings("database"), [])

    def test_rejects_backoff_and_checkpoint_rules(self):
        self.kb.add_learning("planning_lead", "Bei 429-Fehlern: Stoppe die Ausführung, speichere State-Checkpoint und fordere manuelle Fortsetzung an.")
        self.kb.add_learning("devops", "Bei 503-Fehlern: Reduziere Output auf minimales JSON-Format ohne Reasoning-Chain.")
        self.assertEqual(self.kb.get_learnings("planning_lead"), [])
        self.assertEqual(self.kb.get_learnings("devops"), [])

    def test_genuine_code_lesson_mentioning_http_status_is_kept(self):
        # Eine fachliche Regel über das Verhalten der ZU BAUENDEN Anwendung (nicht über das
        # KI-Team selbst) darf nicht am bloßen Vorkommen einer Statuscode-Zahl scheitern.
        self.kb.add_learning("backend", "Gib bei Überschreiten des Nutzer-Ratenlimits HTTP 429 mit Retry-After-Header zurück.")
        self.assertEqual(len(self.kb.get_learnings("backend")), 1)

    def test_genuine_code_lesson_without_any_marker_is_kept(self):
        self.kb.add_learning("database", "Verwende poolclass=StaticPool bei In-Memory-SQLite in Tests.")
        self.assertEqual(len(self.kb.get_learnings("database")), 1)


class TestEditableLearnings(unittest.TestCase):
    """
    Realer Bedarf: der agent_trainer analysiert Läufe automatisch per LLM-Aufruf - eine
    einzelne falsche oder überholte Regel würde sonst erst nach 5 neueren Regeln automatisch
    verdrängt (siehe add_learning) und bis dahin bei JEDEM Aufruf des Agenten den
    System-Prompt verzerren. Der Mensch muss das gezielt korrigieren können.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_learnings.json"
        self.kb = AgentKnowledgeBase(file_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_all_learnings_returns_everything_grouped_by_agent(self):
        self.kb.add_learning("backend", "Regel A")
        self.kb.add_learning("frontend", "Regel B")
        self.kb.add_learning("backend", "Regel C")

        all_learnings = self.kb.get_all_learnings()

        self.assertEqual(all_learnings["backend"], ["Regel A", "Regel C"])
        self.assertEqual(all_learnings["frontend"], ["Regel B"])

    def test_get_all_learnings_returns_a_copy_not_a_live_reference(self):
        self.kb.add_learning("backend", "Regel A")
        snapshot = self.kb.get_all_learnings()
        snapshot["backend"].append("Manipuliert von außen")

        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A"])

    def test_remove_learning_deletes_exactly_the_requested_rule(self):
        self.kb.add_learning("backend", "Regel A")
        self.kb.add_learning("backend", "Regel B (falsch gelernt)")
        self.kb.add_learning("backend", "Regel C")

        removed = self.kb.remove_learning("backend", 2)  # 1-basiert, wie im /learnings-Befehl

        self.assertEqual(removed, "Regel B (falsch gelernt)")
        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A", "Regel C"])

    def test_remove_learning_persists_across_reload(self):
        self.kb.add_learning("backend", "Regel A")
        self.kb.add_learning("backend", "Regel B")
        self.kb.remove_learning("backend", 1)

        reloaded = AgentKnowledgeBase(file_path=self.file_path)
        self.assertEqual(reloaded.get_learnings("backend"), ["Regel B"])

    def test_remove_last_rule_of_an_agent_cleans_up_the_entry_entirely(self):
        self.kb.add_learning("backend", "Einzige Regel")
        self.kb.remove_learning("backend", 1)

        self.assertEqual(self.kb.get_learnings("backend"), [])
        self.assertNotIn("backend", self.kb.get_all_learnings())

    def test_remove_learning_returns_none_for_unknown_agent(self):
        self.assertIsNone(self.kb.remove_learning("does_not_exist", 1))

    def test_remove_learning_returns_none_for_out_of_range_index(self):
        self.kb.add_learning("backend", "Regel A")
        self.assertIsNone(self.kb.remove_learning("backend", 0))
        self.assertIsNone(self.kb.remove_learning("backend", 2))
        # Nichts wurde verändert trotz der ungültigen Versuche.
        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A"])


if __name__ == "__main__":
    unittest.main()


class TestTopicSaturation:
    """Analyse 2026-09-15: 6 von 10 frontend-Regeln sagten "Code per write_file statt im Chat"."""

    def test_rephrased_rule_on_covered_topic_is_rejected_and_reported(self, tmp_path, monkeypatch):
        from memory.agent_knowledge_base import AgentKnowledgeBase

        reported: list[dict] = []
        monkeypatch.setattr("core.team_memory.record_lesson", lambda **kw: reported.append(kw))
        kb = AgentKnowledgeBase(file_path=tmp_path / "learnings.json")
        kb.add_learning("frontend", "Gib niemals Code im Chat aus. Nutze ausnahmslos write_file oder edit_file.")
        kb.add_learning("frontend", "Beende die Aufgabe nie mit reinem Text; schreibe UI-Artefakte zwingend per write_file physisch.")
        assert len(kb.get_learnings("frontend")) == 1
        assert reported and reported[0]["category"] == "learning_saturated"

    def test_consolidate_keeps_first_rule_per_topic(self, tmp_path):
        import json

        from memory.agent_knowledge_base import AgentKnowledgeBase

        path = tmp_path / "learnings.json"
        path.write_text(json.dumps({"frontend": [
            "Nutze write_file statt Code im Chat.", "Andere Regel zu CSS-Pfaden.", "Code nie als Markdown ausgeben, immer write_file.",
        ]}), encoding="utf-8")
        kb = AgentKnowledgeBase(file_path=path)
        assert kb.consolidate_topic_duplicates() == {"frontend": 1}
        assert kb.get_learnings("frontend") == ["Nutze write_file statt Code im Chat.", "Andere Regel zu CSS-Pfaden."]
