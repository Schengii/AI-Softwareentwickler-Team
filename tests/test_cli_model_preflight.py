"""
tests/test_cli_model_preflight.py – Testet die automatische Start-Preflight-Sicherheitsmaßnahme
in interface/cli.py (CLIInterface._run_startup_model_preflight).

Nutzerwunsch: Bevor das KI-Team überhaupt mit einer Projektaufgabe beginnt, sollen kurz alle
KI-Modelle angepingt und dem Nutzer angezeigt werden, welche gerade verfügbar sind - inkl.
einer Empfehlung, ob sich ein Projektlauf gerade lohnt. core/model_preflight.py lieferte die
Bausteine (bisher nur über den manuellen `--check-models`-Flag abrufbar) bereits, diese Tests
decken die neue automatische Verdrahtung in der interaktiven CLI ab.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.model_preflight import TierStatus
from interface.cli import CLIInterface


def _gruene_ergebnisse() -> list[TierStatus]:
    return [
        TierStatus(tier=t, requested_model="m", effective_model="m", reachable=True)
        for t in ("LITE", "STANDARD", "HEAVY", "ORCHESTRATOR")
    ]


def _rote_ergebnisse() -> list[TierStatus]:
    return [
        TierStatus(tier=t, requested_model="m", effective_model="", reachable=False, error="429 quota")
        for t in ("LITE", "STANDARD", "HEAVY", "ORCHESTRATOR")
    ]


class TestStartupModelPreflight(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()

    def test_gruene_lage_zeigt_bericht_ohne_rueckfrage(self):
        with patch("core.model_preflight.run_model_preflight", new=AsyncMock(return_value=_gruene_ergebnisse())), \
             patch("interface.cli.console.print") as mock_print, \
             patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._run_startup_model_preflight())

        mock_confirm.assert_not_called()  # grün -> keine Rückfrage nötig
        panel_titles = [
            str(c.args[0].title) for c in mock_print.call_args_list
            if c.args and getattr(c.args[0], "title", None)
        ]
        self.assertTrue(any("Modell-Preflight" in t for t in panel_titles))

    def test_rote_lage_fragt_explizit_nach(self):
        with patch("core.model_preflight.run_model_preflight", new=AsyncMock(return_value=_rote_ergebnisse())), \
             patch("interface.cli.console.print"), \
             patch("interface.cli.Confirm.ask", return_value=True) as mock_confirm:
            asyncio.run(self.cli._run_startup_model_preflight())

        mock_confirm.assert_called_once()

    def test_bekannter_cooldown_zeigt_ruecksetzzeit_im_panel(self):
        """Nutzerwunsch: neben der Ampel soll sichtbar sein, WANN die Modelle voraussichtlich
        zurückgesetzt werden. token_guard.get_exhausted_details() liefert das bereits aus den
        Preflight-Pings selbst (core/llm_factory.py markiert bei 429/Quota automatisch)."""
        exhausted_detail = {
            "model_name": "m", "reason": "429 RESOURCE_EXHAUSTED",
            "remaining_seconds": 90.0, "available_at": "12:00:00",
        }
        with patch("core.model_preflight.run_model_preflight", new=AsyncMock(return_value=_rote_ergebnisse())), \
             patch("core.token_guard.token_guard.get_exhausted_details", return_value=[exhausted_detail]), \
             patch("interface.cli.console.print") as mock_print, \
             patch("interface.cli.Confirm.ask", return_value=True):
            asyncio.run(self.cli._run_startup_model_preflight())

        panel_bodies = [
            str(c.args[0].renderable) for c in mock_print.call_args_list
            if c.args and getattr(c.args[0], "renderable", None)
        ]
        gedruckt = "\n".join(panel_bodies)
        self.assertIn("12:00:00 Uhr", gedruckt)

    def test_manueller_recheck_fragt_trotz_roter_lage_nicht_nach(self):
        """interactive_confirm=False (siehe /modelle-Befehl): der Nutzer hat den Check selbst
        ausgelöst und liest den Bericht ohnehin - keine zusätzliche Ja/Nein-Rückfrage nötig."""
        with patch("core.model_preflight.run_model_preflight", new=AsyncMock(return_value=_rote_ergebnisse())), \
             patch("interface.cli.console.print"), \
             patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._run_startup_model_preflight(interactive_confirm=False))

        mock_confirm.assert_not_called()

    def test_preflight_fehler_blockiert_die_sitzung_nicht(self):
        """Der Preflight darf einen Start nie blockieren - ein unerwarteter Fehler wird
        abgefangen, nicht durchgereicht."""
        with patch("core.model_preflight.run_model_preflight", new=AsyncMock(side_effect=RuntimeError("kaputt"))), \
             patch("interface.cli.console.print") as mock_print:
            asyncio.run(self.cli._run_startup_model_preflight())  # darf nicht werfen

        gedruckt = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("übersprungen", gedruckt)


class TestModelleCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()

    def test_modelle_befehl_ruft_den_preflight_auf(self):
        with patch.object(self.cli, "_run_startup_model_preflight", new=AsyncMock()) as mock_preflight:
            asyncio.run(self.cli._handle_command("/modelle"))

        mock_preflight.assert_called_once_with(interactive_confirm=False)


class TestMainLoopRunsPreflightOnce(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()

    def test_main_loop_ruft_preflight_genau_einmal_vor_der_ersten_eingabe(self):
        """Sofortiger EOF nach dem Preflight - stellt sicher, dass der Aufruf VOR der
        Eingabeschleife passiert (nicht z.B. erst nach der ersten Aufgabe) und bei aktivem
        Flag genau einmal erfolgt."""
        with patch("interface.cli.ENABLE_STARTUP_MODEL_PREFLIGHT", True), \
             patch.object(self.cli, "_run_startup_model_preflight", new=AsyncMock()) as mock_preflight, \
             patch.object(self.cli, "_read_user_input", side_effect=EOFError), \
             patch.object(self.cli, "_print_goodbye"):
            asyncio.run(self.cli._main_loop())

        mock_preflight.assert_awaited_once()
        self.assertTrue(self.cli._startup_preflight_done)

    def test_main_loop_ueberspringt_preflight_wenn_deaktiviert(self):
        with patch("interface.cli.ENABLE_STARTUP_MODEL_PREFLIGHT", False), \
             patch.object(self.cli, "_run_startup_model_preflight", new=AsyncMock()) as mock_preflight, \
             patch.object(self.cli, "_read_user_input", side_effect=EOFError), \
             patch.object(self.cli, "_print_goodbye"):
            asyncio.run(self.cli._main_loop())

        mock_preflight.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
