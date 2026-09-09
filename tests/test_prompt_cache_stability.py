"""
tests/test_prompt_cache_stability.py – Cache-stabile Reihenfolge der System-Prompt-Bestandteile

Regressionsschutz für einen Fund der KI-Team-Masterplan-Analyse: Der System-Prompt wurde als
"Basis → Learnings → Werkzeug-Anweisungen" zusammengesetzt. Der Learnings-Block ändert sich,
sobald ein Agent etwas Neues lernt – er stand damit MITTEN im Prompt. Da Prompt-Caching
ausschließlich über ein gemeinsames PRÄFIX funktioniert, warf jede neue Lernregel auch den
völlig unveränderten, großen Werkzeugkatalog aus dem Cache. Passend dazu die reale Messung:
21,08 Mio. Prompt-Tokens gegen 0,84 Mio. Completion-Tokens (25:1) bei nur 12% Cache-Treffern.

Kernaussage der Tests: Das gemeinsame Präfix zweier Prompts, die sich NUR in den Learnings
unterscheiden, muss den kompletten Werkzeugkatalog enthalten.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.message_bus import AgentTask
from memory.agent_knowledge_base import AgentKnowledgeBase


@pytest.fixture
def agent():
    from agents.backend_agent import BackendAgent
    return BackendAgent()


def _gemeinsames_praefix(a: str, b: str) -> str:
    grenze = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        grenze += 1
    return a[:grenze]


def _baue_prompt(agent, kb, tools: bool) -> str:
    """Baut den System-Prompt exakt so zusammen wie BaseAgent.execute()."""
    if tools:
        stabil = agent._augment_with_tool_instructions(agent.system_prompt, read_only=False)
        return kb.get_augmented_prompt(agent.agent_id, stabil)
    return kb.get_augmented_prompt(agent.agent_id, agent.system_prompt)


class TestReihenfolge:
    def test_werkzeugkatalog_steht_vor_den_learnings(self, agent, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        kb.add_learning(agent.agent_id, "Nutze `StaticPool` in conftest.py.")
        prompt = _baue_prompt(agent, kb, tools=True)

        pos_learnings = prompt.find("GELERNTE BEST PRACTICES")
        pos_werkzeug = prompt.find("write_file")
        assert pos_werkzeug != -1, "Werkzeugkatalog nicht im Prompt gefunden"
        assert pos_learnings != -1
        assert pos_werkzeug < pos_learnings, "Der volatile Learnings-Block steht vor dem statischen Werkzeugkatalog"

    def test_learnings_stehen_ganz_am_ende(self, agent, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        kb.add_learning(agent.agent_id, "Konkrete Regel mit `marker`.")
        prompt = _baue_prompt(agent, kb, tools=True)
        assert "Konkrete Regel mit `marker`." in prompt.split("GELERNTE BEST PRACTICES")[-1]


class TestCachePraefix:
    def test_neue_lernregel_erhaelt_den_werkzeugkatalog_im_praefix(self, agent, tmp_path):
        """Der eigentliche Kernbefund: Zuvor endete das gemeinsame Praefix VOR dem Katalog."""
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        kb.add_learning(agent.agent_id, "Erste Regel mit `anker_eins`.")
        vorher = _baue_prompt(agent, kb, tools=True)

        kb.add_learning(agent.agent_id, "Zweite, voellig andersartige Regel ueber `anker_zwei`.")
        nachher = _baue_prompt(agent, kb, tools=True)

        assert vorher != nachher, "Testaufbau kaputt: Die Prompts muessen sich unterscheiden"
        praefix = _gemeinsames_praefix(vorher, nachher)
        assert "write_file" in praefix, "Der Werkzeugkatalog liegt nicht mehr im cachebaren Praefix"
        assert agent.system_prompt[:200] in praefix

    def test_praefix_umfasst_den_grossteil_des_prompts(self, agent, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        kb.add_learning(agent.agent_id, "Erste Regel mit `anker_eins`.")
        vorher = _baue_prompt(agent, kb, tools=True)
        kb.add_learning(agent.agent_id, "Zweite Regel ueber ein ganz anderes Thema `anker_zwei`.")
        nachher = _baue_prompt(agent, kb, tools=True)

        anteil = len(_gemeinsames_praefix(vorher, nachher)) / len(vorher)
        assert anteil > 0.8, f"Nur {anteil:.0%} des Prompts sind cachebar"

    def test_ohne_learnings_bleibt_der_prompt_unveraendert(self, agent, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        mit_kb = _baue_prompt(agent, kb, tools=True)
        ohne_kb = agent._augment_with_tool_instructions(agent.system_prompt, read_only=False)
        assert mit_kb == ohne_kb


class TestVerhaltenUnveraendert:
    def test_alle_learnings_landen_weiterhin_im_prompt(self, agent, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        regeln = [
            "Regel A ueber `alpha_wert`.",
            "Regel B betreffend `beta_wert`.",
            "Regel C zum Thema `gamma_wert`.",
        ]
        for r in regeln:
            kb.add_learning(agent.agent_id, r)
        prompt = _baue_prompt(agent, kb, tools=True)
        for r in regeln:
            assert r in prompt

    def test_agent_ohne_werkzeuge_bekommt_learnings_trotzdem(self, agent, tmp_path):
        kb = AgentKnowledgeBase(file_path=tmp_path / "l.json")
        kb.add_learning(agent.agent_id, "Regel ohne Werkzeuge mit `anker`.")
        prompt = _baue_prompt(agent, kb, tools=False)
        assert "Regel ohne Werkzeuge mit `anker`." in prompt
        assert "write_file" not in prompt

    def test_execute_ohne_werkzeuge_laeuft_durch(self, agent):
        """Absicherung, dass der umgebaute else-Zweig keine ungebundene Variable nutzt."""
        from core.llm_factory import LLMResponse

        antwort = LLMResponse(text="fertig", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2)
        with patch.object(agent, "_llm") as llm:
            llm.generate_with_usage = AsyncMock(return_value=antwort)
            llm.model_name = "m"
            ergebnis = asyncio.run(agent.execute(AgentTask(
                task_id="t1", agent_id=agent.agent_id, description="Tu etwas", project_dir=None,
            )))
        assert ergebnis.success is True
        assert ergebnis.content == "fertig"
