"""
agents/web_research_agent.py – Web Research & Information Scraper Agent mit Tavily Live-Search

Spezialisiert auf:
- Echte Live-Web-Recherche via Tavily API (Dokumentationen, Best Practices, GitHub)
- Automatischer Fallback auf LLM-Wissensbasis, falls das Tavily-Monatskontingent erschöpft ist
- Strukturierte Bereitstellung von Fakten & Live-Code-Snippets für das Entwicklerteam
"""

import httpx

from agents.base_agent import BaseAgent
from config import TAVILY_API_KEY
from core.message_bus import AgentResult, AgentTask
from core.token_guard import token_guard


class WebResearchAgent(BaseAgent):
    """
    Spezialisierter Agent für Live-Web-Recherche via Tavily API mit nahtlosem Fallback.
    Läuft in Phase 1 oder Phase 3.
    """

    def __init__(self):
        super().__init__(agent_id="web_research", name="Web-Recherche & Info Specialist")

    @property
    def system_prompt(self) -> str:
        return """Du bist ein erstklassiger Tech-Researcher, Open-Source Intelligence (OSINT) Analyst und Data Extractor.

Deine Aufgabe ist es, aktuelle Technologien, Framework-Dokumentationen, API-Spezifikationen,
Bibliotheken, Marktlösungen und Best Practices strukturiert zu recherchieren, zu analysieren und dem Team bereitzustellen.

Deine Kernkompetenzen:
- Extrahieren von Best Practices aus offiziellen Dokumentationen (MDN, Python Docs, Next.js, FastAPI, etc.)
- Wettbewerbs- & Marktanalysen ähnlicher Produkte
- Identifikation der besten und modernsten Open-Source-Pakete (GitHub Stars, Wartungsstatus, Lizenz)
- Strukturierte Zusammenfassung von technischen RFCs und API-Änderungen

Dein Standard-Ausgabeformat:

## 🌐 Web-Recherche & Informationsbericht

### 1. 🔍 Zusammenfassung der Recherche-Ergebnisse
- **Kernaussage:** [Zentrales Ergebnis in 2 Sätzen]
- **Relevanz für das Projekt:** [Warum dies für die Implementierung wichtig ist]

### 2. 📚 Empfohlene Bibliotheken & Tech-Komponenten
| Paket / Tool | Version / Lizenz | Warum empfohlen? | Alternative |
|---|---|---|---|
| [z. B. tanstack/react-query] | MIT | Optimal für Server-State-Management | SWR |
| [z. B. pydantic v2] | MIT | 5x schnellerer Rust-Core | Marshmallow |

### 3. 📋 Best-Practice Code-Snippets & Integrationshinweise
```python
# Auszug / Best Practice aus aktuellen Framework-Dokumentationen
```

### 4. 💡 Wichtige Hinweise & Fallstricke (Gotchas)
- [Bekannte Bugs / Breaking Changes in aktuellen Versionen]
- [Vermeidungsstrategie]

Antworte auf Deutsch. Faktenbasiert, auf dem neuesten Stand der Technik und sofort nützlich für das Entwicklerteam."""

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Führt Live-Web-Recherche über Tavily durch und reichert das Ergebnis mit dem KI-Modell an.
        Fällt automatisch auf die reine LLM-Recherche zurück, falls Tavily-Tokens erschöpft sind.
        """
        live_search_context = ""

        # 1. Versuche Live-Recherche via Tavily API
        if TAVILY_API_KEY and not token_guard.is_model_exhausted("tavily_search"):
            try:
                search_query = task.description[:200]
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": TAVILY_API_KEY,
                            "query": search_query,
                            "search_depth": "basic",
                            "include_answer": True,
                            "max_results": 4,
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        answer = data.get("answer", "")
                        results = data.get("results", [])
                        
                        live_search_context = "\n\n--- ECHTE LIVE-SUCHERGEBNISSE (TAVILY) ---\n"
                        if answer:
                            live_search_context += f"Direkte KI-Antwort: {answer}\n\n"
                        for item in results:
                            live_search_context += f"Quelle: {item.get('title')} ({item.get('url')})\n{item.get('content')}\n\n"
                    elif resp.status_code in (401, 402, 429):
                        token_guard.mark_model_exhausted("tavily_search", "Tavily Quota/Balance Exceeded")
            except Exception as e:
                token_guard.mark_model_exhausted("tavily_search", str(e))

        # 2. KI-Agent synthetisiert den Bericht (inkl. evtl. gefundener Live-Daten)
        augmented_prompt = task.description
        if live_search_context:
            augmented_prompt += f"\n\nNutze folgende aktuelle Live-Suchergebnisse für deine Analyse:\n{live_search_context}"

        original_task_desc = task.description
        task.description = augmented_prompt
        try:
            res = await super().execute(task)
        finally:
            task.description = original_task_desc

        return res
