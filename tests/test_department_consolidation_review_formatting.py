"""
tests/test_department_consolidation_review_formatting.py – Testet
agents/orchestrator/reporting.py._format_results_for_review()

Realer Fund aus einer echten, offenen Rückfrage eines governance_lead-Konsolidierungslaufs:
schlugen ALLE Mitglieder einer Phase fehl oder lieferten leeren Inhalt (z.B. ein reines
Tool-Ergebnis ohne abschließenden Text), war der an den Teamleiter übergebene Ergebnis-Block
komplett LEER - der Lead bekam wörtlich "... haben folgende Ergebnisse geliefert:\n\n\nPrüfe
sie ..." und stellte folgerichtig eine Rückfrage ("Ergebnisse wurden im Prompt nicht
mitgeliefert"), statt einen Bericht zu schreiben.
"""

import unittest

from agents.orchestrator.reporting import ReportingMixin
from core.message_bus import AgentResult


class _Reporter(ReportingMixin):
    """Minimaler Host für das Mixin - _format_results_for_review() nutzt kein self-Attribut."""


class TestFormatResultsForReview(unittest.TestCase):
    def setUp(self):
        self.reporter = _Reporter()

    def test_successful_result_with_content_is_shown(self):
        results = [AgentResult(task_id="t1", agent_id="code_reviewer", agent_name="Code-Reviewer",
                                success=True, content="Alles sauber.")]
        text = self.reporter._format_results_for_review(results)
        self.assertIn("Code-Reviewer", text)
        self.assertIn("Alles sauber.", text)

    def test_failed_result_shows_error_instead_of_vanishing(self):
        results = [AgentResult(task_id="t1", agent_id="compliance", agent_name="Compliance",
                                success=False, content="", error="Rate-Limit erschöpft")]
        text = self.reporter._format_results_for_review(results)
        self.assertIn("Compliance", text)
        self.assertIn("fehlgeschlagen", text)
        self.assertIn("Rate-Limit erschöpft", text)

    def test_success_with_empty_content_is_shown_not_silently_dropped(self):
        """success=True aber content="" (reiner Tool-Aufruf ohne Textantwort) darf nicht
        spurlos verschwinden - genau das führte zur echten Rückfrage."""
        results = [AgentResult(task_id="t1", agent_id="project_cleaner", agent_name="Projekt-Hygiene",
                                success=True, content="", files_written=[])]
        text = self.reporter._format_results_for_review(results)
        self.assertIn("Projekt-Hygiene", text)
        self.assertNotEqual(text.strip(), "")

    def test_all_members_failed_or_empty_never_produces_a_blank_block(self):
        """Der konkrete Fund: ALLE Mitglieder einer Phase scheitern/liefern nichts - der
        Ergebnis-Block darf trotzdem nie leer sein, sonst bekommt der Teamleiter buchstäblich
        nichts zu prüfen."""
        results = [
            AgentResult(task_id="t1", agent_id="code_reviewer", agent_name="Code-Reviewer",
                        success=False, content="", error="Provider-Kette erschöpft"),
            AgentResult(task_id="t2", agent_id="refactoring", agent_name="Refactoring",
                        success=False, content="", error="Timeout"),
            AgentResult(task_id="t3", agent_id="project_cleaner", agent_name="Projekt-Hygiene",
                        success=True, content=""),
        ]
        text = self.reporter._format_results_for_review(results)
        self.assertNotEqual(text.strip(), "")
        self.assertIn("Code-Reviewer", text)
        self.assertIn("Refactoring", text)
        self.assertIn("Projekt-Hygiene", text)


if __name__ == "__main__":
    unittest.main()
