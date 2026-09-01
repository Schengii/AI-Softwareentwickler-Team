"""
tests/test_review_gate.py – Testet core/review_gate.py gegen die drei tatsächlichen
Ausgabeformate von code_reviewer/security/compliance (agents/orchestrator.py.REVIEW_ONLY_AGENT_IDS).

Die Beispieltexte sind bewusst nah an den in den jeweiligen System-Prompts vorgeschriebenen
Formaten gehalten (agents/code_reviewer_agent.py, agents/security_agent.py,
agents/compliance_agent.py), nicht an einer idealisierten Vereinfachung davon.
"""

import unittest

from core.review_gate import find_critical_findings, route_findings_to_owners

CODE_REVIEWER_REPORT_WITH_FINDING = """## Code-Review Report

### Gesamtbewertung
⭐⭐⭐ Solide Grundstruktur, aber ein kritischer Sicherheitsfehler.

### 🔴 Kritische Probleme (müssen behoben werden)
SQL-Injection in `backend/db.py`: die Funktion `get_user()` baut die Query per
String-Concatenation statt parametrisiert. Fix: `cursor.execute("... WHERE id = ?", (user_id,))`.

### 🟡 Mittlere Probleme (sollten behoben werden)
Fehlende Typannotationen in einigen Funktionen.

### ✅ Gut gelöste Aspekte
Klare Trennung zwischen Routing und Business-Logik.
"""

CODE_REVIEWER_REPORT_NO_FINDING = """## Code-Review Report

### Gesamtbewertung
⭐⭐⭐⭐⭐ Sehr sauberer Code.

### 🔴 Kritische Probleme (müssen behoben werden)
Keine kritischen Probleme gefunden.

### 🟡 Mittlere Probleme (sollten behoben werden)
Keine.
"""

SECURITY_REPORT_WITH_FINDING = """## 🔒 Security-Report

### Findings
1. **SQL-Injection in `backend/db.py`** - Schweregrad: Kritisch

   Die Funktion get_user() ist anfällig für SQL-Injection über den user_id-Parameter,
   da die Query nicht parametrisiert wird. Ein Angreifer könnte beliebige Daten auslesen.

2. **Fehlendes Rate Limiting** - Schweregrad: Mittel

   Der Login-Endpunkt hat kein Rate Limiting, was Brute-Force-Angriffe erleichtert.
"""

SECURITY_REPORT_NO_FINDING = """## 🔒 Security-Report

Schweregrad-Bewertung: keine kritischen Funde in diesem Durchlauf. Alle Endpunkte nutzen
parametrisierte Queries und validieren Eingaben korrekt.
"""

COMPLIANCE_REPORT_WITH_FINDING = """## ⚖️ Legal, Privacy & Compliance Audit

### 2. 📜 Open-Source-Lizenzanalyse
| Abhängigkeit / Komponente | Lizenz | Risikostufe (Grün / Gelb / Rot) | Handlungsempfehlung |
|---|---|---|---|
| `requirements.txt` (flask-login) | AGPL-3.0 | 🔴 Achtung Copyleft | Prüfen ob proprietärer Source Code offengelegt werden müsste |
| fastapi | MIT | 🟢 Sicher | Gewerblich uneingeschränkt nutzbar |
"""

COMPLIANCE_REPORT_NO_FINDING = """## ⚖️ Legal, Privacy & Compliance Audit

### 2. 📜 Open-Source-Lizenzanalyse
| Abhängigkeit / Komponente | Lizenz | Risikostufe (Grün / Gelb / Rot) | Handlungsempfehlung |
|---|---|---|---|
| fastapi | MIT | 🟢 Sicher | Gewerblich uneingeschränkt nutzbar |
"""


class TestFindCriticalFindings(unittest.TestCase):
    def test_code_reviewer_heading_format_detects_finding(self):
        findings = find_critical_findings(CODE_REVIEWER_REPORT_WITH_FINDING)
        self.assertEqual(len(findings), 1)
        self.assertIn("SQL-Injection", findings[0])
        self.assertIn("backend/db.py", findings[0])

    def test_code_reviewer_no_finding_confirmation_is_not_a_finding(self):
        findings = find_critical_findings(CODE_REVIEWER_REPORT_NO_FINDING)
        self.assertEqual(findings, [])

    def test_security_freeform_format_detects_finding(self):
        findings = find_critical_findings(SECURITY_REPORT_WITH_FINDING)
        self.assertTrue(any("SQL-Injection" in f and "backend/db.py" in f for f in findings))
        # Das Mittel-Finding darf NICHT als kritisch gemeldet werden.
        self.assertFalse(any("Rate Limiting" in f for f in findings))

    def test_security_no_finding_confirmation_is_not_a_finding(self):
        findings = find_critical_findings(SECURITY_REPORT_NO_FINDING)
        self.assertEqual(findings, [])

    def test_compliance_table_row_format_detects_finding(self):
        findings = find_critical_findings(COMPLIANCE_REPORT_WITH_FINDING)
        self.assertTrue(any("AGPL-3.0" in f for f in findings))
        self.assertFalse(any("MIT" in f and "🟢" in f for f in findings))

    def test_compliance_no_finding_confirmation_is_not_a_finding(self):
        findings = find_critical_findings(COMPLIANCE_REPORT_NO_FINDING)
        self.assertEqual(findings, [])

    def test_empty_content_returns_no_findings(self):
        self.assertEqual(find_critical_findings(""), [])

    def test_findings_are_deduplicated(self):
        # Derselbe Fund darf nicht doppelt (z.B. einmal ueber den Ueberschriften- und einmal
        # ueber den Freitext-Absatz-Durchlauf) auftauchen.
        findings = find_critical_findings(CODE_REVIEWER_REPORT_WITH_FINDING)
        normalized = [f.lower().strip() for f in findings]
        self.assertEqual(len(normalized), len(set(normalized)))


class TestRouteFindingsToOwners(unittest.TestCase):
    def test_finding_with_known_file_is_routed_to_owner(self):
        file_owners = {"backend/db.py": "backend", "frontend/app.js": "frontend"}
        findings = [("code_reviewer", "SQL-Injection in `backend/db.py` gefunden.")]

        agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

        self.assertIn("backend", agents_to_fix)
        self.assertIn("SQL-Injection", agents_to_fix["backend"][0])
        self.assertIn("[code_reviewer]", agents_to_fix["backend"][0])
        self.assertEqual(unrouted, [])

    def test_finding_with_short_filename_matches_full_owned_path(self):
        file_owners = {"backend/db.py": "backend"}
        findings = [("security", "Problem in `db.py`.")]

        agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

        self.assertIn("backend", agents_to_fix)
        self.assertEqual(unrouted, [])

    def test_finding_without_matching_file_is_unrouted(self):
        file_owners = {"backend/db.py": "backend"}
        findings = [("compliance", "Lizenzrisiko im gesamten Projekt, kein einzelner Datei-Bezug.")]

        agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

        self.assertEqual(agents_to_fix, {})
        self.assertEqual(len(unrouted), 1)
        self.assertIn("[compliance]", unrouted[0])

    def test_multiple_findings_for_same_owner_are_grouped(self):
        file_owners = {"backend/db.py": "backend"}
        findings = [
            ("code_reviewer", "Problem A in `backend/db.py`."),
            ("security", "Problem B in `backend/db.py`."),
        ]

        agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

        self.assertEqual(len(agents_to_fix["backend"]), 2)
        self.assertEqual(unrouted, [])


if __name__ == "__main__":
    unittest.main()
