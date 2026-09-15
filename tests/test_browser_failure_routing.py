"""
tests/test_browser_failure_routing.py – Tests fuer
agents/orchestrator/verification.py._classify_browser_failure_owner()

Realer Fund (root_cause_analysis, syncwave-Projekt, 2026-09-15, memory/team_lessons.jsonl):
_build_browser_fix_task() wies JEDEN Fehlschlag des Browser/UI-Checks hartcodiert dem
frontend-Agenten zu. Viele Konsolenfehler (CORS, 5xx-API-Antworten, abgelehnte WebSocket-
Handshakes) haben ihre Ursache aber im Backend - der Frontend-Agent kann eine fehlende
CORS-Konfiguration oder einen abstuerzenden Endpunkt nicht beheben, sieht das korrekt, und
der Fix-Loop drehte sich wiederholt ergebnislos.
"""

import unittest

from agents.orchestrator.verification import _classify_browser_failure_owner


class TestClassifyBrowserFailureOwner(unittest.TestCase):
    def test_cors_error_routes_to_backend(self):
        owner = _classify_browser_failure_owner(
            console_errors=["Access to fetch at 'http://api/x' has been blocked by CORS policy"],
            missing_assets=[],
            available_agents={"frontend", "backend"},
        )
        self.assertEqual(owner, "backend")

    def test_websocket_handshake_error_routes_to_backend(self):
        owner = _classify_browser_failure_owner(
            console_errors=["Error during WebSocket handshake: 'Connection' header is missing"],
            missing_assets=[],
            available_agents={"frontend", "backend"},
        )
        self.assertEqual(owner, "backend")

    def test_5xx_response_routes_to_backend(self):
        owner = _classify_browser_failure_owner(
            console_errors=[],
            missing_assets=["HTTP 502: http://127.0.0.1:8123/api/tasks"],
            available_agents={"frontend", "backend"},
        )
        self.assertEqual(owner, "backend")

    def test_404_missing_asset_stays_with_frontend(self):
        # Ein 4xx (echt fehlendes statisches Asset) ist keine Backend-Ursache - muss weiter
        # beim frontend-Agenten landen wie bisher.
        owner = _classify_browser_failure_owner(
            console_errors=[],
            missing_assets=["HTTP 404: http://127.0.0.1:8123/style.css"],
            available_agents={"frontend", "backend"},
        )
        self.assertEqual(owner, "frontend")

    def test_generic_js_error_stays_with_frontend(self):
        owner = _classify_browser_failure_owner(
            console_errors=["Uncaught TypeError: cannot read property 'x' of undefined"],
            missing_assets=[],
            available_agents={"frontend", "backend"},
        )
        self.assertEqual(owner, "frontend")

    def test_backend_signal_without_backend_agent_falls_back_to_frontend(self):
        owner = _classify_browser_failure_owner(
            console_errors=["CORS error"],
            missing_assets=[],
            available_agents={"frontend"},
        )
        self.assertEqual(owner, "frontend")

    def test_no_frontend_agent_falls_back_to_backend(self):
        owner = _classify_browser_failure_owner(
            console_errors=["Uncaught TypeError"],
            missing_assets=[],
            available_agents={"backend"},
        )
        self.assertEqual(owner, "backend")

    def test_no_matching_agent_returns_none(self):
        owner = _classify_browser_failure_owner(
            console_errors=["Uncaught TypeError"],
            missing_assets=[],
            available_agents={"database"},
        )
        self.assertIsNone(owner)


if __name__ == "__main__":
    unittest.main()
