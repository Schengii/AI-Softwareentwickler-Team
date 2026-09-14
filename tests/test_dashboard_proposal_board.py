"""
tests/test_dashboard_proposal_board.py – Testet den "Vorschläge, die auf Freigabe warten"-
Bereich im Dashboard (Gesamtsystem-Analyse 2026-09-14, Punkt 3.4).

Root-Cause-Befunde, Roadmap- und Optimierungsvorschläge legen bewusst NICHT-autonome Tickets an
- ohne eigene Bündelung verschwanden sie bisher zwischen normalen Arbeits-Tickets im
Kanban-Board (ein "blocked"-Root-Cause-Befund sah dort wie ein echter Governance-Blocker aus).
Dieser Test verankert vor allem, dass die im Dashboard-JS hart codierte Quellen-Liste
(PROPOSAL_TICKET_SOURCES) nicht unbemerkt von den tatsächlichen Ticket-Quellen der drei
Vorschlags-Module abweicht.
"""

import re
import unittest

from core.optimization_advisor import analyze  # noqa: F401 - importierbar halten für den Source-String unten
from core.roadmap_advisor import PROPOSAL_TICKET_SOURCE
from core.root_cause_analyst import TICKET_SOURCE as ROOT_CAUSE_TICKET_SOURCE
from interface.web_dashboard import HTML_DASHBOARD

# core/optimization_advisor.py verwendet "optimization_advisor" als Literal (siehe dortiger
# record_unused_agent_tickets()/analyze()-Docstring), ohne eigene benannte Konstante zu
# exportieren - hier deshalb als Literal nachgezogen statt einen Import zu erzwingen, der im
# Modul selbst nicht vorgesehen ist.
OPTIMIZATION_ADVISOR_TICKET_SOURCE = "optimization_advisor"


class TestProposalBoardSourcesInSync(unittest.TestCase):
    def _js_proposal_sources(self) -> list[str]:
        match = re.search(r"const PROPOSAL_TICKET_SOURCES = \[(.*?)\];", HTML_DASHBOARD)
        self.assertIsNotNone(match, "PROPOSAL_TICKET_SOURCES-Array nicht im Dashboard-HTML gefunden")
        return re.findall(r"'([^']+)'", match.group(1))

    def test_js_source_list_matches_the_three_advisory_ticket_sources(self):
        js_sources = set(self._js_proposal_sources())
        expected = {ROOT_CAUSE_TICKET_SOURCE, PROPOSAL_TICKET_SOURCE, OPTIMIZATION_ADVISOR_TICKET_SOURCE}
        self.assertEqual(
            js_sources, expected,
            "Dashboard-JS PROPOSAL_TICKET_SOURCES ist nicht mehr synchron mit den tatsächlichen "
            "source-Werten von core/root_cause_analyst.py, core/roadmap_advisor.py und "
            "core/optimization_advisor.py.",
        )

    def test_proposal_board_container_and_kanban_exclusion_present(self):
        self.assertIn('id="proposalBoard"', HTML_DASHBOARD)
        self.assertIn("renderProposalBoard", HTML_DASHBOARD)
        self.assertIn("!PROPOSAL_TICKET_SOURCES.includes(t.source)", HTML_DASHBOARD)


if __name__ == "__main__":
    unittest.main()
