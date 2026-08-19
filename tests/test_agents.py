"""
tests/test_agents.py – Unit-Tests für alle 23 Agenten und Basis-Strukturen
"""

import unittest
from agents.orchestrator import Orchestrator
from agents.base_agent import BaseAgent
from agents import (
    BusinessAnalystAgent, ProductOwnerAgent, ArchitectAgent, FinOpsAgent,
    UIUXAgent, FrontendAgent, BackendAgent, DatabaseAgent, ApiIntegrationAgent,
    DataEngineerAgent, MobileAgent, MLAgent, PerformanceAgent, I18nAgent,
    DevOpsAgent, TesterAgent, DocumentationAgent, SecurityAgent,
    CodeReviewerAgent, RefactoringAgent, ComplianceAgent, ReadmeAgent, GitHubAgent
)


class TestAgentSystem(unittest.TestCase):
    """Prüft die Initialisierung und Konfiguration aller Agenten."""

    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_all_23_agents_registered(self):
        """Stellt sicher, dass exakt 23 Spezialisten im Team registriert sind."""
        self.assertEqual(len(self.orchestrator._agents), 23)

    def test_agent_instances_and_prompts(self):
        """Prüft, dass jeder Agent einen validen System-Prompt und eine eindeutige ID besitzt."""
        expected_agents = [
            ("business_analyst", BusinessAnalystAgent),
            ("product_owner", ProductOwnerAgent),
            ("architect", ArchitectAgent),
            ("finops", FinOpsAgent),
            ("ui_ux", UIUXAgent),
            ("frontend", FrontendAgent),
            ("backend", BackendAgent),
            ("database", DatabaseAgent),
            ("api_integration", ApiIntegrationAgent),
            ("data_engineer", DataEngineerAgent),
            ("mobile", MobileAgent),
            ("ml", MLAgent),
            ("performance", PerformanceAgent),
            ("i18n", I18nAgent),
            ("devops", DevOpsAgent),
            ("tester", TesterAgent),
            ("documentation", DocumentationAgent),
            ("security", SecurityAgent),
            ("code_reviewer", CodeReviewerAgent),
            ("refactoring", RefactoringAgent),
            ("compliance", ComplianceAgent),
            ("readme", ReadmeAgent),
            ("github", GitHubAgent),
        ]

        for agent_id, agent_cls in expected_agents:
            self.assertIn(agent_id, self.orchestrator._agents)
            agent = self.orchestrator._agents[agent_id]
            self.assertIsInstance(agent, agent_cls)
            self.assertTrue(len(agent.system_prompt.strip()) > 50, f"System prompt for {agent_id} is too short")
            self.assertEqual(agent.agent_id, agent_id)

    def test_team_info_generation(self):
        """Prüft, dass die get_team_info-Methode eine lesbare Markdown-Struktur liefert."""
        info = self.orchestrator.get_team_info()
        self.assertIn("Dein KI-Team (23 Spezialisten)", info)
        self.assertIn("Phase 1: Planung & Produkt", info)
        self.assertIn("Phase 4: Review, Refactoring & Compliance", info)


if __name__ == "__main__":
    unittest.main()
