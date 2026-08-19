"""
core/task_manager.py – Analysiert Nutzeraufgaben und zerlegt sie in Teilaufgaben (30 Spezialisten)
"""

import json
import re
from typing import Optional
from core.llm_factory import LLMFactory
from core.message_bus import AgentTask
import uuid


# ──────────────────────────────────────────────────────────
# Alle verfügbaren Agenten (30 Spezialisten)
# ──────────────────────────────────────────────────────────

AVAILABLE_AGENTS = {
    # ── Phase 1: Führung, Planung & Recherche ─────────────
    "team_lead": {
        "name": "Teamleiter (Engineering Manager)",
        "phase": 1,
        "description": "Definiert Projektziele, DoD, Trade-Off-Entscheidungen und steuert den Team-Fokus.",
    },
    "product_owner": {
        "name": "Product Owner",
        "phase": 1,
        "description": "Definiert Produktvision, MVP-Scope (MoSCoW), Release-Roadmap und User Journeys.",
    },
    "business_analyst": {
        "name": "Business Analyst",
        "phase": 1,
        "description": "Analysiert Anforderungen, erstellt User Stories und Akzeptanzkriterien (Given/When/Then).",
    },
    "web_research": {
        "name": "Web-Recherche Specialist",
        "phase": 1,
        "description": "Recherchiert aktuelle Framework-Dokumentationen, Best Practices, Open-Source-Pakete und Markttrends.",
    },

    # ── Phase 2: Architektur & FinOps ─────────────────────
    "architect": {
        "name": "Software-Architekt",
        "phase": 2,
        "description": "Entwirft Systemarchitektur, API-Contracts, Komponenten-Blueprints und ADRs.",
    },
    "finops": {
        "name": "Cost & FinOps Engineer",
        "phase": 2,
        "description": "Kalkuliert Cloud-Kosten (AWS/GCP/Hetzner), TCO, Serverless vs. VM und AI-Token-Budgets.",
    },

    # ── Phase 3: Kern-Entwicklung ─────────────────────────
    "frontend": {
        "name": "Frontend-Entwickler",
        "phase": 3,
        "description": "Implementiert React, Vue, Next.js, HTML/CSS und interaktive Web-UIs.",
    },
    "backend": {
        "name": "Backend-Entwickler",
        "phase": 3,
        "description": "Entwickelt REST/FastAPI/Node Server-Logik, Authentifizierung und APIs.",
    },
    "database": {
        "name": "Datenbank-Entwickler",
        "phase": 3,
        "description": "Entwirft SQL/NoSQL Datenmodelle, ORM-Schemas, Indizes und Migrationen.",
    },
    "api_integration": {
        "name": "API & Integration Specialist",
        "phase": 3,
        "description": "OpenAPI 3.1 Specs, GraphQL, Webhooks mit HMAC-Sicherheit, Stripe, OAuth2.",
    },
    "data_engineer": {
        "name": "Data Engineer",
        "phase": 3,
        "description": "Event-Streaming (Kafka/RabbitMQ), Redis Caching-Layer und ETL-Pipelines.",
    },
    "mobile": {
        "name": "Mobile-Entwickler",
        "phase": 3,
        "description": "Entwickelt Cross-Platform Apps mit Flutter, React Native, iOS & Android.",
    },
    "ml": {
        "name": "KI/ML-Entwickler",
        "phase": 3,
        "description": "LLM-APIs, RAG-Systeme, Embeddings, Vector Stores und ML-Pipelines.",
    },
    "performance": {
        "name": "Performance-Ingenieur",
        "phase": 3,
        "description": "Load-Testing, Profiling, Query-Optimierung und Latenz-Minimierung.",
    },

    # ── Phase 3: Medien, Content & Design ─────────────────
    "image_generator": {
        "name": "Bild- & Grafik-Designer",
        "phase": 3,
        "description": "Erstellt SVG-Grafiken/Logos und optimierte Bild-Prompts für Imagen 3 / Midjourney.",
    },
    "copywriter": {
        "name": "Copywriter & Content Specialist",
        "phase": 3,
        "description": "Schreibt Landingpage-Texte, UI-Microcopy (Buttons, Errors), SEO-Texte und FAQs.",
    },
    "ui_ux": {
        "name": "UI/UX Designer",
        "phase": 3,
        "description": "Wireframes, Design-Systeme, Farbpaletten und Design-Tokens.",
    },
    "i18n": {
        "name": "Internationalisierungs-Spezialist",
        "phase": 3,
        "description": "Mehrsprachigkeit (i18n/l10n), RTL-Unterstützung und Formatierungen.",
    },
    "documentation": {
        "name": "Dokumentant",
        "phase": 3,
        "description": "API-Dokumentation, Inline-Kommentare und Architekturguides.",
    },

    # ── Phase 3: Infrastruktur & Qualität ─────────────────
    "devops": {
        "name": "DevOps-Ingenieur",
        "phase": 3,
        "description": "Dockerfile, docker-compose, CI/CD GitHub Actions Pipelines, K8s.",
    },
    "tester": {
        "name": "QA-Tester",
        "phase": 3,
        "description": "Unit-Tests (pytest), Integrationstests und E2E-Testpläne.",
    },
    "security": {
        "name": "Sicherheits-Analyst",
        "phase": 3,
        "description": "OWASP Top 10, Auth-Audits, Input-Sanitization, Security-Headers.",
    },

    # ── Phase 4: Review, Refactoring, Compliance & Hygiene
    "code_reviewer": {
        "name": "Code-Reviewer",
        "phase": 4,
        "description": "Qualitätskontrolle, Konsistenzprüfung, Code-Scoring und Bug-Detektion.",
    },
    "refactoring": {
        "name": "Refactoring Specialist",
        "phase": 4,
        "description": "Beseitigt Code Smells, refaktoriert Module und sichert strikte Typsicherheit.",
    },
    "compliance": {
        "name": "Legal & Compliance Specialist",
        "phase": 4,
        "description": "DSGVO/GDPR-Audits, Lizenzprüfung (GPL vs MIT), WCAG 2.1 Barrierefreiheit.",
    },
    "project_cleaner": {
        "name": "Projekt-Hygiene & Struktur-Wächter",
        "phase": 4,
        "description": "Bereinigt alte/tote Dateien, verhindert Projekt-Bloat und optimiert Ordnerstrukturen.",
    },

    # ── Phase 5: Ausbildung, Retrospektive & Utilities ────
    "agent_trainer": {
        "name": "Ausbilder & Agent-Optimizer",
        "phase": 4,
        "description": "Optimiert System-Prompts, analysiert Fehler der Agenten und bildet neue Rollen aus.",
    },
    "retrospective": {
        "name": "Retrospektive & Lessons Learned Agent",
        "phase": 4,
        "description": "Erstellt die Abschluss-Retrospektive (Was lief gut/schlecht, Lessons Learned).",
    },
    "readme": {
        "name": "README-Agent",
        "phase": 3,
        "description": "Erstellt oder aktualisiert die Projekt-README.md.",
    },
    "github": {
        "name": "GitHub-Agent",
        "phase": 3,
        "description": "Generiert Commit-Messages und führt automatische Git-Pushes durch.",
    },
}

