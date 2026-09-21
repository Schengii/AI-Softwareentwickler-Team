"""
tests/test_unused_agent_prompt_guidance.py – Testet P2-3 (ROADMAP_TEMP.md): "13 von 33 Rollen
wurden in 20 Läufen kein einziges Mal eingesetzt"

Realer Fund: mehrere immer im Zerlegungs-Prompt sichtbare Rollen (nicht hinter dem
Nischen-Filter core.task_manager._NICHE_AGENT_TRIGGERS versteckt) wurden trotzdem nie vom
Planer gewählt - product_owner, business_analyst, ui_ux, devops, documentation, refactoring,
github. Dieselbe Ursache wie bei den bereits zuvor geschärften Rollen (accessibility, finops,
web_research, performance, image_generator, copywriter, mobile, ml, prompt_engineer,
data_engineer, i18n, team_lead - siehe deren Kommentare in core/task_manager.py): die
Beschreibung nannte nur WAS die Rolle kann, nicht WANN man sie tatsächlich braucht.

Regressionsschutz: jede der sieben Rollen behält ein konkretes "Einsetzen bei"-Kriterium in
ihrer AVAILABLE_AGENTS-Beschreibung UND eine explizite Regel im DECOMPOSE_SYSTEM_PROMPT -
verhindert, dass eine künftige Umformulierung wieder auf eine reine Fähigkeitsbeschreibung
zurückfällt.
"""

import unittest

from core.task_manager import AVAILABLE_AGENTS, DECOMPOSE_SYSTEM_PROMPT

_SHARPENED_ROLE_IDS = (
    "product_owner",
    "business_analyst",
    "ui_ux",
    "devops",
    "documentation",
    "refactoring",
    "github",
)


class TestSharpenedRoleDescriptions(unittest.TestCase):
    def test_each_role_names_a_concrete_when_to_use_criterion(self):
        for agent_id in _SHARPENED_ROLE_IDS:
            with self.subTest(agent_id=agent_id):
                description = AVAILABLE_AGENTS[agent_id]["description"]
                self.assertIn("Einsetzen bei", description)

    def test_each_role_has_an_explicit_decompose_prompt_rule(self):
        for agent_id in _SHARPENED_ROLE_IDS:
            with self.subTest(agent_id=agent_id):
                self.assertIn(f"{agent_id} einbeziehen", DECOMPOSE_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
