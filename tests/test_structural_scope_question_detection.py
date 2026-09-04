"""
tests/test_structural_scope_question_detection.py – Testet core/review_gate.py.
find_structural_scope_questions()'s erweiterte Muster-Erkennung.

Realer Fund (Team-Retrospektive, webhookshield-Projekt, 2026-09-03): in EINEM Lauf blieben 3
offene Rückfragen zu einem leeren Projektverzeichnis unbeantwortet liegen, weil sie alle
inhaltlich zur selben Frageklasse gehörten ("es existiert kein Code - darf ich ihn selbst
anlegen?"), aber nur eine einzige zur ursprünglich engen Regex passte (nur "von Grund auf neu
ERSTELLEN", nicht "AUFSETZEN"). Diese Tests fixieren die drei tatsächlichen Originalfragen aus
`.ai_team_status.json` als Regressionsschutz.
"""

import unittest

from core.review_gate import find_structural_scope_questions

_REAL_WEBHOOKSHIELD_QUESTIONS = [
    "Könnten Sie bitte bestätigen, ob das Projektverzeichnis korrekt initialisiert wurde oder "
    "ob ich ein neues Projekt von Grund auf neu aufsetzen soll? Wenn es ein bestehendes Projekt "
    "geben sollte, scheint der Zugriff darauf aktuell nicht möglich zu sein.",
    "Können Sie die Dateien des Projekts bereitstellen oder mir mitteilen, in welchem "
    "Verzeichnis ich arbeiten soll? Aktuell ist das Arbeitsverzeichnis komplett leer.",
    "Soll ich das Projekt 'WebhookShield' basierend auf den Anforderungen (Webhook-Empfang, "
    "Datenbank-Persistenz, Sicherheits-Check) neu aufsetzen? Das Projektverzeichnis ist "
    "komplett leer.",
]

_REAL_INCIDENTPILOT_QUESTION = (
    "Soll ich die Grundstruktur der Anwendung (Backend mit FastAPI, Frontend mit Vite) "
    "inklusive der Test-Infrastruktur von Grund auf neu erstellen, um die geforderten Tests "
    "implementieren zu können?"
)

# Eine echte fachliche Unklarheit, die NUR ein Mensch beantworten kann - darf NIEMALS als
# Struktur-Scope-Frage erkannt werden (siehe Docstring von find_structural_scope_questions).
_GENUINE_HUMAN_QUESTION = "Welche Zahlungsanbieter (Stripe, PayPal, ...) sollen unterstützt werden?"


class TestStructuralScopeQuestionDetection(unittest.TestCase):
    def test_detects_all_three_real_webhookshield_questions(self):
        matched = find_structural_scope_questions(_REAL_WEBHOOKSHIELD_QUESTIONS)
        self.assertEqual(
            set(matched), set(_REAL_WEBHOOKSHIELD_QUESTIONS),
            f"Nicht erkannt: {set(_REAL_WEBHOOKSHIELD_QUESTIONS) - set(matched)}",
        )

    def test_still_detects_original_incidentpilot_question(self):
        matched = find_structural_scope_questions([_REAL_INCIDENTPILOT_QUESTION])
        self.assertEqual(matched, [_REAL_INCIDENTPILOT_QUESTION])

    def test_does_not_match_genuine_human_only_question(self):
        matched = find_structural_scope_questions([_GENUINE_HUMAN_QUESTION])
        self.assertEqual(matched, [])


if __name__ == "__main__":
    unittest.main()
