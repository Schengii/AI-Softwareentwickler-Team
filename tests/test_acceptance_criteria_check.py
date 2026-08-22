"""
tests/test_acceptance_criteria_check.py – Testet die Akzeptanzkriterien-Ergänzung in
core/result_aggregator.py.ResultAggregator.synthesize()

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: product_owner/business_analyst
formulieren Akzeptanzkriterien (Given/When/Then), aber nichts prüft am Ende mechanisch, ob sie
erfüllt wurden. Statt eines zusätzlichen LLM-Aufrufs wird der ohnehin stattfindende Synthese-
Aufruf konditional um eine entsprechende Anweisung erweitert - dieser Test beweist, dass die
Erweiterung NUR dann im System-Prompt landet, wenn product_owner/business_analyst tatsächlich
Teil der erfolgreichen Ergebnisse ist, sonst unverändert bleibt (kein unnötiger Prompt-Text).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock

from core.llm_factory import LLMResponse
from core.message_bus import AgentResult
from core.result_aggregator import ACCEPTANCE_CRITERIA_CHECK_INSTRUCTION, ResultAggregator


def _result(agent_id: str, content: str = "Ergebnis.", success: bool = True) -> AgentResult:
    return AgentResult(
        task_id=f"t-{agent_id}", agent_id=agent_id, agent_name=agent_id,
        success=success, content=content, total_tokens=10,
    )


class TestAcceptanceCriteriaCheck(unittest.TestCase):
    def setUp(self):
        self.aggregator = ResultAggregator()
        self.aggregator._llm = AsyncMock()
        self.aggregator._llm.generate_with_usage = AsyncMock(
            return_value=LLMResponse(text="### Fertig", model_name="fake", total_tokens=5),
        )

    def test_business_analyst_present_adds_instruction(self):
        results = [_result("business_analyst", "User Story mit Given/When/Then..."), _result("backend")]
        asyncio.run(self.aggregator.synthesize("Baue etwas", "Kurz", results))

        system_prompt = self.aggregator._llm.generate_with_usage.call_args[0][1]
        self.assertIn(ACCEPTANCE_CRITERIA_CHECK_INSTRUCTION, system_prompt)

    def test_product_owner_present_adds_instruction(self):
        results = [_result("product_owner", "MVP-Scope mit Akzeptanzkriterien..."), _result("backend")]
        asyncio.run(self.aggregator.synthesize("Baue etwas", "Kurz", results))

        system_prompt = self.aggregator._llm.generate_with_usage.call_args[0][1]
        self.assertIn(ACCEPTANCE_CRITERIA_CHECK_INSTRUCTION, system_prompt)

    def test_neither_present_leaves_prompt_unchanged(self):
        results = [_result("backend"), _result("tester")]
        asyncio.run(self.aggregator.synthesize("Baue etwas", "Kurz", results))

        system_prompt = self.aggregator._llm.generate_with_usage.call_args[0][1]
        self.assertNotIn(ACCEPTANCE_CRITERIA_CHECK_INSTRUCTION, system_prompt)

    def test_failed_business_analyst_does_not_add_instruction(self):
        # Ein GESCHEITERTER business_analyst-Aufruf hat keine verwertbaren Akzeptanzkriterien
        # geliefert - der Prompt-Zusatz wäre hier irreführend.
        results = [_result("business_analyst", success=False, content=""), _result("backend")]
        asyncio.run(self.aggregator.synthesize("Baue etwas", "Kurz", results))

        system_prompt = self.aggregator._llm.generate_with_usage.call_args[0][1]
        self.assertNotIn(ACCEPTANCE_CRITERIA_CHECK_INSTRUCTION, system_prompt)


if __name__ == "__main__":
    unittest.main()
