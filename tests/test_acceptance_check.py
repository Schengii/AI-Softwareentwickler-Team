"""
tests/test_acceptance_check.py – Testet P4-2 (ROADMAP_TEMP.md): "Keine Abnahme gegen die
ursprüngliche Anforderung"

core/acceptance_check.py lässt den product_owner-Agenten in zwei Schritten prüfen, ob geliefert
wurde, was bestellt war - nicht nur, ob Tests grün sind (real gemessen an `cachegrid_proxy`:
3 Testfunktionen bestanden die Testtiefen-Prüfung mit "100%", obwohl mehrere bestellte Features
komplett fehlten). Schritt 1 (extract_requirements) läuft ohne Tools, Schritt 2
(verify_acceptance) mit Lese-Tool-Zugriff gegen den echten Code.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from core.acceptance_check import (
    AcceptanceCheckResult,
    extract_requirements,
    parse_requirements,
    parse_verification,
    read_requirements,
    verify_acceptance,
    write_requirements,
)
from core.message_bus import AgentResult


class TestParseRequirements(unittest.TestCase):
    def test_parses_numbered_list(self):
        content = "1. Write-Behind-Strategie implementieren\n2. Key-Tagging und selektive Invalidierung\n"
        self.assertEqual(
            parse_requirements(content),
            ["Write-Behind-Strategie implementieren", "Key-Tagging und selektive Invalidierung"],
        )

    def test_ignores_non_numbered_lines(self):
        content = "Hier ist die Liste:\n1. Erste Anforderung\nEinleitender Text\n2. Zweite Anforderung\n"
        self.assertEqual(parse_requirements(content), ["Erste Anforderung", "Zweite Anforderung"])

    def test_caps_at_limit(self):
        content = "\n".join(f"{i}. Anforderung {i}" for i in range(1, 20))
        self.assertEqual(len(parse_requirements(content, limit=10)), 10)

    def test_empty_content_returns_empty_list(self):
        self.assertEqual(parse_requirements(""), [])


class TestParseVerification(unittest.TestCase):
    def test_all_met(self):
        requirements = ["Feature A", "Feature B"]
        content = "1. [ERFÜLLT] siehe app/a.py\n2. [ERFÜLLT] siehe app/b.py\n"
        result = parse_verification(content, requirements)
        self.assertTrue(result.parsed)
        self.assertEqual(result.requirements_met, True)
        self.assertEqual(result.met, requirements)
        self.assertEqual(result.missing, [])

    def test_some_missing(self):
        requirements = ["Write-Behind-Strategie", "Key-Tagging", "Race-Condition-Tests"]
        content = (
            "1. [ERFÜLLT] app/cache.py implementiert Write-Behind\n"
            "2. [FEHLT] kein Tagging-Mechanismus im Code gefunden\n"
            "3. [FEHLT] nur 3 Testfunktionen, keine Race-Condition-Tests\n"
        )
        result = parse_verification(content, requirements)
        self.assertTrue(result.parsed)
        self.assertEqual(result.requirements_met, False)
        self.assertEqual(result.missing, ["Key-Tagging", "Race-Condition-Tests"])

    def test_unparseable_response_does_not_block(self):
        requirements = ["Feature A", "Feature B"]
        result = parse_verification("Ich habe den Code geprüft und alles sieht gut aus.", requirements)
        self.assertFalse(result.parsed)
        self.assertIsNone(result.requirements_met)

    def test_count_mismatch_does_not_block(self):
        requirements = ["Feature A", "Feature B", "Feature C"]
        content = "1. [ERFÜLLT] ok\n2. [FEHLT] fehlt\n"  # nur 2 statt 3 Zeilen
        result = parse_verification(content, requirements)
        self.assertFalse(result.parsed)
        self.assertIsNone(result.requirements_met)

    def test_case_insensitive_and_umlaut_variant(self):
        requirements = ["Feature A"]
        result = parse_verification("1. [erfullt] ok", requirements)
        self.assertTrue(result.parsed)
        self.assertEqual(result.met, ["Feature A"])

    def test_no_requirements_returns_default_result(self):
        result = parse_verification("egal", [])
        self.assertIsNone(result.requirements_met)
        self.assertFalse(result.parsed)


class TestRequirementsFilePersistence(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_write_then_read_roundtrip(self):
        write_requirements(self.project_dir, ["A", "B"])
        self.assertEqual(read_requirements(self.project_dir), ["A", "B"])

    def test_read_missing_file_returns_empty_list(self):
        self.assertEqual(read_requirements(self.project_dir), [])


class _FakeOrchestrator:
    def __init__(self, response_content: str, success: bool = True):
        self._run_single_agent = AsyncMock(
            return_value=AgentResult(
                task_id="t", agent_id="product_owner", agent_name="Product Owner",
                success=success, content=response_content,
            )
        )


class TestExtractRequirements(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_extracts_and_persists_requirements(self):
        orch = _FakeOrchestrator("1. Feature A\n2. Feature B\n")
        requirements = asyncio.run(extract_requirements(orch, "Baue Feature A und B", self.project_dir))
        self.assertEqual(requirements, ["Feature A", "Feature B"])
        self.assertEqual(read_requirements(self.project_dir), ["Feature A", "Feature B"])
        orch._run_single_agent.assert_awaited_once()
        task = orch._run_single_agent.await_args.args[0]
        self.assertFalse(task.allow_tools)  # Phase 1 braucht keinen Tool-Zugriff.

    def test_failed_call_returns_empty_list_without_writing_file(self):
        orch = _FakeOrchestrator("", success=False)
        requirements = asyncio.run(extract_requirements(orch, "Baue etwas", self.project_dir))
        self.assertEqual(requirements, [])
        self.assertEqual(read_requirements(self.project_dir), [])


class TestVerifyAcceptance(unittest.TestCase):
    def test_calls_agent_read_only_with_project_dir(self):
        orch = _FakeOrchestrator("1. [ERFÜLLT] ok\n2. [FEHLT] fehlt\n")
        result = asyncio.run(verify_acceptance(orch, "/some/project", ["Feature A", "Feature B"]))
        self.assertIsInstance(result, AcceptanceCheckResult)
        self.assertEqual(result.missing, ["Feature B"])
        task = orch._run_single_agent.await_args.args[0]
        self.assertTrue(task.allow_tools)
        self.assertTrue(task.tools_read_only)
        self.assertEqual(task.project_dir, "/some/project")

    def test_no_requirements_skips_the_call_entirely(self):
        orch = _FakeOrchestrator("egal")
        result = asyncio.run(verify_acceptance(orch, "/some/project", []))
        self.assertIsNone(result.requirements_met)
        orch._run_single_agent.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
