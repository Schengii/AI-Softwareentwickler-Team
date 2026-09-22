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


class TestGenericPatternRecognizesRealWorldSecretNames(unittest.TestCase):
    """
    Regression-Tests für einen Code-Review-Fund: die generische Regel verpasste bisher die in
    der Praxis häufigste Klasse von Secret-Funden komplett.

    1. Das führende `\\b` vor der Keyword-Alternation matcht NICHT zwischen `_` und einem
       Buchstaben (beide sind `\\w`) - Variablennamen mit Dienst-/Komponenten-Präfix wie
       `DATABASE_PASSWORD` oder `STRIPE_SECRET_KEY` wurden dadurch NIE erkannt, obwohl dieses
       Präfix-Muster deutlich häufiger vorkommt als der bloße, unpräfigierte Name.
    2. Die Regel verlangte zwingend Anführungszeichen um den Wert - das native, ungequotete
       `.env`-Format (`KEY=wert`), das das Modul in seinem eigenen Docstring explizit als
       Risikoszenario nennt, wurde dadurch NIE erkannt.
    3. "secret"/"token" fehlten als alleinstehende Schlüsselwörter - nur die Verbindungen
       "secret_key"/"access_token"/"auth_token" waren gelistet. Namen wie STRIPE_SECRET,
       CLIENT_SECRET oder CSRF_TOKEN (ohne "_KEY"-Suffix) wurden dadurch NIE erkannt.
    """

    def test_detects_prefixed_variable_name_with_quotes(self):
        diff = _diff("config.py", ['DATABASE_PASSWORD = "Sup3rSecretPassw0rd99"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_detects_unquoted_dotenv_style_assignment(self):
        diff = _diff(".env.local", ["DATABASE_PASSWORD=Sup3rSecretPassw0rd99"])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_detects_unquoted_shell_export(self):
        diff = _diff("setup.sh", ["export API_TOKEN=abcdef0123456789abcdef0123456789"])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_detects_unquoted_yaml_style_assignment(self):
        diff = _diff("docker-compose.yml", ["  DB_PASSWORD: Sup3rSecretPassw0rd99"])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_detects_bare_secret_keyword_without_key_suffix(self):
        diff = _diff("config.py", ['STRIPE_SECRET = "whsec_1234567890abcdefghijklmnopqrstuv"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_detects_bare_token_keyword_without_auth_prefix(self):
        diff = _diff("config.py", ['CSRF_TOKEN = "abcdef0123456789abcdef0123456789"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_unquoted_finding_is_still_fully_redacted(self):
        # Zusätzlicher Bugfix: _redact() zensierte bisher nur gequotete Werte - ein neu
        # erkannter unquoted-Fund hätte den echten Geheimwert unredigiert im Snippet gezeigt.
        diff = _diff(".env.local", ["DATABASE_PASSWORD=Sup3rSecretPassw0rd99"])
        findings = scan_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertNotIn("Sup3rSecretPassw0rd99", findings[0].snippet)
        self.assertIn("REDACTED", findings[0].snippet)

    def test_unquoted_placeholder_is_still_ignored(self):
        diff = _diff(".env.example", ["API_TOKEN=changeme"])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])

    def test_generic_key_alone_is_not_flagged_to_avoid_noise(self):
        # "key" bleibt bewusst NUR in Verbindung mit "api" gelistet - bloßes "key" wäre zu
        # generisch (primary_key, sort_key, cache_key, ...) und würde die Warnung entwerten.
        diff = _diff("models.py", ['primary_key = "not_a_real_secret_value_at_all"'])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])


class TestGenericPatternIgnoresProseContainingKeywordAsSubstring(unittest.TestCase):
    """
    Regression-Test für einen echten Fehlalarm (smart_knowledge_hub-Lauf, 2026-09-22): das
    Suffix `[a-z0-9_]*` nach dem Keyword erlaubte bisher JEDE Kleinbuchstaben-Fortsetzung, nicht
    nur echte Bezeichner-Suffixe. Ein Docstring wie "Einfache Tokenisierung: Kleinbuchstaben und
    alphanumerische Woerter." wurde dadurch als Secret gemeldet - "token" matchte als Präfix von
    "Tokenisierung", der folgende Doppelpunkt im Fließtext wurde fälschlich als
    Zuweisungsoperator gelesen und `secrets_clean` blockierte die Definition of Done, obwohl kein
    einziger echter Secret im Projekt stand.
    """

    def test_ignores_tokenisierung_docstring(self):
        diff = _diff("app/core/rag.py", [
            '    """Einfache Tokenisierung: Kleinbuchstaben und alphanumerische Woerter."""',
        ])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])

    def test_ignores_other_prose_words_containing_secret_as_substring(self):
        diff = _diff("docs/notes.md", [
            "Der Secretary-Dienst verwaltet Termine, keine Passwoerter.",
        ])
        findings = scan_diff(diff)
        self.assertEqual(findings, [])

    def test_still_detects_underscore_suffixed_keyword_after_the_fix(self):
        # Der Fix (Pflicht-`_` vor dem Suffix) darf die bereits abgesicherten Präfix-Muster
        # (siehe TestGenericPatternRecognizesRealWorldSecretNames oben) nicht wieder brechen.
        diff = _diff("config.py", ['AWS_SECRET_ACCESS_KEY = "abcdefghijklmno1234567890AB"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))

    def test_still_detects_camel_case_keyword_without_underscore(self):
        # Camel-Case-Namen (apiKey, secretToken) haben nie ein eigenes Präfix-Suffix, sondern
        # matchen das Keyword direkt an seiner eigenen Position im Wort - re.search() prüft
        # jede Startposition, das bleibt unverändert funktionsfähig.
        diff = _diff("config.js", ['secretToken = "abcdefghijklmno1234567890AB"'])
        findings = scan_diff(diff)
        self.assertTrue(any(f.rule == "Generisches Secret-Muster" for f in findings))


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
