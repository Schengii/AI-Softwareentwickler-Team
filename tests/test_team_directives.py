"""
tests/test_team_directives.py – Contract-First- und Fix-Loop-Direktiven der Kernrollen

Stellt sicher, dass die Direktiven aus agents/team_directives.py tatsächlich in den System-Prompts
von architect, backend, tester und refactoring ankommen.
"""

import unittest

from agents.architect_agent import ArchitectAgent
from agents.backend_agent import BackendAgent
from agents.refactoring_agent import RefactoringAgent
from agents.team_directives import (
    ARCHITECT_CONTRACT_DIRECTIVE,
    BACKEND_CONTRACT_DIRECTIVE,
    FIX_LOOP_DIRECTIVE,
    TESTER_CONTRACT_DIRECTIVE,
)
from agents.tester_agent import TesterAgent
from core.failure_triage import INTERFACE_CONTRACT_FILE


def _prompt(agent_cls) -> str:
    # Der Prompt hängt nicht vom Zustand ab - kein LLM-Client nötig.
    return agent_cls.system_prompt.fget(None)


class TestCoreRolePrompts(unittest.TestCase):
    def test_architect_defines_the_interface_contract(self):
        prompt = _prompt(ArchitectAgent)
        self.assertIn(ARCHITECT_CONTRACT_DIRECTIVE, prompt)
        self.assertIn(INTERFACE_CONTRACT_FILE, prompt)
        self.assertIn('{"modules": {"app/core/encryption.py"', prompt)
        self.assertIn("SettingsConfigDict", prompt)

    def test_backend_implements_contract_and_settings_defaults(self):
        prompt = _prompt(BackendAgent)
        self.assertIn(BACKEND_CONTRACT_DIRECTIVE, prompt)
        self.assertIn(FIX_LOOP_DIRECTIVE, prompt)

    def test_backend_forbids_get_event_loop_in_sync_context(self):
        # Analysebericht 2026-09-13 (HyperionSentinel): BACKEND_CONTRACT_DIRECTIVE band bisher
        # NICHT die Async-&-Event-Loop-Direktive ein (anders als PYTHON_CODE_CONTRACT_DIRECTIVE,
        # das resilience_guard/ml/security/... bereits abdeckt) - ein `backend`-generiertes
        # `CircuitBreaker.__init__` oder ein Modul-Level-Singleton konnte deshalb unbemerkt
        # `asyncio.get_event_loop()` aufrufen und die gesamte Testsuite schon beim `pytest`-Import
        # mit `RuntimeError: There is no current event loop` zum Absturz bringen (realer Fund im
        # Vorgänger-Projekt `incident_pulse`).
        prompt = _prompt(BackendAgent)
        self.assertIn("asyncio.get_event_loop()", prompt)
        self.assertIn("time.monotonic()", prompt)
        self.assertIn("VERBOTEN", prompt)

    def test_tester_imports_only_real_symbols(self):
        prompt = _prompt(TesterAgent)
        self.assertIn(TESTER_CONTRACT_DIRECTIVE, prompt)
        self.assertIn("EncryptionService(...).encrypt(...)", prompt)
        self.assertIn(FIX_LOOP_DIRECTIVE, prompt)

    def test_refactoring_follows_fix_loop_discipline(self):
        prompt = _prompt(RefactoringAgent)
        self.assertIn(FIX_LOOP_DIRECTIVE, prompt)
        self.assertIn("requirements.txt", FIX_LOOP_DIRECTIVE)

    def test_backend_enforces_worker_lifecycle_and_lifespan(self):
        prompt = _prompt(BackendAgent)
        self.assertIn("Worker-Lifecycle & Graceful Shutdown", prompt)
        self.assertIn("stop()", prompt)
        self.assertIn("lifespan", prompt)

    def test_tester_enforces_domain_logic_unit_tests(self):
        prompt = _prompt(TesterAgent)
        self.assertIn("Fachlogik isoliert testen", prompt)
        self.assertIn("engine.py", prompt)
        self.assertIn("core/", prompt)


if __name__ == "__main__":
    unittest.main()
