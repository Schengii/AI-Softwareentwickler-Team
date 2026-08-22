"""
tests/test_model_routing_matrix.py – Testet get_model_for_agent und Fachbereichs-Routing in config.py
"""

import os
import unittest
from unittest.mock import patch

import config
from core.llm_factory import LLMFactory


class TestModelRoutingMatrix(unittest.TestCase):
    def test_default_agent_model(self):
        model = config.get_model_for_agent("unknown_specialist")
        self.assertEqual(model, config.DEFAULT_AGENT_MODEL)

    def test_role_specific_mapping(self):
        arch_model = config.get_model_for_agent("architect")
        self.assertEqual(arch_model, config.AGENT_MODELS["architect"])

    def test_department_override(self):
        with patch.dict(config.DEPARTMENT_MODELS, {"planning": "custom-planning-llm"}), \
             patch.dict(os.environ, {"ARCHITECT_MODEL": ""}):
            # Without specific ENV override on ARCHITECT_MODEL, department level kicks in
            pass

    def test_llm_factory_create_for_agent(self):
        llm = LLMFactory.create_for_agent("copywriter")
        self.assertIsNotNone(llm)


if __name__ == "__main__":
    unittest.main()
