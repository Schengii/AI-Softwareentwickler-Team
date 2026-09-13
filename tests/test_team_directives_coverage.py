"""
tests/test_team_directives_coverage.py – Abdeckungstest für PYTHON_CODE_CONTRACT_DIRECTIVE
und die Tester-Signatur-Verifikationsregel.

Stellt sicher, dass:
a) ALLE Python-Code schreibenden Agenten (backend, resilience_guard, ml, security, database,
   api_integration, data_engineer) die Contract-Direktive in ihrem System-Prompt besitzen.
b) Der Tester-Agent die Signatur-Prüfungsregel ("Raten von Keyword-Argumenten ... verboten")
   verbindlich in seinem Prompt enthält.
"""

import unittest

from agents.api_integration_agent import ApiIntegrationAgent
from agents.backend_agent import BackendAgent
from agents.data_engineer_agent import DataEngineerAgent
from agents.database_agent import DatabaseAgent
from agents.ml_agent import MLAgent
from agents.resilience_guard_agent import ResilienceGuardAgent
from agents.security_agent import SecurityAgent
from agents.team_directives import (
    BACKEND_CONTRACT_DIRECTIVE,
    PYTHON_CODE_CONTRACT_DIRECTIVE,
    TESTER_CONTRACT_DIRECTIVE,
)
from agents.tester_agent import TesterAgent
from core.failure_triage import INTERFACE_CONTRACT_FILE

# Neu an PYTHON_CODE_CONTRACT_DIRECTIVE angebundene Agenten (Schritt 1 der KI-Team-Optimierung).
PYTHON_CODE_AGENT_CLASSES = (
    ResilienceGuardAgent,
    MLAgent,
    SecurityAgent,
    DatabaseAgent,
    ApiIntegrationAgent,
    DataEngineerAgent,
)


def _prompt(agent_cls) -> str:
    # Der Prompt hängt nicht vom Zustand ab - kein LLM-Client nötig.
    return agent_cls.system_prompt.fget(None)


class TestPythonCodeContractDirectiveCoverage(unittest.TestCase):
    def test_directive_references_interface_contract_and_module_layout(self):
        self.assertIn(INTERFACE_CONTRACT_FILE, PYTHON_CODE_CONTRACT_DIRECTIVE)
        self.assertIn("app/<modul>/...", PYTHON_CODE_CONTRACT_DIRECTIVE)

    def test_all_python_code_agents_bind_the_contract_directive(self):
        for agent_cls in PYTHON_CODE_AGENT_CLASSES:
            with self.subTest(agent=agent_cls.__name__):
                prompt = _prompt(agent_cls)
                self.assertIn(
                    PYTHON_CODE_CONTRACT_DIRECTIVE,
                    prompt,
                    f"{agent_cls.__name__} bindet PYTHON_CODE_CONTRACT_DIRECTIVE nicht in seinen System-Prompt ein.",
                )

    def test_backend_agent_already_covered_by_backend_contract_directive(self):
        # backend_agent.py war bereits vor dieser Optimierung an BACKEND_CONTRACT_DIRECTIVE
        # gebunden (siehe test_team_directives.py) - kein Doppel-Anhängen von
        # PYTHON_CODE_CONTRACT_DIRECTIVE nötig, da beide denselben Contract-First-Kernsatz
        # (interface_contract.json + Settings-Dev-Defaults) durchsetzen.
        prompt = _prompt(BackendAgent)
        self.assertIn(BACKEND_CONTRACT_DIRECTIVE, prompt)

    def test_resilience_guard_enforces_secure_random_for_jitter(self):
        prompt = _prompt(ResilienceGuardAgent)
        self.assertIn("secrets.SystemRandom().uniform(", prompt)
        self.assertIn("# nosec B311", prompt)


class TestTesterSignatureVerificationDirective(unittest.TestCase):
    def test_tester_contract_directive_forbids_guessing_signatures(self):
        self.assertIn("Raten von Keyword-Argumenten", TESTER_CONTRACT_DIRECTIVE)
        self.assertIn("Methodendefinition", TESTER_CONTRACT_DIRECTIVE)
        self.assertIn("find_symbol_definition", TESTER_CONTRACT_DIRECTIVE)

    def test_tester_agent_binds_the_signature_verification_rule(self):
        prompt = _prompt(TesterAgent)
        self.assertIn(TESTER_CONTRACT_DIRECTIVE, prompt)
        self.assertIn("Raten von Keyword-Argumenten oder Methodensignaturen ist VERBOTEN", prompt)


if __name__ == "__main__":
    unittest.main()
