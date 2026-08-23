"""
tests/test_agents.py – Unit-Tests für alle 30 Agenten und Basis-Strukturen
"""

import unittest

from agents import (
    AccessibilityAgent,
    AgentTrainerAgent,
    ApiIntegrationAgent,
    ArchitectAgent,
    BackendAgent,
    BusinessAnalystAgent,
    CodeReviewerAgent,
    ComplianceAgent,
    CopywriterAgent,
    DatabaseAgent,
    DataEngineerAgent,
    DevOpsAgent,
    DocumentationAgent,
    FinOpsAgent,
    FrontendAgent,
    GitHubAgent,
    I18nAgent,
    ImageGeneratorAgent,
    MLAgent,
    MobileAgent,
    PerformanceAgent,
    ProductOwnerAgent,
    ProjectCleanerAgent,
    PromptEngineerAgent,
    ReadmeAgent,
    RefactoringAgent,
    ResilienceGuardAgent,
    RetrospectiveAgent,
    SecurityAgent,
    TeamLeadAgent,
    TesterAgent,
    UIUXAgent,
    WebResearchAgent,
)
from agents.orchestrator import Orchestrator


class TestAgentSystem(unittest.TestCase):
    """Prüft die Initialisierung und Konfiguration aller 33 Agenten."""

    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_all_33_agents_registered(self):
        """Stellt sicher, dass alle 33 Spezialisten im Team registriert sind."""
        self.assertEqual(len(self.orchestrator._agents), 33)

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
            ("prompt_engineer", PromptEngineerAgent),
            ("performance", PerformanceAgent),
            ("image_generator", ImageGeneratorAgent),
            ("copywriter", CopywriterAgent),
            ("ui_ux", UIUXAgent),
            ("accessibility", AccessibilityAgent),
            ("i18n", I18nAgent),
            ("documentation", DocumentationAgent),
            ("devops", DevOpsAgent),
            ("tester", TesterAgent),
            ("security", SecurityAgent),
            ("resilience_guard", ResilienceGuardAgent),
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
        """Prüft, dass die get_team_info-Methode eine lesbare Markdown-Struktur der Fachbereiche liefert."""
        info = self.orchestrator.get_team_info()
        self.assertIn("Strukturierte Fachbereiche & Teamleiter-Hierarchie", info)
        self.assertIn("Planning Lead", info)
        self.assertIn("Design Lead", info)
        self.assertIn("Dev Lead", info)
        self.assertIn("Content & Doc Lead", info)


if __name__ == "__main__":
    unittest.main()
