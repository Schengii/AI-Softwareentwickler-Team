"""
tests/test_secret_scanner.py – Testet core/secret_scanner.py

Realer Fund: agents/github_agent.py committet/pusht bisher ungeprüft, was `git add -A`
staged – ein Agent, der versehentlich einen echten API-Key in eine generierte Datei
schreibt, hätte diesen Secret unbemerkt auf GitHub gepusht. core/secret_scanner.py
durchsucht den echten `git diff`-Output regelbasiert auf neu hinzugefügte Secrets.
"""

import unittest

from core.secret_scanner import scan_diff


def _diff(file_path: str, added_lines: list[str], removed_lines: list[str] | None = None) -> str:
    """Baut einen minimalen, aber realistischen `git diff`-Ausschnitt für einen Test."""
    removed_lines = removed_lines or []
    body = "\n".join(f"-{line}" for line in removed_lines) + (
        "\n" if removed_lines else ""
    ) + "\n".join(f"+{line}" for line in added_lines)
    return (
        f"diff --git a/{file_path} b/{file_path}\n"
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        f"@@ -1,1 +1,{len(added_lines)} @@\n"
        f"{body}\n"
    )


class TestKnownProviderPatterns(unittest.TestCase):
    def test_detects_aws_access_key(self):
        diff = _diff("config.py", ['AWS_KEY = "AKIAABCDEFGHIJKLMNOP"'])
        findings = scan_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "AWS Access Key")
        self.assertEqual(findings[0].file_path, "config.py")

    def test_detects_private_key_block(self):
        diff = _diff("id_rsa", ["-----BEGIN RSA PRIVATE KEY-----"])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Private-Key-Block" for f in findings))

    def test_detects_anthropic_key(self):
        diff = _diff(".env", ['ANTHROPIC_API_KEY = "sk-ant-abcdef0123456789ghijklmno"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Anthropic API-Key" for f in findings))

    def test_ignores_official_aws_documentation_example_key(self):
        # AKIAIOSFODNN7EXAMPLE ist AWS' eigener offizieller Beispiel-Key aus deren Doku -
        # taucht real in generierten README/Beispieldateien auf und ist kein echter Fund.
        diff = _diff("README.md", ['aws_access_key_id = AKIAIOSFODNN7EXAMPLE  # example'])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])


class TestGenericAssignmentPattern(unittest.TestCase):
    def test_detects_generic_password_assignment(self):
        diff = _diff("settings.py", ['password = "Sup3rSecretValueHere123"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_ignores_common_placeholders(self):
        for value in ("changeme", "your-api-key-here", "placeholder-value-123", "xxxxxxxxxxxx"):
            diff = _diff(".env.example", [f'api_key = "{value}"'])
            findings = scan_diff(diff)
            self.assertEqual(findings, [], f"Platzhalter '{value}' hätte nicht gemeldet werden dürfen")

    def test_ignores_short_values_below_length_threshold(self):
        diff = _diff("settings.py", ['token = "short"'])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])


class TestOnlyAddedLinesCount(unittest.TestCase):
    def test_removed_secret_is_not_flagged(self):
        diff = _diff("config.py", ["import os"], removed_lines=['AWS_KEY = "AKIAABCDEFGHIJKLMNOP"'])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])

    def test_unrelated_added_lines_produce_no_findings(self):
        diff = _diff("main.py", ["def foo():", "    return 42"])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])


class TestRedaction(unittest.TestCase):
    def test_snippet_never_contains_full_secret_value(self):
        diff = _diff("config.py", ['AWS_KEY = "AKIAABCDEFGHIJKLMNOP"'])
        findings = scan_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", findings[0].snippet)
        self.assertIn("REDACTED", findings[0].snippet)


if __name__ == "__main__":
    unittest.main()
