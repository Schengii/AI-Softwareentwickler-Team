"""
tests/test_agent_contracts_alias.py – Testet P6-6 (ROADMAP_TEMP.md): core/message_bus.py
enthielt nur noch zwei Dataclasses, ohne dass der Name das noch beschrieb - core/
agent_contracts.py ist jetzt die kanonische Definition, core/message_bus.py ein reiner
Re-Export-Alias für die über 60 bestehenden Importe.
"""

import unittest

import core.agent_contracts as agent_contracts
import core.message_bus as message_bus


class TestAgentContractsAlias(unittest.TestCase):
    def test_message_bus_reexports_the_same_class_objects(self):
        """Identität, nicht nur Gleichheit - isinstance()/Pickling/Dataclass-Vergleiche über
        beide Importpfade hinweg müssen sich wie EIN Typ verhalten, nicht wie zwei."""
        self.assertIs(message_bus.AgentTask, agent_contracts.AgentTask)
        self.assertIs(message_bus.AgentResult, agent_contracts.AgentResult)

    def test_instances_created_via_either_import_path_are_interchangeable(self):
        from core.agent_contracts import AgentResult as ResultViaNewName
        from core.message_bus import AgentResult as ResultViaOldName

        instance = ResultViaOldName(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok")
        self.assertIsInstance(instance, ResultViaNewName)


if __name__ == "__main__":
    unittest.main()
