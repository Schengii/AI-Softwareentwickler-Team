"""
tests/test_agent_registry_consistency.py – Hält die vier unabhängig gepflegten Register für
Agentenrollen synchron: `core.task_manager.AVAILABLE_AGENTS` (Beschreibung für den Planer),
`config.AGENT_MODELS`/die `config.DEPARTMENT_*_AGENTS`-Mengen (Modell- und Fachbereichs-
Zuordnung) und `agents.orchestrator.Orchestrator._agents` (tatsächlich instanziierte
Agenten-Klasse). Eine neue Rolle hinzuzufügen bedeutet heute, mehrere dieser Stellen von Hand
zu pflegen, OHNE dass ein Vergessen einer davon beim Start je auffällt - eine vergessene
`AGENT_MODELS`-Zuordnung fällt z.B. erst zur Laufzeit auf, wenn `config.get_model_for_agent()`
lautlos auf `DEFAULT_AGENT_MODEL` zurückfällt, statt die bewusst gewählte Modellstufe für diese
Rolle zu nutzen. Dieser Test schließt diese Lücke, ohne die vier separaten Register selbst
zusammenzulegen (das wäre ein größerer Umbau) - er verhindert nur, dass sie beim Wachsen des
Teams unbemerkt auseinanderlaufen.
"""

import unittest

import config
from agents.orchestrator import Orchestrator
from core.task_manager import _DECOMPOSE_EXCLUDED_AGENT_IDS, AVAILABLE_AGENTS

# Fachbereichsleiter tauchen bewusst NICHT in AVAILABLE_AGENTS auf (sie werden nicht direkt vom
# Planer als Teilaufgaben-Empfänger ausgewählt, sondern über die Fachbereichs-Orchestrierung
# separat dispatcht) - aber sehr wohl in config.AGENT_MODELS/den DEPARTMENT_*_AGENTS-Mengen.
_DEPARTMENT_LEAD_IDS = {
    "dev_lead", "governance_lead", "qa_lead", "design_lead",
    "planning_lead", "content_lead", "creative_lead",
}


class TestAgentRegistryConsistency(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_every_available_agent_is_instantiated_in_orchestrator(self):
        available_ids = set(AVAILABLE_AGENTS.keys())
        instantiated_ids = set(self.orchestrator._agents.keys())
        self.assertEqual(
            available_ids - instantiated_ids, set(),
            "In AVAILABLE_AGENTS registriert, aber vom Orchestrator nie instanziiert - "
            "eine Aufgabe für diese Rolle würde zur Laufzeit fehlschlagen.",
        )
        self.assertEqual(
            instantiated_ids - available_ids, set(),
            "Vom Orchestrator instanziiert, aber dem Planer nie als wählbare ID beschrieben - "
            "der Planer kann diese Rolle nie einer Teilaufgabe zuweisen.",
        )

    def test_every_available_agent_has_an_explicit_model_tier(self):
        available_ids = set(AVAILABLE_AGENTS.keys())
        model_ids = set(config.AGENT_MODELS.keys())
        self.assertEqual(
            available_ids - model_ids, set(),
            "Keine explizite Modell-Zuordnung in config.AGENT_MODELS - "
            "get_model_for_agent() faellt lautlos auf DEFAULT_AGENT_MODEL zurueck, "
            "statt die fuer diese Rolle bewusst gewaehlte Komplexitaetsstufe zu nutzen.",
        )

    def test_department_lead_ids_have_a_model_but_no_available_agent_entry(self):
        # Gegenprobe zum vorigen Test: Fachbereichsleiter sind der EINZIGE bewusste
        # Unterschied zwischen den beiden Registern - jede andere Abweichung waere ein Fund.
        model_ids = set(config.AGENT_MODELS.keys())
        available_ids = set(AVAILABLE_AGENTS.keys())
        self.assertTrue(_DEPARTMENT_LEAD_IDS.issubset(model_ids))
        self.assertEqual(model_ids - available_ids, _DEPARTMENT_LEAD_IDS)

    def test_every_agent_model_id_belongs_to_exactly_one_department(self):
        department_sets = [
            config.DEPARTMENT_PLANNING_AGENTS,
            config.DEPARTMENT_DEV_AGENTS,
            config.DEPARTMENT_QA_AGENTS,
            config.DEPARTMENT_GOVERNANCE_AGENTS,
            # DEPARTMENT_CREATIVE_AGENTS ist bewusst die Vereinigung aus DESIGN + CONTENT +
            # "creative_lead" (siehe config.py) - separat geprueft, um keine Rollen doppelt
            # zu zaehlen.
            config.DEPARTMENT_DESIGN_AGENTS,
            config.DEPARTMENT_CONTENT_AGENTS,
            {"creative_lead"},
        ]
        model_ids = set(config.AGENT_MODELS.keys())
        seen: dict[str, int] = {}
        for dept_set in department_sets:
            for agent_id in dept_set:
                seen[agent_id] = seen.get(agent_id, 0) + 1

        self.assertEqual(
            model_ids - set(seen), set(),
            "In config.AGENT_MODELS, aber in keiner DEPARTMENT_*_AGENTS-Menge - "
            "diese Rolle wird nie einem Fachbereich zugeordnet.",
        )
        duplicates = {agent_id for agent_id, count in seen.items() if count > 1}
        self.assertEqual(
            duplicates, set(),
            f"In mehreren Fachbereichen gleichzeitig gelistet: {duplicates}",
        )

    def test_decompose_excluded_ids_are_still_valid_agent_ids(self):
        # Verhindert das Gegenteil eines Drift-Funds: eine ausgeschlossene ID, die es als
        # Agentenrolle gar nicht mehr gibt (z.B. nach einer Umbenennung), waere ein stiller
        # Blindgänger im Ausschlussfilter.
        for agent_id in _DECOMPOSE_EXCLUDED_AGENT_IDS:
            self.assertIn(agent_id, config.AGENT_MODELS)


if __name__ == "__main__":
    unittest.main()
