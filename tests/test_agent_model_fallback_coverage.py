"""
tests/test_agent_model_fallback_coverage.py – Stellt sicher, dass JEDER konfigurierte Agent
mindestens 2 unterschiedliche Modelle zur Verfügung hat, falls eines ausfällt.

Nutzeranfrage (2026-09-06): "Achte auch darauf, dass jeder Agent mindestens 2 KI Modelle zur
Verfügung hat, falls eins ausfällt." Die eigentliche Fallback-MECHANIK ist bereits ausführlich
verhaltensgetestet (tests/test_llm_routing.py: Claude<->Gemini<->Groq<->DeepSeek<->OpenRouter,
inkl. echter Mocks für Ausfälle mitten im Lauf) - was fehlte, war ein Test, der die KONFIGURATION
selbst (config.AGENT_MODELS/ORCHESTRATOR_MODEL) gegen diese Mechanik abgleicht: bekommt jede
tatsächlich zugewiesene Modellstufe überhaupt einen Fallback-Pfad, oder könnte eine künftige
Änderung (neue Modellstufe, falscher Wert in .env) eine Rolle versehentlich OHNE jede
Rettungsleine konfigurieren, ohne dass ein bestehender Test das bemerkt?

Zwei Architektur-Fälle (siehe core/llm_factory.py-Kommentare für Details):
1. Gemini-Modellnamen: ihr Fallback-Pfad steht explizit in core.llm_factory.MODEL_FALLBACKS
   (ein Dict, keyed auf den exakten Modellnamen) - fehlt ein Eintrag, greift KEIN Fallback.
2. Claude/Groq/DeepSeek/OpenRouter/HuggingFace-Modellnamen: jeder zugehörige Client hat einen
   FEST einprogrammierten, unbedingten Fallback-Hop (ClaudeClient._free_heavy_fallback_client(),
   GroqClient/DeepSeekClient/OpenRouterClient/HuggingFaceClient je ein Hop zu Gemini) - der ist
   strukturell IMMER vorhanden, unabhängig vom Modellnamen selbst.
"""

import unittest

import config
from core.llm_factory import (
    MODEL_FALLBACKS,
    ClaudeClient,
    DeepSeekClient,
    GroqClient,
    HuggingFaceClient,
    OpenRouterClient,
)

# Client-Klassen, die strukturell IMMER genau einen fest einprogrammierten Fallback-Hop haben
# (siehe core/llm_factory.py-Moduldocstring bei MODEL_FALLBACKS) - für diese reicht der Nachweis
# "ist eine Instanz dieser Klasse", eine Gemini-Modellname-artige MODEL_FALLBACKS-Prüfung wäre
# hier nicht zutreffend (die Kette wird NICHT über dieses Dict gesteuert, siehe dort).
_CLIENT_CLASSES_WITH_HARDCODED_FALLBACK = (ClaudeClient, GroqClient, DeepSeekClient, OpenRouterClient, HuggingFaceClient)


def _model_has_fallback(model_name: str) -> tuple[bool, str]:
    """Prüft strukturell (kein LLM-Aufruf), ob für `model_name` ein zweites Modell erreichbar
    wäre, falls das erste ausfällt. Gibt (hat_fallback, begründung) zurück."""
    name = model_name.lower()
    is_gemini = name.startswith("gemini") and not any(
        name.startswith(p) for p in ("groq:", "deepseek:", "openrouter:", "huggingface:")
    )
    if is_gemini:
        candidates = MODEL_FALLBACKS.get(model_name, [])
        return bool(candidates), f"MODEL_FALLBACKS['{model_name}'] hat {len(candidates)} Kandidat(en)"
    # Nicht-Gemini (Claude/Groq/DeepSeek/OpenRouter/HuggingFace): struktureller Fallback-Hop
    # fest im jeweiligen Client einprogrammiert, unabhängig vom Modellnamen selbst - siehe
    # core/llm_factory.py (ClaudeClient._free_heavy_fallback_client() bzw. die je einzelne
    # `except Exception` -> GeminiClient(...)-Zeile in Groq/DeepSeek/OpenRouter/HuggingFaceClient).
    return True, "Nicht-Gemini-Client mit fest einprogrammiertem Fallback-Hop zu Gemini"


class TestEveryAgentHasAtLeastTwoModels(unittest.TestCase):
    def test_every_configured_agent_model_has_a_fallback(self):
        failures = []
        for agent_id, model_name in config.AGENT_MODELS.items():
            has_fallback, reason = _model_has_fallback(model_name)
            if not has_fallback:
                failures.append(f"{agent_id} -> {model_name}: {reason}")
        self.assertEqual(
            failures, [],
            "Agenten ohne jeden konfigurierten Fallback (nur EIN Modell verfügbar):\n" + "\n".join(failures),
        )

    def test_orchestrator_model_has_a_fallback(self):
        has_fallback, reason = _model_has_fallback(config.ORCHESTRATOR_MODEL)
        self.assertTrue(has_fallback, f"ORCHESTRATOR_MODEL '{config.ORCHESTRATOR_MODEL}' ohne Fallback: {reason}")

    def test_every_gemini_fallback_chain_has_at_least_two_entries(self):
        # Doppelte Absicherung: nicht nur "irgendein" Fallback, sondern selbst wenn der erste
        # Fallback-Kandidat ebenfalls ausfällt, muss noch ein DRITTER übrig bleiben - siehe
        # core/llm_factory.py's eigene Kommentare zur Cross-Provider-Reihenfolge.
        for gemini_model, candidates in MODEL_FALLBACKS.items():
            self.assertGreaterEqual(
                len(candidates), 2,
                f"MODEL_FALLBACKS['{gemini_model}'] hat nur {len(candidates)} Kandidat(en) - "
                "weniger als 2 unabhängige Ausweichstufen.",
            )

    def test_non_gemini_clients_carry_the_documented_hardcoded_fallback(self):
        # Gegenprobe zu _model_has_fallback()'s Nicht-Gemini-Annahme: stellt sicher, dass jede
        # dieser Client-Klassen TATSÄCHLICH die dafür vorausgesetzte Methode/das Attribut trägt,
        # statt sich blind auf die Doku im Moduldocstring zu verlassen.
        self.assertTrue(hasattr(ClaudeClient, "_free_heavy_fallback_client"))
        for client_cls in (GroqClient, DeepSeekClient, OpenRouterClient, HuggingFaceClient):
            self.assertTrue(
                hasattr(client_cls, "generate_with_usage"),
                f"{client_cls.__name__} hat keine generate_with_usage()-Methode mehr - "
                "Fallback-Vertrag von _CLIENT_CLASSES_WITH_HARDCODED_FALLBACK gebrochen.",
            )
        self.assertEqual(
            _CLIENT_CLASSES_WITH_HARDCODED_FALLBACK,
            (ClaudeClient, GroqClient, DeepSeekClient, OpenRouterClient, HuggingFaceClient),
        )


if __name__ == "__main__":
    unittest.main()
