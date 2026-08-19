"""
core/result_aggregator.py – Fasst die Ergebnisse aller Unteragenten token-effizient zusammen
"""

from core.llm_factory import LLMFactory
from core.message_bus import AgentResult


SYNTHESIZE_SYSTEM_PROMPT = """Du bist der Hauptagent eines professionellen KI-Softwareentwickler-Teams.
Du hast die Teilergebnisse deines Teams gesammelt und erstellst nun die finale, konsolidierte Antwort für den Nutzer.

Deine Aufgabe:
1. Präsentiere eine klare, lückenlose Gesamtlösung mit logischer Struktur.
2. Der Nutzer soll nicht die internen Rohdaten sehen, sondern das geprüfte, saubere Gesamtergebnis (inkl. vollständiger, funktionsfähiger Code- und Konfigurationsdateien).
3. Achte auf eine prägnante, token-effiziente Formulierung ohne unnötige Füllwörter.
4. Schließe mit konkreten Hinweisen zur Inbetriebnahme ab.

Antworte auf Deutsch.
"""


class ResultAggregator:
    """Kombiniert Agenten-Ergebnisse zu einer einheitlichen Antwort."""

    def __init__(self, model_name: str = "gemini-3.6-flash"):
        self._llm = LLMFactory.create_gemini(model_name)

    async def synthesize(
        self,
        user_request: str,
        task_summary: str,
        results: list[AgentResult],
    ) -> tuple[str, int]:
        """
        Fasst alle Agenten-Ergebnisse zu einer finalen Antwort zusammen.

        Returns:
            Tuple aus (Antworttext, verbrauchte Tokens)
        """
        if not results:
            return "❌ Keine Ergebnisse von den Agenten erhalten.", 0

        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        results_text = self._format_results(successful, failed)

        prompt = f"""URSPRÜNGLICHE NUTZERANFRAGE:
{user_request}

AUFGABEN-ZUSAMMENFASSUNG:
{task_summary}

ERGEBNISSE DES TEAMS:
{results_text}

Erstelle jetzt das finale, strukturierte Gesamtergebnis für den Nutzer."""

        resp = await self._llm.generate_with_usage(prompt, SYNTHESIZE_SYSTEM_PROMPT)
        return resp.text, resp.total_tokens

    def _format_results(
        self,
        successful: list[AgentResult],
        failed: list[AgentResult]
    ) -> str:
        """Formatiert Teamergebnisse kompakt."""
        sections = []

        for result in successful:
            sections.append(
                f"### [{result.agent_name}]\n{result.content}"
            )

        for result in failed:
            sections.append(
                f"### [{result.agent_name}] FEHLER: {result.error}"
            )

        return "\n\n---\n\n".join(sections)
