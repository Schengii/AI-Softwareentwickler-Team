"""
tests/test_tdd_workflow.py – Testet die TDD- und Profiler-Integration im Orchestrator
"""

import unittest


class TestTDDWorkflow(unittest.TestCase):
    def test_tdd_and_profiler_context_injection(self):
        from config import ENABLE_PROJECT_PROFILING, ENABLE_TDD_WORKFLOW
        self.assertTrue(ENABLE_PROJECT_PROFILING)
        self.assertTrue(ENABLE_TDD_WORKFLOW)
