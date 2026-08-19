"""
tests/test_agents.py – Unit-Tests für alle 30 Agenten und Basis-Strukturen
"""

import unittest
from agents.orchestrator import Orchestrator
from agents.base_agent import BaseAgent
from agents import (
    TeamLeadAgent, ProductOwnerAgent, BusinessAnalystAgent, WebResearchAgent,
    ArchitectAgent, FinOpsAgent, FrontendAgent, BackendAgent, DatabaseAgent,
    ApiIntegrationAgent, DataEngineerAgent, MobileAgent, MLAgent, PerformanceAgent,
    ImageGeneratorAgent, CopywriterAgent, UIUXAgent, I18nAgent, DocumentationAgent,
    DevOpsAgent, TesterAgent, SecurityAgent, CodeReviewerAgent, RefactoringAgent,
    ComplianceAgent, ProjectCleanerAgent, AgentTrainerAgent, RetrospectiveAgent, ReadmeAgent, GitHubAgent
)


class TestAgentSystem(unittest.TestCase):
    """Prüft die Initialisierung und Konfiguration aller 30 Agenten."""

    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_all_30_agents_registered(self):
        """Stellt sicher, dass exakt 30 Spezialisten im Team registriert sind."""
        self.assertEqual(len(self.orchestrator._agents), 30)

    def test_agent_instances_and_prompts(self):
        """Prüft, dass jeder Agent einen validen System-Prompt und eine eindeutige ID besitzt."""
        expected_agents = [
            ("team_lead", TeamLeadAgent),
            ("product_owner", ProductOwnerAgent),
            ("business_analyst", BusinessAnalystAgent),
            ("web_research", WebResearchAgent),
            ("architect", ArchitectAgent),
            ("finops", FinOpsAgent),
            ("frontend", FrontendAgent),
            ("backend", BackendAgent),
            ("database", DatabaseAgent),
            ("api_integration", ApiIntegrationAgent),
            ("data_engineer", DataEngineerAgent),
            ("mobile", MobileAgent),
            ("ml", MLAgent),
            ("performance", PerformanceAgent),
            ("image_generator", ImageGeneratorAgent),
            ("copywriter", CopywriterAgent),
            ("ui_ux", UIUXAgent),
            ("i18n", I18nAgent),
            ("documentation", DocumentationAgent),
            ("devops", DevOpsAgent),
            ("tester", TesterAgent),
            ("security", SecurityAgent),
            ("code_reviewer", CodeReviewerAgent),
            ("refactoring", RefactoringAgent),
            ("compliance", ComplianceAgent),
            ("project_cleaner", ProjectCleanerAgent),
            ("agent_trainer", AgentTrainerAgent),
            ("retrospective", RetrospectiveAgent),
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
        self.assertIn("Dein KI-Team (30 Spezialisten)", info)
        self.assertIn("Phase 1: Führung, Planung & Recherche", info)


if __name__ == "__main__":
    unittest.main()
