"""
core/result_aggregator.py – Fasst die Ergebnisse aller Unteragenten zusammen

Der Orchestrator nutzt dieses Modul nach dem Sammeln aller Agenten-Ergebnisse,
um eine kohärente, vollständige Antwort für den Nutzer zu erstellen.
"""

from core.llm_factory import LLMFactory
from core.message_bus import AgentResult


SYNTHESIZE_SYSTEM_PROMPT = """Du bist der Hauptagent eines professionellen KI-Softwareentwickler-Teams.
Du hast gerade eine Aufgabe an dein Team verteilt und alle Ergebnisse gesammelt.

Deine Aufgabe ist jetzt:
1. Alle Agenten-Ergebnisse zu einer kohärenten, vollständigen Antwort zusammenzufassen
2. Die Ergebnisse logisch zu strukturieren (nicht einfach aneinanderzureihen)
3. Widersprüche oder Lücken zu identifizieren und zu kommentieren
4. Eine klare, übersichtliche Antwort für den Nutzer zu formulieren

Formatiere deine Antwort gut lesbar mit Markdown.
Beginne mit einer kurzen Zusammenfassung, dann die Detailergebnisse nach Bereich geordnet.
Schließe ab mit einer "Nächste Schritte" Sektion falls relevant.

Antworte auf Deutsch, außer der Nutzer fragt auf Englisch.
"""


class ResultAggregator:
    """Kombiniert Agenten-Ergebnisse zu einer einheitlichen Antwort."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self._llm = LLMFactory.create_gemini(model_name)

    async def synthesize(
        self,
        user_request: str,
        task_summary: str,
        results: list[AgentResult],
    ) -> str:
        """
        Fasst alle Agenten-Ergebnisse zu einer finalen Antwort zusammen.

        Args:
            user_request: Die ursprüngliche Nutzeranfrage
            task_summary: Kurze Zusammenfassung der Aufgabe
            results: Liste aller Agenten-Ergebnisse

        Returns:
            Formatierte, zusammengefasste Antwort für den Nutzer
        """
        if not results:
            return "❌ Keine Ergebnisse von den Agenten erhalten."

        # Erfolgreiche und fehlgeschlagene Ergebnisse trennen
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        # Ergebnisse für den Prompt formatieren
        results_text = self._format_results(successful, failed)

        prompt = f"""URSPRÜNGLICHE NUTZERANFRAGE:
{user_request}

AUFGABEN-ZUSAMMENFASSUNG:
{task_summary}

ERGEBNISSE DES TEAMS:
{results_text}

Bitte fasse jetzt alle Ergebnisse zu einer vollständigen, kohärenten Antwort zusammen."""

        return await self._llm.generate(prompt, SYNTHESIZE_SYSTEM_PROMPT)

    def _format_results(
        self,
        successful: list[AgentResult],
        failed: list[AgentResult]
    ) -> str:
        """Formatiert alle Agenten-Ergebnisse für den Synthesize-Prompt."""
        sections = []

        for result in successful:
            duration_str = f" (⏱ {result.duration_seconds:.1f}s)" if result.duration_seconds > 0 else ""
            sections.append(
                f"### ✅ {result.agent_name}{duration_str}\n\n{result.content}"
            )

        for result in failed:
            sections.append(
                f"### ❌ {result.agent_name} (FEHLER)\n\nFehler: {result.error}"
            )

        return "\n\n---\n\n".join(sections)
