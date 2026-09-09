"""
tests/test_learning_eviction.py – Nutzenbasierte statt FIFO-Verdrängung im Learning-Speicher

Regressionsschutz für einen Fund der KI-Team-Masterplan-Analyse: 7 der 19 Agenten mit Learnings
standen exakt am Limit MAX_RULES_PER_AGENT (architect, dev_lead, governance_lead, code_reviewer,
qa_lead, frontend, security – je 10/10). Die Verdrängung arbeitete rein nach FIFO, sodass eine
bewährte, sehr konkrete Regel von einer beliebig generischen verdrängt werden konnte – das
Gedächtnis verlor mit der Zeit gerade seine nützlichsten Einträge.
"""

import pytest

from memory.agent_knowledge_base import (
    MAX_RULES_PER_AGENT,
    AgentKnowledgeBase,
    _evict_least_valuable,
    _specificity_score,
)

KONKRET = "Nutze `StaticPool` in conftest.py, sonst sieht jede Verbindung eine eigene DB."
GENERISCH = "Achte auf saubere Umsetzung und gute Qualitaet."


class TestSpezifitaet:
    def test_konkrete_regel_schlaegt_generische(self):
        assert _specificity_score(KONKRET) > _specificity_score(GENERISCH)

    @pytest.mark.parametrize("regel", [
        "Verwende `create_async_engine` statt create_engine.",
        "Trage jeden Import in requirements.txt nach.",
        "Ein ModuleNotFoundError bedeutet eine fehlende Abhaengigkeit.",
        "Die Testabdeckung muss mindestens 80 Prozent betragen.",
        "Rufe Base.metadata.create_all() vor dem Testlauf auf.",
    ])
    def test_regeln_mit_konkreten_ankern_werden_erkannt(self, regel):
        assert _specificity_score(regel) >= 1

    @pytest.mark.parametrize("regel", [
        "Arbeite sorgfaeltig.",
        "Achte auf guten Stil.",
        "Denke an den Nutzer.",
        "",
    ])
    def test_reine_ermahnungen_bekommen_null(self, regel):
        assert _specificity_score(regel) == 0

    def test_none_stuerzt_nicht_ab(self):
        assert _specificity_score(None) == 0


class TestVerdraengung:
    def test_generischste_regel_fliegt_zuerst(self):
        regeln = [KONKRET, GENERISCH, "Nutze `pytest.ini` mit pythonpath."]
        _evict_least_valuable(regeln)
        assert GENERISCH not in regeln
        assert KONKRET in regeln

    def test_bei_gleichstand_faellt_die_aelteste(self):
        """Stabiles, nachvollziehbares Verhalten als Tiebreak."""
        regeln = ["Erste generische Regel.", "Zweite generische Regel."]
        _evict_least_valuable(regeln)
        assert regeln == ["Zweite generische Regel."]

    def test_einzelne_regel_wird_nie_entfernt(self):
        regeln = [GENERISCH]
        _evict_least_valuable(regeln)
        assert regeln == [GENERISCH]

    def test_leere_liste_ist_unproblematisch(self):
        regeln = []
        _evict_least_valuable(regeln)
        assert regeln == []


class TestIntegrationMitDemSpeicher:
    def test_konkrete_regel_ueberlebt_eine_flut_generischer(self, tmp_path):
        """Der eigentliche Kernbefund: Zuvor haette FIFO die konkrete Regel verdraengt."""
        kb = AgentKnowledgeBase(file_path=tmp_path / "learnings.json")
        kb.add_learning("backend", KONKRET)
        for i in range(MAX_RULES_PER_AGENT * 2):
            # Bewusst unterschiedlich formuliert, damit die Jaccard-Dedup nicht greift.
            kb.add_learning("backend", f"Bitte beachte den Hinweis Nummer eins zum Thema {chr(97 + i % 26)}.")
        assert KONKRET in kb.get_learnings("backend")

    def test_budget_wird_weiterhin_eingehalten(self, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "learnings.json")
        for i in range(MAX_RULES_PER_AGENT * 3):
            kb.add_learning("frontend", f"Regel ueber das Thema {chr(97 + i % 26)} und dessen Umgang.")
        assert len(kb.get_learnings("frontend")) <= MAX_RULES_PER_AGENT

    def test_dedup_bleibt_wirksam(self, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "learnings.json")
        kb.add_learning("backend", "Jeder neue Import muss sofort in requirements.txt nachgetragen werden.")
        kb.add_learning("backend", "Jeder neue Import muss zwingend in die requirements.txt nachgetragen werden.")
        assert len(kb.get_learnings("backend")) == 1