DECOMPOSE_SYSTEM_PROMPT = """Du bist ein erfahrener Principal Software-Architekt und Engineering Lead.
Analysiere die Aufgabe und wähle NUR die wirklich notwendigen Spezialisten aus, um maximale Token-Effizienz zu gewährleisten.

Antworte NUR mit einem gültigen JSON-Objekt. Keine Erklärungen davor oder danach.

Das JSON-Format ist exakt wie folgt:
{
  "task_summary": "Kurze Zusammenfassung der Gesamtaufgabe",
  "project_slug": "kurzer_projekt_ordnername_ohne_sonderzeichen",
  "required_agents": [
    {
      "agent_id": "<agent_id aus der Liste>",
      "task": "Präzise, token-effiziente Aufgabenbeschreibung für diesen Agenten"
    }
  ]
}

Verfügbare Agenten-IDs:
team_lead, product_owner, business_analyst, web_research,
architect, finops,
frontend, backend, database, api_integration, data_engineer, mobile, ml, performance,
image_generator, copywriter, ui_ux, i18n, documentation, devops, tester, security,
code_reviewer, refactoring, compliance, project_cleaner, agent_trainer, readme, github

Wichtige Regeln:
- Wähle NUR die zwingend erforderlichen Agenten aus (Token-Sparsamkeit)
- Halte die Aufgabenbeschreibungen klar und fokussiert
- code_reviewer bei Code-Generierung einschließen
- project_cleaner einbeziehen, wenn Verzeichnisstrukturen aufgeräumt oder schlank gehalten werden sollen
"""


class TaskManager:
    """Analysiert und zerlegt Nutzeraufgaben in parallelisierbare Teilaufgaben."""

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self._llm = LLMFactory.create_gemini(model_name)

    async def decompose(
        self,
        user_request: str,
        conversation_context: Optional[str] = None
    ) -> tuple[str, str, list[AgentTask]]:
        agents_description = "\n".join([
            f"- {agent_id} [Phase {info['phase']}]: {info['description']}"
            for agent_id, info in AVAILABLE_AGENTS.items()
            if agent_id not in ("retrospective", "agent_trainer")
        ])

        context_section = ""
        if conversation_context:
            context_section = f"\n\nVorheriger Kontext (gekürzt):\n{conversation_context[:1000]}"

        prompt = f"""Analysiere folgende Nutzeranfrage und erstelle einen effizienten Aufgabenplan:

NUTZERANFRAGE:
{user_request}
{context_section}

VERFÜGBARE AGENTEN:
{agents_description}

Erstelle jetzt das JSON mit den Teilaufgaben."""

        raw_json = await self._llm.generate_json(prompt, DECOMPOSE_SYSTEM_PROMPT)
        plan = self._parse_plan(raw_json)
        task_summary = plan.get("task_summary", "Aufgabe wird bearbeitet...")
        project_slug = plan.get("project_slug", "project")
        required_agents = plan.get("required_agents", [])

        agent_tasks = []
        for agent_info in required_agents:
            agent_id = agent_info.get("agent_id", "")
            if agent_id not in AVAILABLE_AGENTS:
                continue

            agent_tasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                agent_id=agent_id,
                description=agent_info.get("task", ""),
                context=user_request[:1500],
            ))

        return task_summary, project_slug, agent_tasks

    def _parse_plan(self, raw_json: str) -> dict:
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_json)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return {"task_summary": "Aufgabe analysiert", "project_slug": "project", "required_agents": []}
